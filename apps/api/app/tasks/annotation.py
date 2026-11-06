"""Worker tasks for genome annotation with Bakta and Prokka.

Before a run the worker checks again everything the user confirmed: the assembly's contigs (SHA-256), the database
(Bakta: still installed, same content checksum, Bakta's folder check; Prokka: the package's files, same checksum)
and the programs behind each step. If the steps that can run differ from the confirmed ones, the job fails and
nothing runs. Every output stays in the job's results folder; the annotator's own files are kept unchanged and
ARVA writes its feature index (features.jsonl) beside them.
"""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arva_core.annotation import summarize, write_jsonl
from arva_tools import ToolExecutionError, ToolTimeoutError
from arva_tools import bakta as bakta_tool
from arva_tools import prokka as prokka_tool
from arva_tools.bakta import BaktaAdapter, BaktaParams
from arva_tools.native_common import NativeRefusal, native_relative
from arva_tools.prokka import ProkkaAdapter, ProkkaParams

from app.core.config import get_settings
from app.models import Annotation, Assembly, DatabaseStatus, ReferenceDatabase
from app.services import annotation as svc
from app.services.databases import DatabaseError, check_bakta_dir
from app.tasks.common import JobCancelled, JobContext, JobFailure, run_job
from app.tasks.tools import (
    _await_native,
    _native_executor,
    _rel,
    _resolve_tool,
    _run,
    _sha256,
    _StageMonitor,
    native_timeout_error,
)

INPUT_NAME = "genome.fna"
FEATURES_FILE = "features.jsonl"


def _assembly(ctx: JobContext) -> Assembly:
    planned = (ctx.job.parameters or {})["assembly"]
    a = ctx.db.get(Assembly, planned["assembly_id"])
    if a is None or a.sample_id != ctx.job.sample_id:
        raise JobFailure(f"Assembly {planned['assembly_id']} no longer exists",
                         "assembly_missing", assembly=str(planned["assembly_id"]))
    src = ctx.path(a.contigs_path)
    if not src.is_file():
        raise JobFailure("The contigs file of the assembly is missing on disk",
                         "contigs_missing", assembly=str(planned["assembly_id"]))
    if (digest := _sha256(src)) != planned["contigs_sha256"]:
        raise JobFailure(f"The contigs file changed since it was registered (sha256 {digest}, recorded "
                         f"{planned['contigs_sha256']})", "contigs_changed", assembly=str(planned["assembly_id"]))
    ctx.log(f"Assembly {a.id}: {a.assembler} {a.assembler_version} ({a.kind.value}), contigs sha256 {digest}")
    return a


def _stage(ctx: JobContext, a: Assembly, results: Path, rename: bool) -> dict[str, Any]:
    (results / "input").mkdir(parents=True)
    staged = svc.stage_genome(ctx.path(a.contigs_path), results / "input" / INPUT_NAME, rename)
    ctx.log(f"Input: {len(staged['contigs'])} contigs, {staged['total_length']:,} bp ({staged['non_n_bases']:,} not N), "
            f"written as input/{INPUT_NAME} without FASTA descriptions" + (", contigs renamed contig_1 …" if rename else "")
            + f" (sha256 {staged['sha256']})")
    return staged


def _files(ctx: JobContext, out: Path, outputs: dict[str, str], prefix: str) -> dict[str, dict[str, Any]]:
    files = {}
    for kind, suffix in outputs.items():
        p = out / f"{prefix}.{suffix}"
        if p.is_file():
            files[kind] = {"path": _rel(ctx, p), "sha256": _sha256(p), "size_bytes": p.stat().st_size}
    return files


