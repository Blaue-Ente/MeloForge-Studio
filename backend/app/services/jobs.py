"""Local project/job ledger. Paid work cannot run before explicit confirmation."""

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(os.environ.get("MELOFORGE_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
# Job files are rewritten from request handlers and worker threads; serialise updates.
_LOCK = threading.RLock()


@dataclass
class Job:
    id: str
    kind: str
    status: str
    quote_usd: float
    payload: dict
    created_at: str
    provider_task_id: str | None = None
    result: dict | None = None
    error: str | None = None


def _path(job_id: str) -> Path:
    return ROOT / "jobs" / f"{job_id}.json"


def create(kind: str, payload: dict, quote_usd: float) -> Job:
    job = Job(str(uuid4()), kind, "awaiting_confirmation", quote_usd, payload, datetime.now(timezone.utc).isoformat())
    return save(job)


def get(job_id: str) -> Job | None:
    try:
        # Restrict path components to UUIDs; IDs are also accepted from browser URLs.
        normalized = str(UUID(job_id))
        data = json.loads(_path(normalized).read_text(encoding="utf-8"))
        data.setdefault("provider_task_id", None)
        data.setdefault("result", None)
        data.setdefault("error", None)
        return Job(**data)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def save(job: Job) -> Job:
    with _LOCK:
        target = _path(job.id)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f".{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(asdict(job), ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)
    return job


def update(
    job_id: str,
    *,
    status: str | None = None,
    provider_task_id: str | None = None,
    result: dict | None = None,
    payload: dict | None = None,
    error: str | None = None,
) -> Job | None:
    with _LOCK:
        job = get(job_id)
        if not job:
            return None
        if status is not None:
            job.status = status
        if provider_task_id is not None:
            job.provider_task_id = provider_task_id
        if result is not None:
            job.result = result
        if payload is not None:
            job.payload = payload
        if error is not None:
            job.error = error
        return save(job)


def delete(job_id: str) -> bool:
    with _LOCK:
        try:
            path = _path(str(UUID(job_id)))
        except ValueError:
            return False
        if path.is_file():
            path.unlink()
            return True
        return False


def confirm(job_id: str) -> Job | None:
    with _LOCK:
        job = get(job_id)
        if not job or job.status != "awaiting_confirmation":
            return None
        job.status = "queued"
        return save(job)


def list_recent(*, kind: str | None = None, limit: int = 20) -> list[Job]:
    folder = ROOT / "jobs"
    if not folder.is_dir():
        return []
    found: list[Job] = []
    for path in sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        job = get(path.stem)
        if job and (kind is None or job.kind == kind):
            found.append(job)
            if len(found) >= limit:
                break
    return found
