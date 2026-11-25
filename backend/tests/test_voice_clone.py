import asyncio
import shutil
import subprocess
from uuid import UUID

import pytest
from fastapi import BackgroundTasks, HTTPException

from app import main
from app.schemas import VoiceSongRequest
from app.services import jobs, songs, voice_clone

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="FFmpeg required")


def _tone(path, seconds=8, freq=220):
    subprocess.run([shutil.which("ffmpeg"), "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
                    "-ac", "2", "-ar", "44100", str(path)], check=True, capture_output=True)


def test_consent_is_mandatory(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    with pytest.raises(voice_clone.VoiceCloneError, match="consent"):
        voice_clone.create_voice(name="x", data=b"RIFF", filename="a.wav", consent=False)
    assert voice_clone.list_voices() == []


def test_voice_ids_cannot_escape_the_data_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    with pytest.raises(voice_clone.VoiceCloneError):
        voice_clone.voice_dir("../../secrets")
    assert voice_clone.get_voice("..") is None


@needs_ffmpeg
def test_create_list_and_delete_voice(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    source = tmp_path / "me.wav"
    _tone(source, seconds=12)
    voice = voice_clone.create_voice(name="Ники", data=source.read_bytes(), filename="me.wav", consent=True)
    reference = voice_clone.voice_dir(voice["id"]) / "reference.wav"
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=channels,sample_rate", "-of", "csv=p=0",
                            str(reference)], capture_output=True, text=True, check=True)
    assert probe.stdout.strip() == "44100,1"
    assert voice["name"] == "Ники" and 5 <= voice["reference_seconds"] <= 25
    assert [item["id"] for item in voice_clone.list_voices()] == [voice["id"]]
    assert voice_clone.delete_voice(voice["id"]) and voice_clone.list_voices() == []


@needs_ffmpeg
def test_too_short_reference_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    source = tmp_path / "short.wav"
    _tone(source, seconds=2)
    with pytest.raises(voice_clone.VoiceCloneError, match="too_short"):
        voice_clone.create_voice(name="x", data=source.read_bytes(), filename="short.wav", consent=True)
    assert not any((tmp_path / "voices").iterdir())


@needs_ffmpeg
def test_voice_swap_endpoint_builds_a_mastered_song(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    monkeypatch.setattr(voice_clone, "engine_status", lambda: {"installed": True, "install_hint": None})

    def fake_separate(audio, workdir):
        workdir.mkdir(parents=True, exist_ok=True)
        vocals, inst = workdir / "vocals.wav", workdir / "no_vocals.wav"
        _tone(vocals, 10, 440)
        _tone(inst, 10, 110)
        return vocals, inst

    def fake_convert(vocals, reference, workdir, **_):
        out = workdir / "vc.wav"
        _tone(out, 10, 330)
        return out

    monkeypatch.setattr(voice_clone, "separate", fake_separate)
    monkeypatch.setattr(voice_clone, "convert_vocals", fake_convert)

    song = jobs.create("song", {"title": "Песен", "genre": "pop", "lyrics": "[Verse]\nред"}, 0)
    jobs.update(song.id, status="completed", result={"lyrics": "[Verse]\nред"})
    songs.song_dir(song.id).mkdir(parents=True)
    _tone(songs.song_dir(song.id) / "raw.wav", 10)
    reference = tmp_path / "me.wav"
    _tone(reference, 12)
    voice = voice_clone.create_voice(name="Ники", data=reference.read_bytes(), filename="me.wav", consent=True)

    tasks = BackgroundTasks()
    job = asyncio.run(main.create_voice_song(VoiceSongRequest(song_job_id=UUID(song.id), voice_id=voice["id"]), tasks))
    assert job.kind == "song" and job.status == "running" and job.payload["mode"] == "voice_swap"
    assert asyncio.run(main.get_job(job.id)).status == "running"  # not mistaken for an interrupted job
    task = tasks.tasks[0]
    task.func(*task.args, **task.kwargs)
    done = jobs.get(job.id)
    assert done.status == "completed", done.error
    assert {"mp3", "wav", "vocals", "instrumental", "lyrics"} <= set(done.result["files"])
    assert done.result["mastering"]["compliant"]
    assert asyncio.run(main.download_song(done.id, "vocals")).path.stat().st_size > 1000


def test_instrumental_songs_are_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    monkeypatch.setattr(voice_clone, "engine_status", lambda: {"installed": True, "install_hint": None})
    song = jobs.create("song", {"instrumental": True}, 0)
    jobs.update(song.id, status="completed", result={"lyrics": "[Instrumental]"})
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.create_voice_song(VoiceSongRequest(song_job_id=UUID(song.id), voice_id="0" * 32), BackgroundTasks()))
    assert error.value.status_code == 409