def _register(ctx: JobContext, a: Assembly, tool: str, steps: dict, summary: dict, sequences: list, files: dict,
              features_rel: str) -> Annotation:
    job = ctx.job
    params = {k: v for k, v in (job.parameters or {}).items() if k not in ("steps", "dependencies", "programs")}
    annotation = Annotation(sample_id=job.sample_id, assembly_id=a.id, job_id=job.id, tool=tool,
                            tool_version=job.tool_version, database_key=job.database_key,
                            database_name=job.database_name, database_version=job.database_version,
                            database_checksum=job.database_checksum, parameters=params, steps=steps, summary=summary,
                            sequences=sequences, files=files, features_path=features_rel)
    ctx.db.add(annotation)
    for step, s in steps.items():
        if s["status"] != "searched":
            ctx.log(f"Step {step}: {s['status']}" + (f" ({s['reason']})" if s.get("reason") else "")
                    + "".join(f"; {d['name']} {d['status']}" + (f" {d['found']}" if d.get("found") else "")
                              for d in s.get("dependencies") or []))
    return annotation


def _mapped(sequences: list[dict], staged: dict) -> list[dict]:
    """Each sequence with the assembly's contig name; the annotator's names are the staged names (or Bakta's own
    contig_N, whose originals Bakta reports)."""
    by_staged = {c["name"]: c["original_name"] for c in staged["contigs"]}
    return [{**s, "original_id": by_staged.get(s.get("original_id") or s["id"], s.get("original_id") or s["id"])}
            for s in sequences]


# --- Bakta ---------------------------------------------------------------------------------------------------

def _bakta_database(ctx: JobContext) -> tuple[ReferenceDatabase, str]:
    job = ctx.job
    record = ctx.db.get(ReferenceDatabase, job.reference_database_id) if job.reference_database_id else None
    if record is None or record.status not in (DatabaseStatus.installed, DatabaseStatus.registered):
        raise JobFailure(f"The database {job.database_name} {job.database_version} is no longer installed",
                         "database_missing", name=str(job.database_name), version=str(job.database_version))
    if (job.database_checksum and record.checksum != job.database_checksum) or record.version != job.database_version \
            or record.path != (job.database_path or record.path):
        raise JobFailure("The database's content checksum, version or folder changed since the run was confirmed (it "
                         "was verified or replaced); start the annotation again", "database_changed",
                         name=str(job.database_name))
    try:
        info = check_bakta_dir(Path(record.path))
    except DatabaseError as exc:
        raise JobFailure(f"Bakta could not use the database: {exc}") from exc
    source = record.version_source.value if record.version_source else "unknown"
    ctx.log(f"Database: {record.name} {record.version} ({info['type']}; version from {source}) at {record.path}, "
            f"content checksum {record.checksum or 'not computed (quick verification only)'} (last verified "
            f"{record.verified_at.isoformat() if record.verified_at else 'never'}, {record.verification_level or '?'})")
    return record, info["type"]


def _bakta_amr_data(ctx: JobContext, planned: dict | None) -> Path | None:
    """The AMRFinderPlus database the plan put in place of the Bakta database's own copy, checked unchanged."""
    replacement = (planned or {}).get("replacement") if (planned or {}).get("used") == "replacement" else None
    if replacement is None:
        return None
    r = ctx.db.get(ReferenceDatabase, replacement["id"])
    if r is None or r.status not in (DatabaseStatus.installed, DatabaseStatus.registered) or \
            r.checksum != replacement["checksum"] or r.path != replacement["path"]:
        raise JobFailure(f"The AMRFinderPlus database {replacement['name']} {replacement['version']} chosen for "
                         "Bakta's AMR expert system changed or was removed; open the annotation dialog again",
                         "database_changed", name=str(replacement["name"]))
    ctx.log(f"AMRFinderPlus data for Bakta's AMR expert system: {r.name} {r.version} at {r.path} (content checksum "
            f"{r.checksum}), because the copy inside the Bakta database "
            f"({((planned or {}).get('bundled') or {}).get('version') or '?'}) is not read by this AMRFinderPlus: "
            f"{((planned or {}).get('bundled') or {}).get('error') or ''}")
    return Path(r.path or "")


@dataclass
class _BaktaRun:
    """What the prepare step of a Bakta job decided, for the run and post-process steps."""
    exe: str
    params: BaktaParams
    assembly: Assembly
    steps: dict
    skips: list[str]
    dependencies: list[dict]
    results: Path
    staged: dict
    out: Path
    tmp: Path
    console: Path
    argv: list[str]
    native: dict | None = None


