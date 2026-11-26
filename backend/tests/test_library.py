import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import jobs, library, songs

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")


def _tone(path, seconds=2):
    subprocess.run([shutil.which("ffmpeg"), "-y", "-f", "lavfi", "-i", f"sine=duration={seconds}", str(path)], check=True, capture_output=True)


def _song(title):
    job = jobs.create("song", {"title": title, "genre": "folk"}, 0)
    jobs.update(job.id, status="completed", result={"mastering": {"after": {"integrated_lufs": -14.0, "duration_seconds": 2}}})
    folder = songs.song_dir(job.id)
    folder.mkdir(parents=True)
    _tone(folder / "master.mp3")
    _tone(folder / "master.wav")
    (folder / "lyrics.txt").write_text("ред\n", encoding="utf-8")
    return job


def test_safe_name_strips_windows_invalid_characters():
    assert library.safe_name('Песен: "нова"/версия?') == "Песен новаверсия"
    assert library.safe_name("  ...  ") == "Песен"


@needs_ffmpeg
def test_publish_uses_readable_names_and_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path / "data")
    job = _song("Кръчмата на Цеко")
    folder = library.publish_song(job.id)
    assert folder == Path(tmp_path / "library" / "Кръчмата на Цеко")
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["Кръчмата на Цеко - текст.txt", "Кръчмата на Цеко.mp3", "Кръчмата на Цеко.wav", "информация.txt"]
    assert "Жанр: folk" in (folder / "информация.txt").read_text(encoding="utf-8")
    assert library.publish_song(job.id) == folder  # same folder on repeat


@needs_ffmpeg
def test_same_title_gets_its_own_folder_and_clips_subfolder(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path / "data")
    first, second = _song("Песен"), _song("Песен")
    assert library.publish_song(first.id).name == "Песен"
    assert library.publish_song(second.id).name == "Песен (2)"
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0" * 10)
    clip = library.add_clip(first.id, video, "клип 16x9")
    assert clip == tmp_path / "library" / "Песен" / "Клипове" / "Песен - клип 16x9.mp4"
