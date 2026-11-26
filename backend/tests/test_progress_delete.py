import asyncio
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app import main
from app.schemas import LyricsEdit
from app.services import jobs, library, progress, songs

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")


def _ago(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def test_eta_from_measured_fraction(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    job = jobs.create("song", {"duration_seconds": 60, "started_at": _ago(100)}, 0)
    jobs.update(job.id, status="running")
    progress.record(job.id, 0.5, "Generating music...")
    est = progress.estimate(jobs.get(job.id))
    assert est["pct"] == 50.0 and est["stage_label"] == "Композиране" and 60 <= est["eta_seconds"] <= 140


def test_eta_before_progress_uses_learned_pace(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    done = jobs.create("song", {"duration_seconds": 100}, 0)
    jobs.update(done.id, status="completed", result={"work_seconds": 400, "duration_seconds": 100})
    job = jobs.create("song", {"duration_seconds": 50, "started_at": _ago(10)}, 0)
    jobs.update(job.id, status="queued")
    est = progress.estimate(jobs.get(job.id))
    # 50 s of music at 4 s/s + 25 s mastering - 10 s elapsed
    assert 210 <= est["eta_seconds"] <= 220 and est["stage_label"] == "В опашката"
    assert progress.estimate(jobs.get(done.id)) is None


@needs_ffmpeg
def test_delete_song_removes_files_and_optional_library(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path / "data")
    job = jobs.create("song", {"title": "Изтрий ме"}, 0)
    jobs.update(job.id, status="completed", result={})
    folder = songs.song_dir(job.id)
    folder.mkdir(parents=True)
    subprocess.run([shutil.which("ffmpeg"), "-y", "-f", "lavfi", "-i", "sine=duration=1", str(folder / "master.mp3")], check=True, capture_output=True)
    lib = library.publish_song(job.id)
    assert lib.is_dir()
    asyncio.run(main.delete_job(job.id, library_copy=True))
    assert jobs.get(job.id) is None and not folder.exists() and not lib.exists()
    assert library.library_dir_for(job.id) is None


def test_running_job_cannot_be_deleted(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    job = jobs.create("song", {}, 0)
    jobs.update(job.id, status="running")
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.delete_job(job.id, library_copy=False))
    assert error.value.status_code == 409 and jobs.get(job.id)


def test_edit_lyrics_of_finished_song(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    job = jobs.create("song", {"title": "Т"}, 0)
    jobs.update(job.id, status="completed", result={"lyrics": "стар"})
    folder = songs.song_dir(job.id)
    folder.mkdir(parents=True)
    (folder / "lyric-timing.json").write_text(json.dumps([]), encoding="utf-8")
    data = asyncio.run(main.edit_song_lyrics(job.id, LyricsEdit(lyrics="[Verse]\nнов ред")))
    assert data["result"]["lyrics"] == "[Verse]\nнов ред" and data["result"]["lyrics_edited"]
    assert (folder / "lyrics.txt").read_text(encoding="utf-8") == "[Verse]\nнов ред\n"
    assert not (folder / "lyric-timing.json").exists()


def test_ace_step_scale_and_stage_labels():
    assert progress.ace_step_fraction(0.5) == 0.10 and abs(progress.ace_step_fraction(0.8) - 0.85) < 1e-9
    assert progress.ace_step_fraction(1.0) == 0.95
    assert progress.stage_label("Generating music (batch size: 1)...") == "Композиране"
    assert progress.stage_label("Decoding audio...") == "Декодиране на звука"