def _bakta_prepare(ctx: JobContext) -> _BaktaRun:
    """The database, assembly and programs checked again, the genome staged and the argument vector. For a native run
    (parameters.execution "mac_native") the Bakta is ARVA.app's on the Mac: its programs are checked there (ARVA.app
    refuses to run when the steps differ from the confirmed ones), the database is read from the Mac's folder, and
    the AMRFinderPlus view of the database is made on the Mac."""
    from app.services import native as native_service

    p = ctx.job.parameters or {}
    is_native = p.get("execution") == native_service.MAC_NATIVE
    if is_native:
        executor, facts = _native_executor(ctx, "bakta")
        exe = facts["executable"]
    else:
        exe = _resolve_tool(ctx, "bakta")
    params = BaktaParams(**{k: p[k] for k in BaktaParams.__dataclass_fields__})
    record, db_type = _bakta_database(ctx)
    a = _assembly(ctx)
    amr_data = _bakta_amr_data(ctx, p.get("amr_data"))
    if is_native:
        dependencies = list(p.get("dependencies") or [])
        steps = bakta_tool.plan_steps(dependencies, db_type, params.skip_plot)
        skips = bakta_tool.skip_options(steps)
        ctx.log("Dependencies: checked by ARVA.app on this Mac before Bakta starts (confirmed: "
                + ", ".join(f"{d['name']} {d['status']}" + (f" {d['found']}" if d.get("found") else "")
                            for d in dependencies) + ")")
    else:
        try:
            dependencies = bakta_tool.check_dependencies(exe, Path(record.path), amr_data)
        except RuntimeError as exc:
            raise JobFailure(str(exc)) from exc
        steps = bakta_tool.plan_steps(dependencies, db_type, params.skip_plot)
        skips = bakta_tool.skip_options(steps)
        for d in dependencies:
            ctx.log(f"Dependency {d['name']}: {d['status']}" + (f", version {d['found']}" if d["found"] else "")
                    + f" (Bakta needs {d['minimum']} or later)")
    if skips != p["skip_options"]:
        raise JobFailure(f"The programs Bakta needs changed since the run was confirmed: it would now skip "
                         f"{', '.join(skips) or 'nothing'} instead of {', '.join(p['skip_options']) or 'nothing'}. "
                         "Open the annotation dialog again", "programs_changed", tool="Bakta")
    results = ctx.path(ctx.results_rel)
    staged = _stage(ctx, a, results, rename=False)
    out, tmp = results / bakta_tool.OUT_DIR, results / bakta_tool.TMP_DIR
    tmp.mkdir()
    console = results / bakta_tool.CONSOLE_LOG
    native = None
    db_dir = Path(record.path)
    if amr_data is not None and not is_native:
        db_dir = bakta_tool.compose_database(Path(record.path), amr_data, tmp / "database")
        ctx.log(f"Bakta reads the database through {db_dir.relative_to(results)}: links to every file of "
                f"{record.path}, with amrfinderplus-db/latest -> {amr_data} (the copy inside the Bakta database is not "
                "read by this AMRFinderPlus); neither database is changed")
    try:
        if is_native:
            try:
                database = native_service.database_ref(record.path, executor)
                amr_ref = native_service.database_ref(str(amr_data), executor) if amr_data is not None else None
            except native_service.NativeError as exc:
                raise JobFailure(str(exc), exc.code, **{k: str(v) for k, v in exc.params.items()}) from None
            supported = frozenset(facts["help_options"])
            argv = bakta_tool.native_expected_argv(params, executor["data_dir"], exe, _rel(ctx, results / "input" /
                                                   INPUT_NAME), database, amr_ref, _rel(ctx, out), _rel(ctx, tmp),
                                                   skips, supported)
            native = {"record": executor, "facts": facts, "database": database, "amr_data": amr_ref,
                      "db_type": db_type, "provenance": native_service.provenance(executor, facts, "bakta")}
            if amr_data is not None:
                ctx.log(f"Bakta reads the database through {_rel(ctx, tmp)}/{bakta_tool.COMPOSED_DB}, made by ARVA.app "
                        f"on this Mac: links to every file of {database['root']}/{database['rel']}, with "
                        f"amrfinderplus-db/latest -> {amr_ref['root']}/{amr_ref['rel']}; neither database is changed")
        else:
            argv = BaktaAdapter.argv(exe, params, results / "input" / INPUT_NAME, db_dir, out, tmp, skips,
                                     BaktaAdapter.help_options(exe))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise JobFailure(f"Bakta's --help could not be read to check its options: {exc}",
                         "help_unreadable", tool="Bakta", detail=str(exc)) from exc
    except NativeRefusal as exc:
        raise JobFailure(f"Bakta cannot run on this Mac with these paths: {exc}", "bakta_native_refused",
                         reason=exc.code, detail=str(exc)) from exc
    except ValueError as exc:
        raise JobFailure(f"Bakta cannot run with these settings: {exc}",
                         "settings_rejected", tool="Bakta", detail=str(exc)) from exc
    return _BaktaRun(exe, params, a, steps, skips, dependencies, results, staged, out, tmp, console, argv, native)


