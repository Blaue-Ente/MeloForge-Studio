"""Song package (``meloforge.song/1``) for downstream tools such as Atelier.

A package is a folder with ``song.json`` plus the delivery files. Paths inside
``files`` are relative to the folder. ``vocals.wav`` / ``instrumental.wav`` are
sample-aligned with ``master.wav`` (same start, same length) so lyric timing
measured on the vocal stem maps 1:1 onto the master.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.services import jobs
from app.services.mastering import probe_duration
from app.services.songs import song_dir

SCHEMA = "meloforge.song/1"


class PackageError(RuntimeError):
    pass


def _metadata(job) -> dict:
    metadata = dict((job.result or {}).get("metadata") or {})
    source_id = job.payload.get("source_song_id")
    if not metadata and source_id:
        source = jobs.get(source_id)
        if source:
            metadata = dict((source.result or {}).get("metadata") or {})
    return metadata


def ensure_stems(job_id: str) -> bool:
    """Create aligned stems next to the master if missing. Returns True when present."""
    folder = song_dir(job_id)
    if (folder / "vocals.wav").is_file() and (folder / "instrumental.wav").is_file():
        return True
    from app.services.voice_clone import export_stems

    export_stems(folder / "master.wav", folder)
    return (folder / "vocals.wav").is_file()


def build_manifest(job_id: str) -> dict:
    job = jobs.get(job_id)
    if not job or job.kind != "song" or job.status != "completed":
        raise PackageError("not_ready")
    folder = song_dir(job_id)
    master = folder / "master.wav"
    if not master.is_file():
        raise PackageError("no_master")
    payload, metadata = job.payload, _metadata(job)
    lyrics = ((job.result or {}).get("lyrics") or payload.get("lyrics") or "").strip()
    if lyrics == "[Instrumental]":
        lyrics = ""
    files = {"master": "master.wav"}
    for key, name in (("mp3", "master.mp3"), ("vocals", "vocals.wav"), ("instrumental", "instrumental.wav"), ("lyrics", "lyrics.txt")):
        if (folder / name).is_file():
            files[key] = name
    voice = (job.result or {}).get("voice")
    manifest = {
        "schema": SCHEMA,
        "song_id": job.id,
        "title": payload.get("title") or "",
        "artist": (voice or {}).get("name") or "MeloForge Studio",
        "genre": payload.get("genre") or "",
        "mood": payload.get("mood") or "",
        "prompt": metadata.get("prompt") or payload.get("prompt") or "",
        "language": payload.get("language") or "bg",
        "instrumental": bool(payload.get("instrumental")) or not lyrics,
        "bpm": metadata.get("bpm") or payload.get("bpm"),
        "timesignature": str(metadata.get("timesignature") or payload.get("time_signature") or "") or None,
        "keyscale": metadata.get("keyscale") or payload.get("key_scale") or None,
        "duration": round(probe_duration(master), 3),
        "lyrics": lyrics,
        "files": files,
    }
    if voice:
        manifest["voice"] = {"name": voice.get("name")}
    return manifest


def export_package(job_id: str, destination: Path | None = None, *, stems: bool = True) -> dict:
    """Write ``song.json`` (+ copies of the files when ``destination`` differs). Returns manifest + dir."""
    job = jobs.get(job_id)
    if not job or job.kind != "song" or job.status != "completed":
        raise PackageError("not_ready")
    stems_note = None
    if stems and not job.payload.get("instrumental"):
        try:
            ensure_stems(job_id)
        except Exception as exc:  # Stems are optional in the contract; Atelier can separate itself.
            stems_note = f"stems unavailable: {type(exc).__name__}"
    manifest = build_manifest(job_id)
    source = song_dir(job_id)
    target = Path(destination) if destination else source / "package"
    target.mkdir(parents=True, exist_ok=True)
    for name in manifest["files"].values():
        if (target / name).resolve() != (source / name).resolve():
            shutil.copyfile(source / name, target / name)
    (target / "song.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return {"song_dir": str(target.resolve()), "manifest": manifest, "stems_note": stems_note}
