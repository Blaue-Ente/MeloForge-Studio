"""Local project/job ledger. Paid work cannot run before explicit confirmation."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import os
import json

ROOT = Path(os.environ.get("MELOFORGE_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))

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

def _path(job_id: str) -> Path: return ROOT / "jobs" / f"{job_id}.json"
def create(kind: str, payload: dict, quote_usd: float) -> Job:
    job = Job(str(uuid4()), kind, "awaiting_confirmation", quote_usd, payload, datetime.now(timezone.utc).isoformat())
    _path(job.id).parent.mkdir(parents=True, exist_ok=True)
    _path(job.id).write_text(json.dumps(asdict(job), ensure_ascii=False), encoding="utf-8")
    return job
def get(job_id: str) -> Job | None:
    try:
        # Restrict path components to UUIDs; IDs are also accepted from browser URLs.
        from uuid import UUID
        normalized = str(UUID(job_id))
        data = json.loads(_path(normalized).read_text(encoding="utf-8"))
        data.setdefault("provider_task_id", None)
        data.setdefault("result", None)
        data.setdefault("error", None)
        return Job(**data)
    except (OSError, json.JSONDecodeError, TypeError): return None
    except ValueError: return None

def save(job: Job) -> Job:
    target = _path(job.id)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(job), ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)
    return job

def update(job_id: str, *, status: str | None = None, provider_task_id: str | None = None, result: dict | None = None, payload: dict | None = None, error: str | None = None) -> Job | None:
    job = get(job_id)
    if not job: return None
    if status is not None: job.status = status
    if provider_task_id is not None: job.provider_task_id = provider_task_id
    if result is not None: job.result = result
    if payload is not None: job.payload = payload
    if error is not None: job.error = error
    return save(job)

def confirm(job_id: str) -> Job | None:
    job = get(job_id)
    if not job or job.status != "awaiting_confirmation": return None
    job.status = "queued"
    return save(job)