def _bakta_failed(ctx: JobContext, run: _BaktaRun, exc: ToolExecutionError) -> None:
    """A Bakta run that stopped with an error: Bakta's own reason when its console says one (JobFailure, with
    bakta_out_of_memory when DIAMOND or Bakta was killed for memory), else the error."""
    if isinstance(exc, ToolTimeoutError):
        raise exc
    console_text = run.console.read_text(errors="replace") if run.console.is_file() else ""
    reason = BaktaAdapter.failure_reason(console_text, exc.returncode, native=run.native is not None)
    if reason is None:
        raise exc
    ctx.log("Bakta output (last lines):\n" + exc.stderr_tail.strip())
    if BaktaAdapter.out_of_memory(console_text + exc.stderr_tail, exc.returncode):
        raise JobFailure(reason, "bakta_out_of_memory_native" if run.native is not None else "bakta_out_of_memory"
                         ) from None
    raise JobFailure(reason) from None


def _bakta_run_docker(ctx: JobContext, run: _BaktaRun, monitor: _StageMonitor) -> None:
    try:
        _run(ctx, run.argv, run.results, run.console.name,
             extra_env={**bakta_tool.ENVIRONMENT, **bakta_tool.env_for(run.exe)}, monitor=monitor)
    except ToolExecutionError as exc:
        monitor(finished=True)
        _bakta_failed(ctx, run, exc)


