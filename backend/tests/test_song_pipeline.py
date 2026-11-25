"""End-to-end song pipeline: quote -> confirm -> ACE-Step -> download -> master -> deliver."""

import asyncio
import json
import shutil
import subprocess

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main
from app.schemas import SongRequest
from app.services import jobs, lyrics, mastering, songs

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg and ffprobe are required")


def _tone(path, seconds=12, volume=0.08):
    """A quiet stereo test signal (well below -14 LUFS) so mastering has real work to do."""
    subprocess.run(
        [shutil.which("ffmpeg"), "-y", "-f", "lavfi", "-i",
         f"sine=frequency=220:sample_rate=48000:duration={seconds}", "-f", "lavfi", "-i",
         f"sine=frequency=330:sample_rate=48000:duration={seconds}", "-filter_complex",
         f"[0][1]amerge=inputs=2,volume={volume}", "-c:a", "pcm_s16le", str(path)],
        check=True, capture_output=True,
    )


@pytest.fixture
def ace(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    monkeypatch.setattr(main.settings, "ace_step_enabled", True)
    monkeypatch.setattr(main.settings, "ace_step_base_url", "http://127.0.0.1:8001")
    monkeypatch.setattr(main.settings, "ace_step_model", "acestep-v15-turbo")
    monkeypatch.setattr(main.settings, "ace_step_lm_enabled", False)
    calls = []

    async def models(_config):
        return {"object": "list", "data": [{"id": "acestep/acestep-v15-turbo"}]}

    async def submit(_config, payload):
        calls.append(payload)
        return {"task_id": "ace-task-1"}

    monkeypatch.setattr(main, "ace_step_models", models)
    monkeypatch.setattr(main, "ace_step_submit_song", submit)
    return calls


# --- lyrics -----------------------------------------------------------------

def test_plain_lyrics_get_structure_tags_and_repeated_block_is_chorus():
    text = "Line one\nLine two\n\nWe sing tonight\nWe sing tonight\n\nLine three\nLine four\n\nWe sing tonight\nWe sing tonight"
    structured = lyrics.structure_lyrics(text)
    assert structured.startswith("[Verse 1]\nLine one")
    assert structured.count("[Chorus]") == 2
    assert "[Verse 2]\nLine three" in structured


def test_tagged_lyrics_are_left_untouched():
    text = "[Verse]\nHello\n\n[Chorus]\nWorld"
    assert lyrics.structure_lyrics(text) == text


def test_word_count_ignores_tags_and_flags_overlong_lyrics():
    assert lyrics.sung_word_count("[Chorus]\nСветлина по пътя") == 3
    long_text = " ".join(["дума"] * 200)
    assert lyrics.lyric_warnings(long_text, 30)
    assert lyrics.lyric_warnings(" ".join(["word"] * 60), 30) == []


def test_generated_lyrics_are_cleaned_of_markdown_and_titles():
    raw = "```\nTitle: Нощ\n**[Verse 1]**\nПът под звезди\n```"
    assert lyrics.clean_generated_lyrics(raw) == "[Verse 1]\nПът под звезди"


# --- quote / ACE-Step payload ----------------------------------------------

def test_empty_lyrics_without_ace_lm_is_rejected_with_clear_reason(ace):
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.create_song_quote(SongRequest(prompt="night drive synthwave", duration_seconds=30)))
    assert error.value.status_code == 409
    assert "5Hz LM" in error.value.detail
    assert ace == []


def test_instrumental_song_sends_instrumental_tag(ace):
    quote = asyncio.run(main.create_song_quote(SongRequest(prompt="lofi beat", duration_seconds=30, instrumental=True)))
    asyncio.run(main.confirm_job(quote["id"]))
    assert ace[0]["lyrics"] == "[Instrumental]"
    assert ace[0]["thinking"] is False
    assert "sample_mode" not in ace[0]


def test_payload_carries_metadata_lossless_format_and_fixed_seed(ace):
    request = SongRequest(prompt="warm folk pop", genre="folk pop", mood="hopeful", lyrics="Път\n\nДом",
                          duration_seconds=40, bpm=96, key_scale="G Major", time_signature="4", seed=1234)
    quote = asyncio.run(main.create_song_quote(request))
    assert quote["payload"]["lyrics"].startswith("[Verse 1]")
    assert quote["warnings"]
    asyncio.run(main.confirm_job(quote["id"]))
    sent = ace[0]
    assert sent["audio_format"] == "wav"
    assert sent["prompt"] == "folk pop, hopeful, warm folk pop"
    assert (sent["bpm"], sent["key_scale"], sent["time_signature"]) == (96, "G Major", "4")
    assert sent["use_random_seed"] is False and sent["seed"] == 1234


