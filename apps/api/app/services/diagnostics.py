"""The diagnostic report (GET /system/diagnostics): what someone helping with a problem needs to understand it
without access to this computer, built when asked for.

It holds ARVA's version and commit, the computer as detected (app.services.host), the performance profile, the
folders ARVA uses and whether each is there, the services, the tools, the databases (kind, version, status), the
migration state, the recent error log entries and, for one job or one error, its details. Every text passes
app.core.redaction; with `anonymise`, project, sample and file names become project-1, sample-3, file-2, numbered in
order of creation so that the same name has the same placeholder in every report. A section that cannot be read
says so instead of failing the report: it is most needed when something is broken.

It never holds sequences, reads, file contents, database contents, passwords, tokens, environment variables, the
user's e-mail or the Mac's serial number (which ARVA never reads), and is never sent anywhere: the user copies or
downloads it.
"""
from __future__ import annotations

import io
import json
import platform
import re
import shlex
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core import errorlog
from app.core.redaction import clip, redact_value, tail
from app.models import AnalysisJob, Project, RawFile, ReferenceDatabase, Sample
from app.services import locations, performance, startup
from app.services.capacity import fmt_bytes

MAX_ERRORS = 200
MAX_SINCE_HOURS = 24 * 365
JOB_LOG_LINES = 80
APP_LOG_EVENTS = 40
MAX_MARKDOWN = 4 * 1024**2
# Fields whose values are ARVA's own words (codes, statuses, ids), never a name: anonymisation leaves them alone.
STRUCTURAL = {"id", "time", "version", "commit", "component", "severity", "code", "status", "type", "role", "kind",
              "key", "rq_id", "correlation_id", "job_type", "event", "profile", "choice", "reason", "format"}

INCLUDED = ("ARVA's version, this computer's model and resources, the performance profile, ARVA's folders and "
            "whether they are there, the services, tools, databases (kind, version, status), the migration state "
            "and recent errors; for a job, its type, parameters, resources, timings, error and the end of its log.")
EXCLUDED = ("Never included: sequences, reads, file contents, database contents, passwords, tokens, environment "
            "variables, e-mail addresses or the Mac's serial number; the home folder is shown as ~. Nothing is sent "
            "anywhere: the report is copied or downloaded by the user.")


class NotFound(LookupError):
    def __init__(self, what: str, value: str):
        self.what, self.value = what, value
        super().__init__(f"No {what} {value} is known to ARVA")


@dataclass(frozen=True)
class Options:
    anonymise: bool = False
    include_logs: bool = True
    errors: int = 20
    since_hours: int = 168
    job_id: str | None = None
    error_id: str | None = None


