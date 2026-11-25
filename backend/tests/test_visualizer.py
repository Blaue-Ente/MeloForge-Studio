import asyncio
import shutil
import subprocess
from uuid import UUID

import pytest
from fastapi import BackgroundTasks, HTTPException

from app import main
from app.schemas import VisualizerRequest
from app.services import jobs, songs, visualizer

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="FFmpeg required")


def _tone(path, seconds=6):
    subprocess.run([shutil.which("ffmpeg"), "-y", "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
                    "-ac", "2", "-c:a", "libmp3lame", str(path)], check=True, capture_output=True)


def test_lyric_timeline_skips_tags_and_stays_inside_song():
    timeline = visualizer.lyric_timeline("[Verse]\nедно две три\n\n[Chorus]\nчетири пет", 100)
    assert [line for _, _, line in timeline] == ["едно две три", "четири пет"]
    assert timeline[0][0] == 8.0 and timeline[-1][1] <= 94
    assert timeline[0][1] - timeline[0][0] > timeline[1][1] - timeline[1][0]  # more words, more time
    assert visualizer.lyric_timeline("", 100) == []


def test_filter_script_uses_text_files_and_palette(tmp_path):
    script = visualizer.build_filter_script(workdir=tmp_path, width=1280, height=720, duration=30, style="wave",
                                            palette="sunset", title="Заглавие: 'тест'", subtitle="pop",
                                            timeline=[(2.0, 4.0, "ред")])
    assert "showwaves" in script and "gradients" in script and "[vout]" in script
    assert "Заглавие" not in script  # text goes through UTF-8 files, never inline
    assert (tmp_path / "title.txt").read_text(encoding="utf-8") == "Заглавие: 'тест'"
    assert "between(t,2.0,4.0)" in script


@needs_ffmpeg
@pytest.mark.parametrize("style", visualizer.STYLES)
def test_render_produces_both_aspects(tmp_path, style):
    audio = tmp_path / "song.mp3"
    _tone(audio, seconds=12)
    result = visualizer.render_visualizer(audio=audio, output_dir=tmp_path / "out", ffmpeg=shutil.which("ffmpeg"),
                                          title="Тест", subtitle="pop", lyrics="[Verse]\nедно\nдве", style=style,
                                          show_lyrics=True)
    assert result["formats"] == ["16x9", "9x16"] and result["lyrics_timing"] == "approximate"
    for aspect, size in (("16x9", "1280x720"), ("9x16", "720x1280")):
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                                "-of", "csv=s=x:p=0", str(tmp_path / "out" / f"music-video-{aspect}.mp4")],
                               capture_output=True, text=True, check=True)
        assert probe.stdout.strip() == size
    assert not list((tmp_path / "out").glob(".viz-*"))


@needs_ffmpeg
def test_visualizer_endpoint_runs_and_serves_downloads(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    song = jobs.create("song", {"title": "Песен", "genre": "pop", "lyrics": "[Verse]\nред"}, 0)
    jobs.update(song.id, status="completed", result={"lyrics": "[Verse]\nред"})
    songs.song_dir(song.id).mkdir(parents=True)
    _tone(songs.song_dir(song.id) / "master.mp3")

    tasks = BackgroundTasks()
    job = asyncio.run(main.create_visualizer(VisualizerRequest(song_job_id=UUID(song.id), style="pulse"), tasks))
    assert job.status == "queued" and job.payload["mode"] == "visualizer"
    task = tasks.tasks[0]
    task.func(*task.args, **task.kwargs)
    done = jobs.get(job.id)
    assert done.status == "completed", done.error
    assert asyncio.run(main.download_composition(done.id, "9x16")).path.stat().st_size > 1000
    assert asyncio.run(main.download_composition_lyrics(done.id)).path.read_text(encoding="utf-8") == "[Verse]\nред\n"


def test_visualizer_requires_mastered_song(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    song = jobs.create("song", {}, 0)
    jobs.update(song.id, status="completed", result={})
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.create_visualizer(VisualizerRequest(song_job_id=UUID(song.id)), BackgroundTasks()))
    assert error.value.status_code == 409
