"""Worker task: copy files from a configured server folder into a sample.

Each file goes through the same registration as a browser upload (streamed
SHA-256, read-only storage, quick validation, duplicate and mate detection).
Sources are only opened for reading; they are never modified or deleted.
"""
from __future__ import annotations

from app.services.capacity import InsufficientStorageError, fmt_bytes
from app.services.import_roots import (
    ImportPathError,
    ImportRoot,
    SourceChangedError,
    open_source,
    resolve_file,
    root_by_path,
)
from app.services.imports import DuplicateFileError, register_raw_file, rejection
from app.storage.local import FileTooLargeError
from app.tasks.common import JobCancelled, JobContext, JobFailure, run_job

_PER_FILE_ERRORS = (
    ImportPathError, SourceChangedError, DuplicateFileError, FileTooLargeError, InsufficientStorageError, OSError,
)
_REASONS_IN_ERROR = 5


class _ServerImport:
    def __init__(self) -> None:
        self.imported: list[dict] = []
        self.rejected: list[dict] = []
        self.duplicates = 0

    def summary(self) -> dict:
        # Always a new object: in-place changes to a JSON column are not detected by SQLAlchemy.
        return {"imported": list(self.imported), "rejected": list(self.rejected)}

    def body(self, ctx: JobContext) -> None:
        params = ctx.job.parameters or {}
        try:
            root = root_by_path(str(params.get("root", "")))
        except ImportPathError as exc:
            raise JobFailure(str(exc)) from exc
        paths = [str(p) for p in params.get("paths") or []]
        ctx.log(
            f"Copying {len(paths)} file(s) from {root.path} into sample {ctx.job.sample.sample_code}. "
            "Source files are only read; they are never modified or deleted.",
            flush=True,
        )
        for rel in paths:
            ctx.check_cancelled()
            self._copy(ctx, root, rel)
        ctx.job.result_summary = self.summary()
        if self.duplicates:
            ctx.log(f"{self.duplicates} file(s) were already registered in this sample and stay registered unchanged.")
        if not self.imported:
            reasons = "; ".join(f"{r['path']}: {r['reason']}" for r in self.rejected[:_REASONS_IN_ERROR])
            more = len(self.rejected) - _REASONS_IN_ERROR
            raise JobFailure(
                "No file was imported. " + reasons + (f" (and {more} more; see the log)" if more > 0 else "")
            )
        ctx.log(f"Imported {len(self.imported)} file(s); rejected {len(self.rejected)}.")

    def _copy(self, ctx: JobContext, root: ImportRoot, rel: str) -> None:
        try:
            src = resolve_file(root, rel)
            ctx.log(f"Copying {src.relative} ({fmt_bytes(src.size_bytes)})", flush=True)
            with open_source(root, src) as fh:
                raw = register_raw_file(
                    ctx.db, ctx.job.sample, src.name, fh,
                    expected_size=src.size_bytes,
                    description=f"Imported from server: {root.path}/{src.relative}",
                )
        except _PER_FILE_ERRORS as exc:
            reason = str(exc) if not isinstance(exc, OSError) else f"{exc.strerror or exc} while copying"
            code, params = rejection(exc) or (None, {})
            self.rejected.append({"path": rel, "reason": reason, "code": code, "params": params})
            if isinstance(exc, DuplicateFileError):
                self.duplicates += 1
                ctx.log(f"Rejected {rel}: {reason}; the registered file stays registered.", flush=True)
            else:
                ctx.log(f"Rejected {rel}: {reason}", flush=True)
            return
        self.imported.append(
            {"file_id": raw.id, "name": raw.original_filename, "path": src.relative, "size_bytes": raw.size_bytes}
        )
        mate = f", {raw.read_mate}" if raw.read_mate else ""
        ctx.log(
            f"Imported {src.relative} as file {raw.id} ({raw.size_bytes} bytes, sha256 {raw.checksum_sha256}, "
            f"{raw.file_format.value}{mate}). {raw.validation_message}",
            flush=True,
        )

    def on_failure(self, ctx: JobContext, exc: BaseException) -> None:
        ctx.job.result_summary = self.summary()
        if self.imported:
            when = "the cancellation" if isinstance(exc, JobCancelled) else "the failure"
            ctx.log(f"{len(self.imported)} file(s) imported before {when} stay registered in the sample.")


def run_server_import_job(job_id: str) -> str:
    task = _ServerImport()
    return run_job(job_id, task.body, task.on_failure)