def _bakta_run_native(ctx: JobContext, run: _BaktaRun, monitor: _StageMonitor) -> dict:
    """Publish Bakta's work record and wait for ARVA.app (app.tasks.tools._await_native); its report ends the run.
    Bakta has no checkpoint: a run stopped from outside fails and starts again from the beginning."""
    from app.services import native as native_service

    n = run.native
    work = {"tool": "bakta", "storage_id": n["record"]["storage_id"], "data_dir": n["record"]["data_dir"],
            "executable": n["facts"]["executable"], "params": run.params.as_dict(),
            "genome": _rel(ctx, run.results / "input" / INPUT_NAME), "out_dir": _rel(ctx, run.out),
            "tmp_dir": _rel(ctx, run.tmp), "results_dir": _rel(ctx, run.results), "console_log": run.console.name,
            "database": n["database"], "amr_data": n["amr_data"], "database_type": n["db_type"],
            "skip_options": run.skips, "argv": run.argv, "timeout_seconds": get_settings().tool_timeout_seconds}
    for key in ("genome", "out_dir", "tmp_dir", "results_dir"):
        native_relative(work[key])
        ctx.path(work[key])  # inside the data folder, or StoragePathError
    ctx.job.commands = [*(ctx.job.commands or []), run.argv]
    ctx.log("Command (to run on this Mac by ARVA.app, which checks Bakta's programs again, builds it with its own "
            "copy of the adapter and runs it only if identical): " + shlex.join(run.argv), flush=True)
    try:
        report, timed_out = _await_native(ctx, "Bakta", work, monitor, n["provenance"], lambda: None,
                                          "; start the annotation again", code_prefix="bakta_")
        monitor(finished=True)
        if report.get("missing_report"):
            raise native_timeout_error("bakta")
        outcome = report.get("outcome")
        ctx.log(f"ARVA.app reported: {outcome}" + (f", exit code {report['exit_code']}" if report.get("exit_code")
                                                   is not None else "")
                + (f" ({report.get('code')}: {report.get('detail')})" if report.get("code") else ""), flush=True)
        for d in report.get("dependencies") or []:
            ctx.log(f"Dependency on this Mac {d['name']}: {d['status']}" + (f", version {d['found']}" if d.get("found")
                                                                           else ""))
        if outcome in ("refused", "rejected", "not_started"):
            if ctx.cancel_requested():
                raise JobCancelled()
            raise JobFailure(f"ARVA.app did not run Bakta: {report.get('detail') or report.get('code')}",
                             "bakta_native_refused", reason=report.get("code") or outcome,
                             detail=report.get("detail") or "")
        if outcome == "stopped":
            if ctx.cancel_requested():
                raise JobCancelled()
            if timed_out:
                raise native_timeout_error("bakta")
            raise JobFailure("ARVA.app stopped Bakta before it finished (ARVA.app was closed); start the annotation "
                             "again", "bakta_native_stopped")
        code = report.get("exit_code")
        if code != 0:
            text = run.console.read_text(errors="replace") if run.console.is_file() else ""
            _bakta_failed(ctx, run, ToolExecutionError(f"bakta exited with status {code}", code, text[-4000:],
                                                       "tool_exit", {"tool": "bakta",
                                                                     "status": code if code is not None else "?"}))
        if report.get("dependencies"):
            run.dependencies = [{**d, "on_mac": True} for d in report["dependencies"]]
        ctx.log(f"bakta finished on this Mac in {report.get('duration_seconds') or 0:.1f}s")
        return report
    finally:
        native_service.withdraw(ctx.job.id)


def _bakta_body(ctx: JobContext) -> None:
    run = _bakta_prepare(ctx)
    monitor = _StageMonitor(ctx, "Bakta", run.console, bakta_tool.STAGES, BaktaAdapter.stage)
    monitor()
    report = None
    if run.native is not None:
        report = _bakta_run_native(ctx, run, monitor)
    else:
        _bakta_run_docker(ctx, run, monitor)
    monitor(finished=True)
    shutil.rmtree(run.tmp, ignore_errors=True)
    _bakta_postprocess(ctx, run, report)


def _bakta_postprocess(ctx: JobContext, run: _BaktaRun, report: dict | None) -> None:
    out, console = run.out, run.console
    parsed = BaktaAdapter.parse_console(console.read_text(errors="replace"))
    outputs = {k: out / f"{bakta_tool.PREFIX}.{s}" for k, s in bakta_tool.OUTPUTS.items()}
    if missing := [k for k in bakta_tool.REQUIRED_OUTPUTS if not outputs[k].is_file()]:
        raise JobFailure("Bakta exited without an error but did not write " + ", ".join(missing),
                         "outputs_missing", tool="Bakta", files=", ".join(missing))
    for warning in parsed["warnings"]:
        ctx.log(f"Bakta warning: {warning}")
    try:
        sequences, features, meta = BaktaAdapter.parse_json(json.loads(outputs["json"].read_text(errors="replace")))
    except (ValueError, KeyError, TypeError) as exc:
        raise JobFailure(f"Bakta's JSON cannot be read: {exc}",
                         "output_unreadable", tool="Bakta", detail=str(exc)) from exc
    if (meta.get("version") or {}).get("bakta") not in (None, ctx.job.tool_version):
        ctx.log(f"WARNING: Bakta's JSON says version {meta['version']['bakta']}; detected {ctx.job.tool_version}")
    sequences = _mapped(sequences, run.staged)
    outcome = svc.bakta_outcome(run.steps, parsed, outputs["plot_png"].is_file())
    _finish(ctx, run.assembly, "Bakta", outcome, features, sequences, run.staged, out, bakta_tool.OUTPUTS,
            bakta_tool.PREFIX,
            tool_reported={"stats": meta.get("stats"), "genome": meta.get("genome"), "version": meta.get("version"),
                           "found": parsed["found"]},
            programs=[{k: d.get(k) for k in ("name", "status", "found", "minimum", "on_mac") if k in d}
                      for d in run.dependencies],
            extra_outputs=[console])
    if run.native is not None and report is not None:
        ctx.job.result_summary = {**ctx.job.result_summary, "execution": "mac_native", "native": {
            **run.native["provenance"], "argv": report.get("argv"), "exit_code": report.get("exit_code"),
            "started_at": report.get("started_at"), "finished_at": report.get("finished_at"),
            "duration_seconds": report.get("duration_seconds"), "reported_outputs": report.get("outputs") or [],
            "database": run.native["database"], "amr_data": run.native["amr_data"]}}