class Anonymiser:
    """Project, sample and file names replaced by stable placeholders wherever they appear in a text."""

    def __init__(self, db: Session):
        self.mapping: dict[str, str] = {}
        self._add(db.scalars(select(Project.name).order_by(Project.created_at, Project.id)), "project")
        self._add(db.scalars(select(Sample.sample_code).order_by(Sample.created_at, Sample.id)), "sample")
        files: dict[str, str] = {}
        for original, stored in db.execute(select(RawFile.original_filename, RawFile.stored_path)
                                           .order_by(RawFile.uploaded_at, RawFile.id)):
            if not original:
                continue
            label = files.setdefault(original, f"file-{len(files) + 1}")
            self.mapping.setdefault(original, label)
            # Stored as <id>__<file name made safe>: that form gets the same placeholder.
            base = (stored or "").rsplit("/", 1)[-1]
            if "__" in base:
                self.mapping.setdefault(base.split("__", 1)[1], label)
        words = sorted((n for n in self.mapping if len(n) >= 2), key=len, reverse=True)
        self.pattern = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(map(re.escape, words)) + r")(?![A-Za-z0-9])") \
            if words else None

    def _add(self, names, label: str) -> None:
        numbered: dict[str, str] = {}
        for name in names:
            if name:
                self.mapping.setdefault(name, numbered.setdefault(name, f"{label}-{len(numbered) + 1}"))

    def text(self, value: str) -> str:
        return self.pattern.sub(lambda m: self.mapping[m.group()], value) if self.pattern else value

    def apply(self, value: Any, key: str | None = None) -> Any:
        if isinstance(value, str):
            return value if key in STRUCTURAL else self.text(value)
        if isinstance(value, dict):
            return {k: self.apply(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self.apply(v) for v in value]
        return value


def since_time(hours: int) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds").replace("+00:00", "Z")


def _section(db: Session, fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as exc:
        db.rollback()
        return {"unavailable": f"{type(exc).__name__}: {clip(str(exc), 300)}"}


def _platform() -> dict:
    det = performance.detection()
    return {"summary": performance.host_summary(det.host),
            "host": {k: v["value"] for k, v in det.host.as_dict().items()},
            "container": asdict(det.container), "notes": det.notes, "python": platform.python_version(),
            "os": f"{platform.system()} {platform.release()} {platform.machine()}"}


def _performance(db: Session) -> dict:
    o = performance.overview(db)
    return {"effective": o["effective"], "choice": o["choice"], "automatic": o["automatic"], "docker": o["docker"]}


def _storage(db: Session) -> dict:
    o = locations.overview(db)
    m, b = o["marker"], o["backups"]
    keys = ("role", "host_path", "container_path", "read_only", "available", "free_bytes", "total_bytes",
            "filesystem", "warnings", "databases")
    return {"marker": m.status, "in_container": o["in_container"], "log_folder_writable": errorlog.log_folder() is not None,
            "locations": [{k: loc[k] for k in keys} for loc in o["locations"]],
            "backups": {"count": b["count"], "latest": b["files"][0]["created_at"] if b["files"] else None,
                        "last_result": b["last_result"], "interval_hours": b["interval_hours"], "keep": b["keep"]}}


def _services(db: Session) -> dict:
    from rq import Worker
    from rq.registry import FailedJobRegistry, StartedJobRegistry

    from app.services import jobs as jobs_service

    out: dict[str, Any] = {"database": {"reachable": True, "server": db.execute(text("SHOW server_version")).scalar()},
                           "jobs": {s.value: n for s, n in db.execute(select(AnalysisJob.status, func.count())
                                                                       .group_by(AnalysisJob.status))}}
    try:
        q = jobs_service.get_queue()
        q.connection.ping()
        out["queue"] = {"reachable": True, "name": q.name, "queued": q.count,
                        "started": StartedJobRegistry(queue=q).count, "failed": FailedJobRegistry(queue=q).count,
                        "workers": Worker.count(connection=q.connection)}
    except Exception as exc:
        out["queue"] = {"reachable": False, "error": type(exc).__name__}
    return out


def _tools() -> list[dict]:
    from arva_tools.registry import detect_all

    return [{"id": t.info.id, "status": t.status.value, "version": t.version, "validated": t.version_validated,
             "reason": t.reason, "path": t.path} for t in detect_all()]


def _databases(db: Session) -> list[dict]:
    out = []
    for r in db.scalars(select(ReferenceDatabase).order_by(ReferenceDatabase.kind, ReferenceDatabase.key)):
        out.append({"kind": r.kind, "key": r.key, "version": r.version, "status": r.status.value,
                    "origin": r.origin.value, "verification": r.verification_level, "default": r.is_default,
                    "available": locations.folder_available(r.path) if r.path else None,
                    "error_code": (r.error_detail or {}).get("code")})
    return out


def _entry(e: dict, include_logs: bool) -> dict:
    out = dict(e)
    if not include_logs:
        out.pop("stderr_tail", None)
        if isinstance(out.get("exception"), dict):
            out["exception"] = {k: v for k, v in out["exception"].items() if k != "traceback"}
    return out


def _job(db: Session, job_id: str, opts: Options) -> dict:
    job = db.get(AnalysisJob, job_id)
    if job is None:
        raise NotFound("job", job_id)
    d = job.error_detail or {}
    files = [db.get(RawFile, i) for i in (job.input_raw_file_ids or [])[:50]]
    out: dict[str, Any] = {
        "id": job.id, "type": job.job_type, "status": job.status.value, "project_id": job.project_id,
        "sample_id": job.sample_id, "parent_job_id": job.parent_job_id, "correlation_id": job.correlation_id,
        "tool": {"name": job.tool_name, "version": job.tool_version, "path": job.tool_path},
        "database": {"key": job.database_key, "kind": job.database_kind, "version": job.database_version}
        if job.database_key or job.database_name else None,
        "parameters": job.parameters, "resources": job.resources,
        "inputs": [{"id": f.id, "name": f.original_filename, "format": f.file_format.value, "size_bytes": f.size_bytes}
                   for f in files if f is not None],
        "timings": {"created_at": job.created_at, "started_at": job.started_at, "finished_at": job.finished_at,
                    "duration_seconds": job.duration_seconds, "cancel_requested_at": job.cancel_requested_at},
        "error": {"code": d.get("code"), "params": d.get("params"), "message": clip(job.error_message, 4000)}
        if job.error_message or d else None,
        "progress": {k: v for k, v in (job.progress or {}).items() if isinstance(v, str | int | float | bool)},
        "commands": [clip(shlex.join(str(a) for a in argv), 2000) for argv in (job.commands or [])[:20]
                     if isinstance(argv, list)],
    }
    if opts.include_logs:
        out["log_tail"] = tail(job.log_text, JOB_LOG_LINES)
    cid = job.correlation_id
    out["related_errors"] = [_entry(e, opts.include_logs) for e in errorlog.read(limit=20, match=lambda e: (
        (e.get("job") or {}).get("id") == job.id or (cid is not None and e.get("correlation_id") == cid)))]
    return out


def build(db: Session, opts: Options) -> dict:
    """The report as data, redacted (and anonymised when asked); NotFound for an unknown job or error id."""
    since = since_time(opts.since_hours)
    report: dict[str, Any] = {"report": "ARVA diagnostic report", "generated_at": errorlog.now_text(),
                              **errorlog.build(), "options": asdict(opts), "included": INCLUDED, "excluded": EXCLUDED}
    job_id = opts.job_id
    if opts.error_id:
        found = errorlog.read(limit=1, match=lambda e: e.get("id") == opts.error_id)
        if not found:
            raise NotFound("error", opts.error_id)
        focus = _entry(found[0], True)
        cid = focus.get("correlation_id")
        focus["related"] = [_entry(e, opts.include_logs) for e in errorlog.read(limit=20, match=lambda e: (
            cid is not None and e.get("correlation_id") == cid and e.get("id") != opts.error_id))]
        report["error"] = focus
        linked = (focus.get("job") or {}).get("id")
        if job_id is None and isinstance(linked, str) and db.get(AnalysisJob, linked) is not None:
            job_id = linked
    if job_id:
        report["job"] = _job(db, job_id, opts)
    report["errors"] = [_entry(e, opts.include_logs) for e in errorlog.read(limit=opts.errors, since=since)]
    report["platform"] = _section(db, _platform)
    report["performance"] = _section(db, lambda: _performance(db))
    report["storage"] = _section(db, lambda: _storage(db))
    report["services"] = _section(db, lambda: _services(db))
    report["migrations"] = _section(db, lambda: startup.migration_state(db))
    report["tools"] = _section(db, _tools)
    report["databases"] = _section(db, lambda: _databases(db))
    report["configuration"] = _section(db, startup.summary)
    if opts.include_logs:
        report["app_log"] = errorlog.read(errorlog.APP, limit=APP_LOG_EVENTS, since=since)
    report = redact_value(json.loads(json.dumps(report, default=str)))
    if opts.anonymise:
        report = Anonymiser(db).apply(report)
    return report


# --- Markdown ---------------------------------------------------------------------------------------------------

def _cell(value: Any, key: str | None = None) -> str:
    if key and key.endswith("_bytes") and isinstance(value, int) and not isinstance(value, bool):
        return fmt_bytes(value)
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict | list):
        value = json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("`", "'")


def _table(rows: list[dict], columns: list[str]) -> list[str]:
    if not rows:
        return ["(none)"]
    return ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns),
            *("| " + " | ".join(_cell(r.get(c), c) for c in columns) + " |" for r in rows)]


