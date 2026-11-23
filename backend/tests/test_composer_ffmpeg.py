import shutil
import subprocess

import pytest

from app.services import composer


def test_ffmpeg_assembles_full_track_in_both_aspects(monkeypatch, tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and ffprobe are required for the live assembly check")

    source_audio = tmp_path / "source.mp3"
    source_video = tmp_path / "source.mp4"
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=2", "-c:a", "libmp3lame", str(source_audio)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=12:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source_video)],
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(composer.jobs, "ROOT", tmp_path / "app-data")

    def copy_source(url, target, **_kwargs):
        shutil.copyfile(source_audio if url.endswith(".mp3") else source_video, target)

    monkeypatch.setattr(composer, "_download", copy_source)
    result = composer.compose_song_video(
        "ab31d9fd-312d-4565-97df-f7d197adeb02",
        audio_url="http://127.0.0.1:8001/song.mp3",
        video_url="https://cdn.novita.ai/scene.mp4",
        duration_seconds=2,
        lyrics="One local test line",
        ffmpeg=ffmpeg,
        ace_step_base_url="http://127.0.0.1:8001",
        ace_step_api_key="",
    )

    assert result["formats"] == ["16x9", "9x16"]
    assert result["duration_seconds"] == 2
    assert composer.lyrics_path("ab31d9fd-312d-4565-97df-f7d197adeb02").read_text(encoding="utf-8").strip() == "One local test line"
    for aspect, expected in (("16x9", "1280x720"), ("9x16", "720x1280")):
        output = composer.output_path("ab31d9fd-312d-4565-97df-f7d197adeb02", aspect)
        assert output.is_file() and output.stat().st_size > 1000
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(output)],
            check=True,
            capture_output=True,
            text=True,
        )
        assert probe.stdout.strip() == expected