def test_lm_enabled_engine_uses_thinking_and_sample_mode(ace, monkeypatch):
    monkeypatch.setattr(main.settings, "ace_step_lm_enabled", True)
    quote = asyncio.run(main.create_song_quote(SongRequest(prompt="city pop", duration_seconds=30)))
    asyncio.run(main.confirm_job(quote["id"]))
    assert ace[0]["thinking"] is True and ace[0]["sample_mode"] is True


def test_invalid_key_scale_is_rejected():
    with pytest.raises(ValueError):
        SongRequest(prompt="x pop", key_scale="H super")


# --- mastering ----------------------------------------------------------------

@needs_ffmpeg
@pytest.mark.parametrize("preset", ["streaming", "apple"])
def test_master_meets_loudness_and_true_peak_targets(tmp_path, preset):
    source = tmp_path / "quiet.wav"
    _tone(source)
    report = mastering.master_track(source, tmp_path / "out", preset=preset, title="Тест", lyrics="[Verse]\nРед")
    target = mastering.PRESETS[preset]
    assert report["before"]["integrated_lufs"] < target["lufs"] - 3
    assert abs(report["after"]["integrated_lufs"] - target["lufs"]) <= mastering.LUFS_TOLERANCE
    assert report["after"]["true_peak_dbtp"] <= target["true_peak"] + 0.1
    assert report["compliant"] is True
    probe = subprocess.run(
        [shutil.which("ffprobe"), "-v", "error", "-show_entries", "stream=sample_rate,channels,bits_per_raw_sample:format_tags=title",
         "-of", "json", str(tmp_path / "out" / "master.mp3")], check=True, capture_output=True, text=True, encoding="utf-8")
    info = json.loads(probe.stdout)
    assert info["streams"][0]["sample_rate"] == "44100" and info["streams"][0]["channels"] == 2
    assert info["format"]["tags"]["title"] == "Тест"


@needs_ffmpeg
def test_silent_audio_is_refused(tmp_path):
    source = tmp_path / "silence.wav"
    _tone(source, seconds=3, volume=0)
    with pytest.raises(mastering.MasteringError):
        mastering.master_track(source, tmp_path / "out")


# --- full pipeline through the HTTP API ------------------------------------------

@needs_ffmpeg
def test_song_job_runs_to_mastered_downloads_over_http(ace, monkeypatch, tmp_path):
    rendered = tmp_path / "ace-output.wav"
    _tone(rendered, seconds=12)

    async def status(_config, task_id):
        assert task_id == "ace-task-1"
        return {"status": 1, "audio_url": "http://127.0.0.1:8001/v1/audio?path=C%3A%5Ctmp%5Cx.wav",
                "lyrics": "[Verse]\nПът", "metadata": {"bpm": 96}}

    monkeypatch.setattr(main, "ace_step_song_status", status)
    monkeypatch.setattr(songs, "_download", lambda _url, target, **_kw: shutil.copyfile(rendered, target))

    with TestClient(main.app) as client:
        quote = client.post("/api/v1/jobs/song/quote", json={"title": "Път", "prompt": "folk pop", "lyrics": "[Verse]\nПът", "duration_seconds": 12})
        assert quote.status_code == 200, quote.text
        job_id = quote.json()["id"]
        assert client.post(f"/api/v1/jobs/{job_id}/confirm").json()["status"] == "running"
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        for _ in range(100):
            if body["status"] != "mastering":
                break
            asyncio.run(asyncio.sleep(0.1))
            body = client.get(f"/api/v1/jobs/{job_id}").json()
        assert body["status"] == "completed", body
        assert body["result"]["mastering"]["compliant"] is True
        assert set(body["result"]["files"]) >= {"mp3", "wav", "raw", "lyrics", "report"}
        mp3 = client.get(body["result"]["files"]["mp3"])
        assert mp3.status_code == 200 and mp3.headers["content-type"] == "audio/mpeg" and len(mp3.content) > 10_000
        assert client.get(body["result"]["files"]["lyrics"]).text.strip() == "[Verse]\nПът"
        assert (songs.song_dir(job_id) / "raw.wav").is_file()
        listed = client.get("/api/v1/jobs", params={"kind": "song"}).json()["jobs"]
        assert listed[0]["id"] == job_id
        assert client.get(f"/api/v1/songs/{job_id}/nope").status_code == 404


def test_composition_lyrics_route_is_not_shadowed_by_aspect_route(monkeypatch, tmp_path):
    from app.services.composer import lyrics_path

    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    job = jobs.create("composition", {}, 0)
    jobs.update(job.id, status="completed")
    lyrics_path(job.id).parent.mkdir(parents=True, exist_ok=True)
    lyrics_path(job.id).write_text("Ред\n", encoding="utf-8", newline="\n")
    with TestClient(main.app) as client:
        response = client.get(f"/api/v1/media/{job.id}/lyrics")
    assert response.status_code == 200
    assert response.text == "Ред\n"
