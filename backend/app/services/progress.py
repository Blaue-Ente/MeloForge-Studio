"""Progress and remaining-time estimates for running jobs (shown as a progress bar).

ACE-Step reports a 0-1 progress and a stage for songs; voice conversion and
the visualizer report stages through the job itself. Remaining time comes from
the measured pace of the current job once it is under way, and before that
from the pace of earlier jobs on this machine (seconds of work per second of
music), with safe defaults for a 4 GB laptop GPU.
"""

from __future__ import annotations

from datetime import UTC, datetime
from statistics import median

from app.services import jobs

# Seconds of work per second of music when there is no history yet (RTX 2050, 4 GB).
DEFAULT_PACE = {"song": 3.0, "voice_swap": 7.0, "visualizer": 2.2}
MASTERING_SECONDS = 25
# Model loading and set-up that does not grow with song length.
FIXED_OVERHEAD = {"song": 45, "voice_swap": 90, "visualizer": 5}
STAGE_LABELS = {
    "queued": "В опашката",
    "Preparing inputs...": "Подготовка",
    "Generating music...": "Композиране",
    "Decoding audio...": "Декодиране на звука",
    "mastering": "Мастериране",
    "separation": "Отделяне на вокала",
    "conversion": "Преобразуване на гласа",
    "arrangement": "Подреждане на гласовете",
    "mixing": "Смесване и мастериране",
    "render": "Рендериране на клипа",
}


def stage_label(stage: str) -> str:
    for key, label in STAGE_LABELS.items():
        if stage == key or (key.endswith("...") and stage.startswith(key[:-3])):
            return label
    lowered = (stage or "").lower()
    if lowered.startswith("generating"):
        return "Композиране"
    if lowered.startswith("decoding"):
        return "Декодиране на звука"
    if lowered.startswith("prepar") or lowered.startswith("encod"):
        return "Подготовка"
    return stage or "Работи"


def ace_step_fraction(raw: float) -> float:
    """ACE-Step reports ~0.5 when diffusion starts and 0.8 when decoding starts; spread that evenly."""
    raw = max(0.0, min(1.0, raw))
    if raw < 0.5:
        return raw / 0.5 * 0.10
    if raw < 0.8:
        return 0.10 + (raw - 0.5) / 0.3 * 0.75
    return 0.85 + (raw - 0.8) / 0.2 * 0.10


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _seconds_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(iso)).total_seconds()
    except ValueError:
        return None


def job_type(job) -> str:
    if job.kind == "song":
        return "voice_swap" if job.payload.get("mode") == "voice_swap" else "song"
    if job.kind == "composition" and job.payload.get("mode") == "visualizer":
        return "visualizer"
    return job.kind


def learned_pace(kind: str) -> float:
    """Median seconds of work per second of music from finished jobs of this kind."""
    samples = []
    for job in jobs.list_recent(kind="song" if kind in {"song", "voice_swap"} else "composition", limit=40):
        if job.status != "completed" or job_type(job) != kind:
            continue
        work = (job.result or {}).get("work_seconds")
        length = (job.result or {}).get("duration_seconds") or job.payload.get("duration_seconds")
        if work and length:
            samples.append(max(0.5, (work - FIXED_OVERHEAD.get(kind, 0)) / float(length)))
    return median(samples) if samples else DEFAULT_PACE.get(kind, 3.0)


def expected_seconds(kind: str, length: float, voices: int = 1) -> float:
    pace = learned_pace(kind) * (voices if kind == "voice_swap" else 1)
    return FIXED_OVERHEAD.get(kind, 0) + length * pace + (MASTERING_SECONDS if kind != "visualizer" else 0)


def estimate(job) -> dict | None:
    """{pct, stage, stage_label, eta_seconds, elapsed_seconds} for queued/running jobs, else None."""
    if job.status not in {"queued", "running", "mastering"}:
        return None
    info = (job.result or {}).get("progress_info") or {}
    kind = job_type(job)
    started = job.payload.get("started_at") or job.created_at
    elapsed = _seconds_since(started) or 0.0
    length = float(job.payload.get("duration_seconds") or (job.result or {}).get("duration_seconds") or 120)
    voices = 2 if job.payload.get("voice_b_id") else 1
    expected = expected_seconds(kind, length, voices)
    fraction = float(info.get("fraction") or 0.0)
    if kind == "song" and job.status == "running":
        # ACE-Step's own progress moves in uneven jumps; use the learned pace for the bar and
        # its stage only to place the decoding phase near the end.
        time_fraction = min(0.85, elapsed / expected) if expected else 0.0
        fraction = max(time_fraction, 0.86) if stage_label(info.get("stage") or "") == "Декодиране на звука" else time_fraction
    stage = info.get("stage") or ("mastering" if job.status == "mastering" else "queued" if job.status == "queued" else "")
    if job.status == "mastering":
        fraction = max(fraction, 0.95)
    pace_eta = max(0.0, expected - elapsed)
    if kind == "song" and job.status == "running":
        eta = max(pace_eta, MASTERING_SECONDS if fraction >= 0.86 else 10.0)
    elif fraction >= 0.05:
        # Blend the measured pace with the learned one; trust the measurement more as the job advances.
        measured_eta = max(0.0, elapsed / fraction - elapsed)
        eta = fraction * measured_eta + (1 - fraction) * pace_eta
    else:
        eta = pace_eta
        fraction = max(fraction, min(0.9, elapsed / expected)) if expected else fraction
    if job.status == "mastering":
        eta = min(eta, MASTERING_SECONDS)
    return {
        "pct": round(min(99.0, fraction * 100), 1),
        "stage": stage,
        "stage_label": stage_label(stage),
        "eta_seconds": int(round(eta)),
        "elapsed_seconds": int(round(elapsed)),
    }


def record(job_id: str, fraction: float, stage: str) -> None:
    """Store progress reported by a worker (voice conversion, visualizer, ACE-Step poll)."""
    job = jobs.get(job_id)
    if not job:
        return
    result = dict(job.result or {})
    result["progress_info"] = {"fraction": max(0.0, min(1.0, fraction)), "stage": stage}
    jobs.update(job_id, result=result)


def finish_timing(job) -> float | None:
    """Seconds the job worked (for learning the pace), from its start mark to now."""
    return _seconds_since(job.payload.get("started_at") or job.created_at)