def run_bakta_job(job_id: str) -> str:
    return run_job(job_id, _bakta_body)


# --- Prokka --------------------------------------------------------------------------------------------------

def _prokka_body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "prokka")
    p = ctx.job.parameters or {}
    params = ProkkaParams(**{k: p[k] for k in ProkkaParams.__dataclass_fields__})
    database = svc.prokka_database(exe)
    if not database["ready"]:
        raise JobFailure(f"Prokka's databases were not found in {database['path']}")
    if database["checksum"] != ctx.job.database_checksum:
        raise JobFailure("Prokka's database files changed since the run was confirmed (was the package updated?); "
                         "start the annotation again", "database_changed", name="Prokka")
    ctx.log(f"Database: {database['name']} {database['version'] or ''} at {database['path']}, checksum "
            f"{database['checksum']} ({len(database['files'])} files indexed for this run)")
    programs = prokka_tool.programs_found()
    if missing := prokka_tool.missing_programs(programs):
        raise JobFailure(f"Prokka needs {', '.join(missing)}, which is not installed")
    steps = prokka_tool.plan_steps(programs, database, params.rfam, params.use_genus, params.genus)
    if {s: v["run"] for s, v in steps.items()} != {s: v["run"] for s, v in p["steps"].items()}:
        raise JobFailure("The programs Prokka uses changed since the run was confirmed; open the annotation "
                         "dialog again", "programs_changed", tool="Prokka")
    a = _assembly(ctx)
    results = ctx.path(ctx.results_rel)
    staged = _stage(ctx, a, results, rename=params.rename_contigs)
    if not params.rename_contigs and (problem := prokka_tool.contig_name_problem([c["name"] for c in staged["contigs"]])):
        raise JobFailure(problem)
    db_dir = results / prokka_tool.DB_DIR
    prokka_tool.link_database(Path(database["path"]), db_dir, database["files"])
    try:
        _run(ctx, ProkkaAdapter.setupdb_argv(exe, db_dir), results, "prokka-setupdb.log")
        argv = ProkkaAdapter.argv(exe, params, results / "input" / INPUT_NAME, db_dir, results / prokka_tool.OUT_DIR,
                                  ProkkaAdapter.help_options(exe))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise JobFailure(f"Prokka's --help could not be read to check its options: {exc}",
                         "help_unreadable", tool="Prokka", detail=str(exc)) from exc
    except ValueError as exc:
        raise JobFailure(f"Prokka cannot run with these settings: {exc}",
                         "settings_rejected", tool="Prokka", detail=str(exc)) from exc
    console = results / prokka_tool.CONSOLE_LOG
    monitor = _StageMonitor(ctx, "Prokka", console, prokka_tool.STAGES, ProkkaAdapter.stage)
    monitor()
    try:
        _run(ctx, argv, results, console.name, monitor=monitor)
    except ToolExecutionError as exc:
        monitor(finished=True)
        if isinstance(exc, ToolTimeoutError):
            raise
        reason = ProkkaAdapter.failure_reason(console.read_text(errors="replace") if console.is_file() else "",
                                              exc.returncode)
        if reason is None:
            raise
        ctx.log("Prokka output (last lines):\n" + exc.stderr_tail.strip())
        raise JobFailure(reason) from None
    finally:
        shutil.rmtree(db_dir, ignore_errors=True)
    monitor(finished=True)
    ctx.log(f"Removed the indexed database copy ({prokka_tool.DB_DIR}/); its source files and checksum are recorded")

    out = results / prokka_tool.OUT_DIR
    outputs = {k: out / f"{prokka_tool.PREFIX}.{s}" for k, s in prokka_tool.OUTPUTS.items()}
    if missing := [k for k in prokka_tool.REQUIRED_OUTPUTS if not outputs[k].is_file()]:
        raise JobFailure("Prokka exited without an error but did not write " + ", ".join(missing),
                         "outputs_missing", tool="Prokka", files=", ".join(missing))
    log = ProkkaAdapter.parse_log(outputs["log"].read_text(errors="replace"))
    try:
        sequences, features = ProkkaAdapter.parse_gff(outputs["gff3"].read_text(errors="replace"))
    except ValueError as exc:
        raise JobFailure(f"Prokka's GFF3 cannot be read: {exc}",
                         "output_unreadable", tool="Prokka", detail=str(exc)) from exc
    ctx.log(f"Prokka ran Prodigal in {log['prodigal_mode']} mode (it uses 'meta' for genomes under 100,000 bp)")
    _finish(ctx, a, "Prokka", svc.prokka_outcome(steps, log), features, _mapped(sequences, staged), staged, out,
            prokka_tool.OUTPUTS, prokka_tool.PREFIX,
            tool_reported={"counts": log["counts"], "prodigal_mode": log["prodigal_mode"]},
            programs=[{"name": n, **v} for n, v in log["programs"].items()],
            extra_outputs=[console, results / "prokka-setupdb.log"])


