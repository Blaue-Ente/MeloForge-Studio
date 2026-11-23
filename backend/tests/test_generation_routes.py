import asyncio
from uuid import UUID

import pytest
from fastapi import BackgroundTasks, HTTPException

from app import main
from app.schemas import VideoRequest
from app.services import jobs


def test_video_quote_does_not_send_paid_request_before_confirmation(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    monkeypatch.setattr(main.settings, "novita_api_key", "local-test-key")
    monkeypatch.setattr(main.settings, "novita_video_max_seconds", 8)
    monkeypatch.setattr(main.settings, "novita_video_cost_per_second_usd", 0.1)
    calls = []

    async def submit_video(_settings, payload):
        calls.append(payload)
        return {"task_id": "video-task-1"}

    monkeypatch.setattr(main, "novita_create_video", submit_video)
    quote = asyncio.run(main.create_video_quote(VideoRequest(prompt="night city", duration=5)))
    assert quote["status"] == "awaiting_confirmation"
    assert calls == []

    confirmed = asyncio.run(main.confirm_job(quote["id"]))
    assert confirmed.status == "running"
    assert confirmed.provider_task_id == "video-task-1"
    assert len(calls) == 1


def test_song_quote_waits_for_confirmation_then_submits_to_ace_step(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    monkeypatch.setattr(main.settings, "ace_step_enabled", True)
    monkeypatch.setattr(main.settings, "ace_step_base_url", "http://127.0.0.1:8001")
    monkeypatch.setattr(main.settings, "ace_step_model", "acestep-v15-turbo")
    calls = []

    async def models(_config):
        return {"data": {"default_model": "acestep-v15-turbo", "models": [{"name": "acestep-v15-turbo"}]}}

    async def submit_song(_config, payload):
        calls.append(payload)
        return {"task_id": "song-task-1"}

    monkeypatch.setattr(main, "ace_step_models", models)
    monkeypatch.setattr(main, "ace_step_submit_song", submit_song)
    from app.schemas import SongRequest

    quote = asyncio.run(main.create_song_quote(SongRequest(prompt="neon city pop", duration_seconds=30, language="bg")))
    assert quote["status"] == "awaiting_confirmation"
    assert quote["quote_usd"] == 0
    assert calls == []

    confirmed = asyncio.run(main.confirm_job(quote["id"]))
    assert confirmed.status == "running"
    assert confirmed.provider_task_id == "song-task-1"
    assert calls[0]["sample_mode"] is True
    assert calls[0]["vocal_language"] == "bg"


def test_song_quote_accepts_ace_step_15_openai_model_list(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    monkeypatch.setattr(main.settings, "ace_step_enabled", True)
    monkeypatch.setattr(main.settings, "ace_step_base_url", "http://127.0.0.1:8001")
    monkeypatch.setattr(main.settings, "ace_step_model", "acestep-v15-turbo")

    async def models(_config):
        return {"object": "list", "data": [{"id": "acestep/acestep-v15-turbo", "name": "ACE-Step acestep-v15-turbo"}]}

    monkeypatch.setattr(main, "ace_step_models", models)
    from app.schemas import SongRequest

    quote = asyncio.run(main.create_song_quote(SongRequest(
        prompt="warm Bulgarian folk pop",
        duration_seconds=10,
        language="bg",
        lyrics="Светлина по пътя, песен за дома.",
    )))

    assert quote["status"] == "awaiting_confirmation"
    assert quote["quote_usd"] == 0
    assert quote["payload"]["_ace_step_model"] == "acestep-v15-turbo"


@pytest.mark.parametrize(
    "models_payload",
    [
        {"data": [{"id": "acestep/acestep-v15-turbo", "name": "ACE-Step acestep-v15-turbo"}]},
        {"data": {"default_model": "acestep-v15-turbo", "models": [{"name": "acestep-v15-turbo"}]}},
    ],
)
def test_music_readiness_accepts_current_and_legacy_model_shapes(monkeypatch, models_payload):
    monkeypatch.setattr(main.settings, "ace_step_enabled", True)
    monkeypatch.setattr(main.settings, "ace_step_base_url", "http://127.0.0.1:8001")
    monkeypatch.setattr(main.settings, "ace_step_model", "acestep-v15-turbo")

    async def models(_config):
        return models_payload

    monkeypatch.setattr(main, "ace_step_models", models)
    readiness = asyncio.run(main.music_readiness())

    assert readiness["ready"] is True
    assert readiness["model"] == "acestep-v15-turbo"
    assert readiness["models"] == ["acestep-v15-turbo"]


def test_legacy_video_endpoint_cannot_bypass_confirmation(monkeypatch):
    calls = []

    async def submit_video(*_args):
        calls.append(True)
        return {"task_id": "must-not-run"}

    monkeypatch.setattr(main, "novita_create_video", submit_video)
    with pytest.raises(HTTPException) as response:
        asyncio.run(main.create_wan22_video(VideoRequest(prompt="night city")))
    assert response.value.status_code == 410
    assert calls == []


def test_full_song_video_assembly_and_download_routes(monkeypatch, tmp_path):
    from app.services.composer import lyrics_path, output_path

    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    monkeypatch.setattr(main.shutil, "which", lambda _name: "ffmpeg.exe")
    song = jobs.create("song", {"title": "Test", "duration_seconds": 10, "lyrics": "Test lyric"}, 0)
    jobs.update(song.id, status="completed", result={"audio_url": "http://127.0.0.1:8001/song.mp3", "lyrics": "Test lyric"})
    video = jobs.create("video", {"prompt": "Test scene", "duration": 5, "size": "1280*720"}, 0)
    jobs.update(video.id, status="completed", result={"video_urls": ["https://cdn.novita.ai/scene.mp4"]})

    def fake_compose(job_id, **_kwargs):
        for aspect in ("16x9", "9x16"):
            target = output_path(job_id, aspect)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"test mp4")
        lyrics_path(job_id).write_text("Test lyric\n", encoding="utf-8")
        return {"formats": ["16x9", "9x16"], "duration_seconds": 10, "lyrics_available": True}

    monkeypatch.setattr(main, "compose_song_video", fake_compose)
    tasks = BackgroundTasks()
    composition = asyncio.run(main.create_composition(
        main.ComposeRequest(song_job_id=UUID(song.id), video_job_id=UUID(video.id)), tasks
    ))
    assert composition.status == "queued"
    task = tasks.tasks[0]
    task.func(*task.args, **task.kwargs)
    composition = jobs.get(composition.id)
    assert composition.status == "completed"
    assert composition.result["formats"] == ["16x9", "9x16"]
    assert asyncio.run(main.download_composition(composition.id, "16x9")).path.read_bytes() == b"test mp4"
    assert asyncio.run(main.download_composition(composition.id, "9x16")).path.read_bytes() == b"test mp4"
    lyrics = asyncio.run(main.download_composition_lyrics(composition.id))
    assert lyrics.path.read_text(encoding="utf-8") == "Test lyric\n"


def test_composition_rejects_missing_or_incomplete_source_jobs(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    monkeypatch.setattr(main.shutil, "which", lambda _name: "ffmpeg.exe")
    song = jobs.create("song", {"duration_seconds": 30}, 0)
    video = jobs.create("video", {"duration": 5}, 0)
    with pytest.raises(HTTPException) as response:
        asyncio.run(main.create_composition(
            main.ComposeRequest(song_job_id=UUID(song.id), video_job_id=UUID(video.id)), BackgroundTasks()
        ))
    assert response.value.status_code == 409
