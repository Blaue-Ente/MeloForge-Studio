"""Finished-songs library: readable folders the user can publish from.

Internal song data lives under ``data/songs/<job id>`` (UUID names, hidden in
AppData). Every completed song is also copied to
``<Music>\\MeloForge\\<Title>\\`` with human names, e.g.::

    Кръчмата на Цеко\\Кръчмата на Цеко.mp3
    Кръчмата на Цеко\\Кръчмата на Цеко.wav
    Кръчмата на Цеко\\Кръчмата на Цеко - текст.txt
    Кръчмата на Цеко\\Кръчмата на Цеко - само вокал.wav
    Кръчмата на Цеко\\Клипове\\Кръчмата на Цеко - клип 16x9.mp4
    Кръчмата на Цеко\\информация.txt

The root is ``MELOFORGE_LIBRARY_DIR`` or the user's Music folder.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
from pathlib import Path

from app.services import jobs

_LOCK = threading.Lock()
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
SONG_FILES = (
    ("master.mp3", "{t}.mp3"),
    ("master.wav", "{t}.wav"),
    ("lyrics.txt", "{t} - текст.txt"),
    ("vocals.wav", "{t} - само вокал.wav"),
    ("instrumental.wav", "{t} - само музика.wav"),
)


def library_root() -> Path:
    configured = os.environ.get("MELOFORGE_LIBRARY_DIR", "").strip()
    return Path(configured) if configured else Path.home() / "Music" / "MeloForge"


def safe_name(title: str, fallback: str = "Песен") -> str:
    name = _INVALID.sub("", title or "").strip().rstrip(". ")
    return (name or fallback)[:90]


def _index_path() -> Path:
    return jobs.ROOT / "library.json"


def _index() -> dict:
    try:
        return json.loads(_index_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _folder_for(job_id: str, title: str) -> Path:
    """Stable folder per song; a second song with the same title gets ' (2)'."""
    index = _index()
    root = library_root()
    if job_id in index:
        return root / index[job_id]
    taken = set(index.values())
    base = safe_name(title)
    name, n = base, 2
    while name in taken or ((root / name).is_dir() and any((root / name).iterdir())):
        name, n = f"{base} ({n})", n + 1
    index[job_id] = name
    _index_path().parent.mkdir(parents=True, exist_ok=True)
    _index_path().write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return root / name


def _info_text(job, files: list[str]) -> str:
    payload, result = job.payload, job.result or {}
    meta = result.get("metadata") or {}
    mastering = (result.get("mastering") or {}).get("after") or {}
    lines = [
        f"Заглавие: {payload.get('title') or ''}",
        f"Изпълнител: {(result.get('voice') or {}).get('name') or 'MeloForge Studio'}",
        f"Жанр: {payload.get('genre') or ''}",
        f"Настроение: {payload.get('mood') or ''}",
        f"Темпо: {meta.get('bpm') or payload.get('bpm') or ''} BPM",
        f"Тоналност: {meta.get('keyscale') or payload.get('key_scale') or ''}",
        f"Дължина: {mastering.get('duration_seconds', '')} сек.",
        f"Сила: {mastering.get('integrated_lufs', '')} LUFS, връх {mastering.get('true_peak_dbtp', '')} dBTP",
        f"Създадена с: ACE-Step {payload.get('model') or ''} през MeloForge Studio",
        f"ID: {job.id}",
        "",
        "Файлове:",
        *[f"  {name}" for name in files],
        "",
        "Преди публикуване: провери условията на ACE-Step и платформата за AI музика.",
    ]
    return "\n".join(lines) + "\n"


def publish_song(job_id: str) -> Path | None:
    """Copy a completed song's deliverables into the library. Safe to call repeatedly."""
    from app.services.songs import song_dir

    job = jobs.get(job_id)
    if not job or job.kind != "song" or job.status != "completed":
        return None
    source = song_dir(job_id)
    if not (source / "master.mp3").is_file():
        return None
    with _LOCK:
        folder = _folder_for(job_id, job.payload.get("title") or job.payload.get("prompt", "")[:40])
        folder.mkdir(parents=True, exist_ok=True)
        title = folder.name
        copied = []
        for src_name, pattern in SONG_FILES:
            src = source / src_name
            if src.is_file():
                target = folder / pattern.format(t=title)
                if not target.is_file() or target.stat().st_size != src.stat().st_size:
                    shutil.copyfile(src, target)
                copied.append(target.name)
        (folder / "информация.txt").write_text(_info_text(job, copied), encoding="utf-8", newline="\n")
    return folder


def add_clip(song_job_id: str, video: Path, label: str) -> Path | None:
    """Copy a finished music video next to its song (``Клипове`` subfolder)."""
    folder = publish_song(song_job_id)
    if not folder or not video.is_file():
        return None
    clips = folder / "Клипове"
    clips.mkdir(exist_ok=True)
    target = clips / f"{folder.name} - {safe_name(label, 'клип')}{video.suffix}"
    shutil.copyfile(video, target)
    return target


def forget(job_id: str) -> None:
    with _LOCK:
        index = _index()
        if index.pop(job_id, None) is not None:
            _index_path().write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def library_dir_for(job_id: str) -> Path | None:
    name = _index().get(job_id)
    return library_root() / name if name else None


def open_in_explorer(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        import subprocess

        subprocess.Popen(["xdg-open" if sys.platform.startswith("linux") else "open", str(path)])