def run_prokka_job(job_id: str) -> str:
    return run_job(job_id, _prokka_body)


# --- Shared ending -------------------------------------------------------------------------------------------

def _finish(ctx: JobContext, a: Assembly, tool: str, steps: dict, features: list, sequences: list, staged: dict,
            out: Path, outputs: dict[str, str], prefix: str, tool_reported: dict, programs: list,
            extra_outputs: list[Path]) -> None:
    results = ctx.path(ctx.results_rel)
    features_path = results / FEATURES_FILE
    write_jsonl(features_path, features)
    summary = {**summarize(features, sequences, staged["non_n_bases"], steps["cds"]["status"] == "searched"),
               "tool_reported": tool_reported, "input": {k: staged[k] for k in ("sha256", "non_n_bases",
                                                                                 "total_length", "renamed")},
               "synthetic_evidence": (ctx.job.parameters or {}).get("synthetic_evidence") or []}
    files = _files(ctx, out, outputs, prefix)
    files["input"] = {"path": _rel(ctx, results / "input" / INPUT_NAME), "sha256": staged["sha256"],
                      "size_bytes": (results / "input" / INPUT_NAME).stat().st_size}
    annotation = _register(ctx, a, tool, steps, summary, sequences, files, _rel(ctx, features_path))
    ctx.log(f"{tool}: {len(features):,} features ({', '.join(f'{n} {t}' for t, n in summary['counts'].items())})"
            + (f"; {summary['hypothetical']:,} of {summary['cds']:,} CDS hypothetical" if summary["cds"] else ""))
    ctx.db.flush()
    ctx.job.result_summary = {"annotation_id": annotation.id, "tool": tool, "counts": summary["counts"],
                              "steps": {s: v["status"] for s, v in steps.items()}, "programs": programs}
    ctx.job.output_paths = [f["path"] for f in files.values()] + [_rel(ctx, features_path)] + \
        [_rel(ctx, p) for p in extra_outputs if p.is_file()]