def _pairs(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return [_cell(data)]
    if not data:
        return ["(none)"]
    if "unavailable" in data and len(data) == 1:
        return [f"Not available: {_cell(data['unavailable'])}"]
    return ["| | |", "|---|---|", *(f"| {_cell(k)} | {_cell(v, str(k))} |" for k, v in data.items())]


def _fence(content: str | list | None) -> list[str]:
    if not content:
        return []
    body = "\n".join(content) if isinstance(content, list) else content
    return ["```text", body.replace("```", "'''"), "```"]


def _entry_md(e: dict, level: str = "###") -> list[str]:
    out = [f"{level} {e.get('id', '?')} · {e.get('time', '?')} · {e.get('component', '?')} · {e.get('severity', '?')}",
           "", f"`{_cell(e.get('code'))}` {_cell(e.get('message'))}", ""]
    facts = []
    if r := e.get("request"):
        facts.append(f"- Request: {_cell(r.get('method'))} {_cell(r.get('route'))} → {_cell(r.get('status'))}")
    if j := e.get("job"):
        facts.append(f"- Job: {_cell(j.get('id'))} ({_cell(j.get('type'))}, {_cell(j.get('status'))})")
    if t := e.get("tool"):
        facts.append(f"- Tool: {_cell(t.get('name'))} {_cell(t.get('version'))}")
    if x := e.get("exception"):
        facts.append(f"- Exception: {_cell(x.get('type'))}: {_cell(x.get('message'))}")
        facts += [f"  - caused by {_cell(c.get('type'))}: {_cell(c.get('message'))}" for c in x.get("causes", [])]
    if e.get("correlation_id"):
        facts.append(f"- Correlation: {e['correlation_id']}")
    if e.get("params"):
        facts.append(f"- Parameters: {_cell(e['params'])}")
    if e.get("details"):
        facts.append(f"- Details: {_cell(e['details'])}")
    out += facts
    if (x := e.get("exception")) and x.get("traceback"):
        out += ["", "Traceback (ARVA's frames; library frames summarised):", *_fence(x["traceback"])]
    if e.get("stderr_tail"):
        out += ["", "Tool output (last lines):", *_fence(e["stderr_tail"])]
    return [*out, ""]


def markdown(r: dict) -> str:
    o = r["options"]
    scope = (f" · job {o['job_id']}" if o.get("job_id") else "") + (f" · error {o['error_id']}" if o.get("error_id") else "")
    out = ["# ARVA diagnostic report", "",
           f"Generated {r['generated_at']} · ARVA {r['version']} (commit {r['commit']}){scope}",
           f"Names anonymised: {_cell(o['anonymise'])} · logs included: {_cell(o['include_logs'])} · errors: the last "
           f"{o['errors']} within {o['since_hours']} hours", "", f"> {r['included']}", ">", f"> {r['excluded']}", ""]
    if e := r.get("error"):
        out += ["## The error", "", *_entry_md(e)]
        if e.get("related"):
            out += ["Related entries (same request or job):", ""] + [line for x in e["related"] for line in _entry_md(x, "####")]
    if j := r.get("job"):
        out += [f"## Job {j['id']}", "", *_pairs({k: j[k] for k in ("type", "status", "project_id", "sample_id",
                                                                    "parent_job_id", "correlation_id")}), ""]
        out += ["Tool and database:", "", *_pairs({"tool": j["tool"], "database": j["database"]}), ""]
        out += ["Error:", "", *_pairs(j["error"] or {"error": None}), ""]
        out += ["Timings:", "", *_pairs(j["timings"]), "", "Resources:", "", *_pairs(j["resources"] or {}), ""]
        out += ["Parameters:", "", *_fence(json.dumps(j["parameters"], indent=2, ensure_ascii=False)), ""]
        if j["inputs"]:
            out += ["Inputs:", "", *_table(j["inputs"], ["id", "name", "format", "size_bytes"]), ""]
        if j["progress"]:
            out += ["Progress:", "", *_pairs(j["progress"]), ""]
        if j["commands"]:
            out += ["Commands:", "", *_fence(j["commands"]), ""]
        if j.get("log_tail"):
            out += [f"Log (last {JOB_LOG_LINES} lines):", "", *_fence(j["log_tail"]), ""]
        if j["related_errors"]:
            out += ["Error log entries of this job:", ""] + [line for x in j["related_errors"] for line in _entry_md(x, "####")]
    shown = {x.get("id") for x in [r.get("error") or {}, *(r.get("error") or {}).get("related", []),
                                    *(r.get("job") or {}).get("related_errors", [])]}
    out += [f"## Recent errors ({len(r['errors'])})", ""]
    for e in r["errors"]:
        out += [f"- {e.get('id')} · {e.get('time')} · {e.get('component')} · `{_cell(e.get('code'))}` (shown above)",
                ""] if e.get("id") in shown else _entry_md(e)
    if not r["errors"]:
        out += ["(none)", ""]
    p = r["platform"]
    out += ["## Platform", ""]
    if isinstance(p, dict) and "summary" in p:
        out += [f"Computer: {_cell(p['summary'])} · {_cell(p['os'])} · Python {_cell(p['python'])}", "",
                *_pairs(p["host"]), "", "What ARVA's processes can use:", "", *_pairs(p["container"]), ""]
        out += [f"- {_cell(n)}" for n in p.get("notes") or []]
    else:
        out += _pairs(p)
    perf = r["performance"]
    out += ["", "## Performance profile", ""]
    if isinstance(perf, dict) and "effective" in perf:
        out += [*_pairs(perf["effective"]), "", "Docker Desktop:", "", *_pairs(perf["docker"]), ""]
    else:
        out += [*_pairs(perf), ""]
    st = r["storage"]
    out += ["## Storage", ""]
    if isinstance(st, dict) and "locations" in st:
        out += [f"Storage marker: {_cell(st['marker'])} · log folder writable: {_cell(st['log_folder_writable'])} · "
                f"in a container: {_cell(st['in_container'])}", "",
                *_table(st["locations"], ["role", "host_path", "container_path", "read_only", "available",
                                          "free_bytes", "total_bytes", "filesystem", "warnings", "databases"]),
                "", "Metadata backups:", "", *_pairs(st["backups"]), ""]
    else:
        out += [*_pairs(st), ""]
    out += ["## Services", "", *_pairs(r["services"]), "", "## Migrations", "", *_pairs(r["migrations"]), ""]
    out += ["## Tools", ""]
    out += _table(r["tools"], ["id", "status", "version", "validated", "reason", "path"]) \
        if isinstance(r["tools"], list) else _pairs(r["tools"])
    out += ["", "## Databases", ""]
    out += _table(r["databases"], ["kind", "key", "version", "status", "origin", "verification", "default",
                                   "available", "error_code"]) if isinstance(r["databases"], list) else _pairs(r["databases"])
    out += ["", "## Configuration", "", *_pairs(r["configuration"]), ""]
    if "app_log" in r:
        out += [f"## Application log (last {len(r['app_log'])} events)", ""]
        out += _fence([json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in reversed(r["app_log"])]) \
            or ["(none)"]
    text_out = "\n".join(out).rstrip() + "\n"
    return text_out if len(text_out) <= MAX_MARKDOWN else text_out[:MAX_MARKDOWN] + "\n\n(report cut at 4 MB)\n"


def archive(report: dict, md: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("arva-diagnostics.md", md)
        z.writestr("arva-diagnostics.json", json.dumps(report, indent=2, ensure_ascii=False))
    return buf.getvalue()
