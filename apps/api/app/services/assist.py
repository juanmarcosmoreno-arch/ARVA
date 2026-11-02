"""ARVA Assist: the integration point for an optional AI assistant. Nothing here talks to a network: ARVA bundles no
provider. A provider is code that implements `AssistProvider` and is registered with `register()` (a deployment adds
one; the tests register a fake). Assist is off until an administrator enables it in Settings with a provider, an
endpoint and, if needed, a key; ARVA works fully without it.

What is sent is built here and nowhere else (`build_payload`): the instructions, the question, ARVA Guide excerpts
the interface supplies, and a summary of the project's stored results (the full project report's data without
personal fields: no researcher, institution, notes or description). Sequences are never included unless the request
says the user consented for that request. Every request is logged with exactly what was sent (`assist_requests`).

The key is kept in <storage>/secrets/assist-key (owner-only file, outside the database, so metadata backups and
diagnostics do not contain it) and is never returned by the API."""
from __future__ import annotations

import hashlib
import ipaddress
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import utcnow
from app.models import Annotation, AppSetting, AssistRequest, Project, Sample, User
from app.services import auth, project_report

SETTING_KEY = "assist"
KEY_FILE = "assist-key"
MAX_QUESTION = 4000
MAX_GUIDE_ITEMS = 8
MAX_GUIDE_CHARS = 6000
MAX_SEQUENCE = 20000
INSTRUCTIONS = (
    "You are ARVA Assist, inside a bacterial genomics platform. Answer only from the ARVA data and ARVA Guide "
    "excerpts given in the context. If they do not contain the answer, say so. Label every statement as "
    "Observed (a value in the data), Interpretation, or Hypothesis. Never invent results, values, genes, "
    "references or tool options. Correlation is not causation; similarity does not establish horizontal transfer. "
    "Do not tell the user to run destructive commands. Analyses are changed only by the user in ARVA."
)
PERSONAL_FIELDS = ("researcher", "institution", "notes", "description")


class AssistError(Exception):
    def __init__(self, code: str, status: int = 400, **params: Any):
        super().__init__(code)
        self.code, self.status, self.params = code, status, params


MESSAGES = {
    "assist_disabled": "ARVA Assist is off. An administrator can enable it in Settings.",
    "assist_no_provider": "No ARVA Assist provider named {provider} is installed in this ARVA.",
    "assist_endpoint_invalid": "The endpoint must be an https:// address, or http:// on this computer (127.0.0.1, "
                               "localhost or ::1).",
    "assist_sequence_consent": "Sequences are sent only when you tick the consent for this request.",
    "assist_question_invalid": "Write a question of 1 to {maximum} characters.",
    "assist_provider_failed": "The provider did not answer ({reason}).",
    "assist_not_found": "No such item to include.",
}


def message(exc: AssistError) -> str:
    return MESSAGES[exc.code].format(**exc.params)


@dataclass(frozen=True)
class ProviderConfig:
    endpoint: str | None
    model: str | None
    api_key: str | None


class AssistProvider(Protocol):
    def ask(self, payload: dict[str, Any], config: ProviderConfig) -> str: ...


PROVIDERS: dict[str, Callable[[], AssistProvider]] = {}


def register(name: str, factory: Callable[[], AssistProvider]) -> None:
    PROVIDERS[name] = factory


def unregister(name: str) -> None:
    PROVIDERS.pop(name, None)


# --- Settings -------------------------------------------------------------------------------------------------------

def _key_path():
    return get_settings().secrets_dir / KEY_FILE


def _stored(db: Session) -> dict[str, Any]:
    row = db.get(AppSetting, SETTING_KEY)
    return dict(row.value) if row else {"enabled": False, "provider": None, "endpoint": None, "model": None}


