import asyncio
import json
import shutil
import subprocess
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException

from app import main
from app.schemas import AtelierVideoRequest, RuntimeSettingsUpdate
from app.services import atelier, jobs, song_package, songs, voice_clone

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="FFmpeg required")


def _tone(path, seconds=6, freq=220):
    subprocess.run([shutil.which("ffmpeg"), "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
                    "-ac", "2", "-ar", "44100", str(path)], check=True, capture_output=True)


def _song(tmp_path, *, stems=False):
    song = jobs.create("song", {"title": "Кръчма", "genre": "folk", "language": "bg", "prompt": "p", "lyrics": "[Verse]\nред"}, 0)
    jobs.update(song.id, status="completed", result={"lyrics": "[Verse]\nред", "metadata": {"bpm": 96, "keyscale": "D minor", "timesignature": "4", "prompt": "tavern folk"}})
    folder = songs.song_dir(song.id)
    folder.mkdir(parents=True)
    _tone(folder / "master.wav")
    _tone(folder / "master.mp3")
    (folder / "lyrics.txt").write_text("[Verse]\nред\n", encoding="utf-8")
    if stems:
        _tone(folder / "vocals.wav", 6, 440)
        _tone(folder / "instrumental.wav", 6, 110)
    return song


@needs_ffmpeg
def test_package_manifest_follows_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    song = _song(tmp_path, stems=True)
    out = song_package.export_package(song.id)
    manifest = json.loads((tmp_path / "songs" / song.id / "package" / "song.json").read_text(encoding="utf-8"))
    assert manifest == out["manifest"]
    assert manifest["schema"] == "meloforge.song/1" and manifest["bpm"] == 96 and manifest["keyscale"] == "D minor"
    assert manifest["prompt"] == "tavern folk" and abs(manifest["duration"] - 6.0) < 0.1
    assert manifest["files"] == {"master": "master.wav", "mp3": "master.mp3", "vocals": "vocals.wav", "instrumental": "instrumental.wav", "lyrics": "lyrics.txt"}
    for name in manifest["files"].values():
        assert (tmp_path / "songs" / song.id / "package" / name).is_file()  # relative to song_dir


@needs_ffmpeg
def test_package_without_engine_still_exports_master(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    monkeypatch.setattr(voice_clone, "engine_status", lambda: {"installed": False})
    song = _song(tmp_path)
    out = song_package.export_package(song.id)
    assert "vocals" not in out["manifest"]["files"] and out["stems_note"]


@needs_ffmpeg
def test_stems_are_aligned_to_master(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    source = tmp_path / "short.wav"
    _tone(source, 5.2)
    voice_clone.align_stem(source, tmp_path / "aligned.wav", length_seconds=6.0)
    assert abs(float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(tmp_path / "aligned.wav")],
                              capture_output=True, text=True, check=True).stdout) - 6.0) < 0.01


def test_atelier_url_must_be_loopback():
    with pytest.raises(atelier.AtelierError):
        atelier._base("http://example.com:8765")
    assert atelier._base("http://127.0.0.1:8765/") == "http://127.0.0.1:8765"
    with pytest.raises(ValueError):
        RuntimeSettingsUpdate(atelier_base_url="http://10.0.0.5:8765")


@needs_ffmpeg
def test_atelier_request_sends_package_path(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    song = _song(tmp_path, stems=True)
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"project": "p1", "status": "needs_confirm", "estimate": {"amount_usd": 0.4}})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    result = asyncio.run(main.atelier_music_video(AtelierVideoRequest(song_job_id=UUID(song.id), mode="stills", local_only=True)))
    assert seen["url"].endswith("/api/musicvideo") and seen["body"]["mode"] == "stills" and seen["body"]["local_only"] is True
    assert json.loads((tmp_path / "songs" / song.id / "package" / "song.json").read_text(encoding="utf-8"))
    assert seen["body"]["song_dir"] == result["package"]["song_dir"] and result["status"] == "needs_confirm"


def test_atelier_offline_is_a_clear_503(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused")

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.atelier_project("p1"))
    assert error.value.status_code == 503
