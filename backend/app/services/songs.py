"""Finalise completed ACE-Step songs: keep a local copy and produce delivery masters."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.services import jobs
from app.services.composer import _download, _safe_asset_url
from app.services.mastering import master_track

SONG_FILES = {
    "mp3": ("master.mp3", "audio/mpeg"),
    "wav": ("master.wav", "audio/wav"),
    "raw": (None, None),
    "lyrics": ("lyrics.txt", "text/plain; charset=utf-8"),
    "report": ("mastering-report.json", "application/json"),
}


def song_dir(job_id: str) -> Path:
    return jobs.ROOT / "songs" / job_id


def raw_audio_path(job_id: str) -> Path | None:
    folder = song_dir(job_id)
    for candidate in sorted(folder.glob("raw.*")):
        return candidate
    return None


def song_file(job_id: str, kind: str) -> tuple[Path, str] | None:
    if kind not in SONG_FILES:
        return None
    if kind == "raw":
        raw = raw_audio_path(job_id)
        if not raw:
            return None
        media = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac"}.get(raw.suffix, "application/octet-stream")
        return raw, media
    name, media = SONG_FILES[kind]
    return song_dir(job_id) / name, media  # type: ignore[return-value]


def _raw_suffix(audio_url: str) -> str:
    parsed = urlparse(audio_url)
    # ACE-Step serves files as /v1/audio?path=<local file>; the extension lives in the query.
    candidate = (parse_qs(parsed.query).get("path") or [parsed.path])[0]
    suffix = Path(candidate).suffix.lower()
    return suffix if suffix in {".mp3", ".wav", ".flac"} else ".mp3"


def finalize_song(job_id: str, *, ace_step_base_url: str, ace_step_api_key: str) -> dict:
    """Download, master and describe a completed song. Runs in a worker thread."""
    job = jobs.get(job_id)
    if not job or job.kind != "song" or not job.result or not job.result.get("audio_url"):
        raise ValueError("Song job has no generated audio")
    audio_url = _safe_asset_url(job.result["audio_url"], ace_step_base_url, cloud_media=True)
    folder = song_dir(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / f"raw{_raw_suffix(audio_url)}"
    if not raw.is_file():
        needs_key = urlparse(audio_url).hostname == urlparse(ace_step_base_url).hostname
        partial = raw.with_suffix(raw.suffix + ".part")
        _download(audio_url, partial, api_key=ace_step_api_key if needs_key else "")
        partial.replace(raw)

    payload = job.payload
    lyrics = (job.result.get("lyrics") or payload.get("lyrics") or "").strip()
    if lyrics and lyrics != "[Instrumental]":
        (folder / "lyrics.txt").write_text(lyrics + "\n", encoding="utf-8", newline="\n")
    report = master_track(
        raw,
        folder,
        preset=payload.get("master_preset", "streaming"),
        title=payload.get("title", ""),
        genre=payload.get("genre", ""),
        lyrics="" if lyrics == "[Instrumental]" else lyrics,
    )
    (folder / "song.json").write_text(json.dumps({"job_id": job_id, "payload": payload, "metadata": job.result.get("metadata")}, ensure_ascii=False, indent=2), encoding="utf-8")
    files = {}
    for kind in SONG_FILES:
        found = song_file(job_id, kind)
        if found and found[0].is_file():
            files[kind] = f"/api/v1/songs/{job_id}/{kind}"
    return {
        **job.result,
        "files": files,
        "local_dir": str(folder),
        "mastering": report,
    }