def endpoint_is_local(endpoint: str | None) -> bool:
    if not endpoint:
        return False
    host = (urlsplit(endpoint).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_endpoint(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    parts = urlsplit(endpoint.strip())
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
        raise AssistError("assist_endpoint_invalid")
    if parts.scheme == "http" and not endpoint_is_local(endpoint):
        raise AssistError("assist_endpoint_invalid")
    return endpoint.strip()


def settings_view(db: Session) -> dict[str, Any]:
    s = _stored(db)
    return {**s, "key_set": _key_path().is_file(), "endpoint_is_local": endpoint_is_local(s.get("endpoint")),
            "providers": sorted(PROVIDERS), "instructions": INSTRUCTIONS}


def save_settings(db: Session, enabled: bool, provider: str | None, endpoint: str | None, model: str | None,
                  api_key: str | None, clear_key: bool) -> dict[str, Any]:
    value = {"enabled": bool(enabled), "provider": provider or None, "endpoint": check_endpoint(endpoint),
             "model": (model or "").strip()[:128] or None}
    if value["enabled"] and value["provider"] not in PROVIDERS:
        raise AssistError("assist_no_provider", provider=value["provider"] or "")
    row = db.get(AppSetting, SETTING_KEY)
    if row is None:
        db.add(AppSetting(key=SETTING_KEY, value=value))
    else:
        row.value = value
    db.flush()
    if clear_key:
        _key_path().unlink(missing_ok=True)
    elif api_key:
        auth.ensure_secrets_dir()
        auth.write_private(_key_path(), api_key.strip())
    return settings_view(db)


def status(db: Session) -> dict[str, Any]:
    s = _stored(db)
    return {"enabled": bool(s.get("enabled")) and s.get("provider") in PROVIDERS, "provider": s.get("provider"),
            "endpoint_is_local": endpoint_is_local(s.get("endpoint"))}


# --- Context --------------------------------------------------------------------------------------------------------

def _project_context(db: Session, project: Project, sample_id: str | None) -> dict[str, Any]:
    data = project_report.collect(db, project)
    data["project"] = {k: v for k, v in data["project"].items() if k not in PERSONAL_FIELDS}
    samples = data["samples"]
    if sample_id:
        samples = [s for s in samples if s["id"] == sample_id]
    for s in samples:
        s.pop("id", None)
        s.pop("expected_species", None)
    return {"source": "ARVA stored results (latest completed result per analysis and sample)",
            "project": data["project"], "samples": samples,
            "comparisons": [{k: v for k, v in c.items() if k != "id"} for c in data["comparisons"]],
            "tools": [{k: m[k] for k in ("tool", "versions", "databases", "used_for")} for m in data["methods"]],
            "not_searched_means": "the analysis was not run on that sample; it is not a negative result"}


def _sequences(db: Session, refs: list[dict[str, str]], visible: Callable[[str], bool]) -> list[dict[str, Any]]:
    from app.services.annotation import feature_detail

    out = []
    for ref in refs[:5]:
        ann = db.get(Annotation, ref.get("annotation_id", ""))
        sample = db.get(Sample, ann.sample_id) if ann else None
        if ann is None or sample is None or not visible(sample.project_id):
            raise AssistError("assist_not_found", 404)
        try:
            f = feature_detail(ann, int(ref.get("feature_id", "")))
        except (LookupError, ValueError, FileNotFoundError):
            raise AssistError("assist_not_found", 404) from None
        seq = (f.get("protein") or {}).get("sequence") or (f.get("nucleotide") or {}).get("sequence") or ""
        out.append({"annotation_id": ann.id, "feature": f.get("locus_tag") or f.get("id"),
                    "product": f.get("product"), "sequence": seq[:MAX_SEQUENCE]})
    return out


def build_payload(db: Session, question: str, project: Project | None, sample_id: str | None,
                  guide: list[dict[str, str]], sequence_refs: list[dict[str, str]], sequence_consent: bool,
                  visible: Callable[[str], bool]) -> dict[str, Any]:
    question = question.strip()
    if not 1 <= len(question) <= MAX_QUESTION:
        raise AssistError("assist_question_invalid", maximum=MAX_QUESTION)
    if sequence_refs and not sequence_consent:
        raise AssistError("assist_sequence_consent")
    excerpts, used = [], 0
    for g in guide[:MAX_GUIDE_ITEMS]:
        text = str(g.get("text", ""))[:MAX_GUIDE_CHARS - used]
        used += len(text)
        if text:
            excerpts.append({"id": str(g.get("id", ""))[:100], "title": str(g.get("title", ""))[:200], "text": text})
    payload: dict[str, Any] = {"instructions": INSTRUCTIONS, "question": question, "guide": excerpts,
                               "data": _project_context(db, project, sample_id) if project else None,
                               "sequences": []}
    if sequence_refs:
        payload["sequences"] = _sequences(db, sequence_refs, visible)
    return payload


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def ask(db: Session, user: User | None, payload: dict[str, Any], project_id: str | None) -> dict[str, Any]:
    s = _stored(db)
    if not s.get("enabled"):
        raise AssistError("assist_disabled", 409)
    factory = PROVIDERS.get(s.get("provider") or "")
    if factory is None:
        raise AssistError("assist_no_provider", 409, provider=s.get("provider") or "")
    key_path = _key_path()
    config = ProviderConfig(endpoint=s.get("endpoint"), model=s.get("model"),
                            api_key=key_path.read_text().strip() if key_path.is_file() else None)
    text = _canonical(payload)
    record = AssistRequest(at=utcnow(), user_id=user.id if user else None, username=user.username if user else None,
                           provider=s["provider"], endpoint_host=urlsplit(s.get("endpoint") or "").hostname,
                           model=s.get("model"), project_id=project_id, question=payload["question"],
                           sent=json.loads(text), sent_sha256=hashlib.sha256(text.encode()).hexdigest(),
                           included_sequences=bool(payload["sequences"]), status="sent")
    try:
        answer = factory().ask(payload, config)
        record.status, record.answer = "answered", str(answer)[:100_000]
    except Exception as exc:
        record.status, record.error_code = "failed", type(exc).__name__[:64]
    db.add(record)
    db.commit()
    if record.status == "failed":
        raise AssistError("assist_provider_failed", 502, reason=record.error_code)
    return {"request_id": record.id, "answer": record.answer, "sent_sha256": record.sent_sha256,
            "included_sequences": record.included_sequences}


def audit_rows(db: Session, limit: int) -> list[dict[str, Any]]:
    return [{"id": r.id, "at": r.at, "username": r.username, "provider": r.provider, "endpoint_host": r.endpoint_host,
             "model": r.model, "project_id": r.project_id, "question": r.question, "sent": r.sent,
             "sent_sha256": r.sent_sha256, "included_sequences": r.included_sequences, "status": r.status,
             "answer": r.answer, "error_code": r.error_code}
            for r in db.scalars(select(AssistRequest).order_by(AssistRequest.at.desc()).limit(limit))]
