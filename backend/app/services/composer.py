"""Local FFmpeg assembly of completed ACE-Step songs and Novita video clips."""

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import httpx

from app.services import jobs
from app.services.mastering import probe_duration

_FORMATS = {"16x9": (1280, 720), "9x16": (720, 1280)}
_MAX_DOWNLOAD_BYTES = 1_000_000_000


def _safe_asset_url(url: str, trusted_base: str, *, cloud_media: bool = False) -> str:
    parsed = urlparse(url)
    trusted = urlparse(trusted_base)
    same_endpoint = parsed.scheme == trusted.scheme and parsed.hostname == trusted.hostname and parsed.port == trusted.port
    cloud_host = parsed.scheme == "https" and parsed.hostname and (
        parsed.hostname == "amazonaws.com"
        or parsed.hostname.endswith(".amazonaws.com")
        or parsed.hostname == "novita.ai"
        or parsed.hostname.endswith(".novita.ai")
    )
    if not parsed.hostname or not parsed.path or not (same_endpoint or (cloud_media and cloud_host)):
        raise ValueError("Provider returned a media URL outside its configured service.")
    return url


def _download(url: str, target: Path, *, api_key: str = "") -> None:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    total = 0
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=20.0), follow_redirects=False) as client, client.stream(
        "GET", url, headers=headers
    ) as response:
        response.raise_for_status()
        length = response.headers.get("content-length")
        if length and int(length) > _MAX_DOWNLOAD_BYTES:
            raise ValueError("Generated media is larger than the 1 GB assembly limit.")
        with target.open("wb") as output:
            for chunk in response.iter_bytes(1024 * 1024):
                total += len(chunk)
                if total > _MAX_DOWNLOAD_BYTES:
                    raise ValueError("Generated media is larger than the 1 GB assembly limit.")
                output.write(chunk)


def output_path(job_id: str, aspect: str) -> Path:
    if aspect not in _FORMATS:
        raise ValueError("Unsupported video aspect ratio")
    return jobs.ROOT / "media" / job_id / f"music-video-{aspect}.mp4"


def lyrics_path(job_id: str) -> Path:
    return jobs.ROOT / "media" / job_id / "lyrics.txt"


def compose_song_video(
    job_id: str,
    *,
    audio_url: str,
    video_url: str,
    duration_seconds: int,
    lyrics: str,
    ffmpeg: str,
    ace_step_base_url: str,
    ace_step_api_key: str,
    local_audio: Path | None = None,
) -> dict:
    video_url = _safe_asset_url(video_url, "https://api.novita.ai", cloud_media=True)
    destination = jobs.ROOT / "media" / job_id
    destination.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="compose-", dir=destination) as temp_dir:
        temp = Path(temp_dir)
        video_file = temp / "scene.mp4"
        if local_audio is not None and local_audio.is_file():
            # Prefer the loudness-mastered song; it is already on disk.
            audio_file = local_audio
        else:
            audio_url = _safe_asset_url(audio_url, ace_step_base_url, cloud_media=True)
            audio_file = temp / "track.mp3"
            audio_needs_key = urlparse(audio_url).hostname == urlparse(ace_step_base_url).hostname
            _download(audio_url, audio_file, api_key=ace_step_api_key if audio_needs_key else "")
        _download(video_url, video_file)
        try:
            # ACE-Step's output length can differ slightly from the requested duration.
            duration_seconds = max(1, round(probe_duration(audio_file), 2))  # type: ignore[assignment]
        except Exception:
            pass
        for aspect, (width, height) in _FORMATS.items():
            output = output_path(job_id, aspect)
            filter_graph = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"
            command = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-stream_loop", "-1", "-i", str(video_file),
                "-i", str(audio_file), "-t", str(duration_seconds), "-map", "0:v:0", "-map", "1:a:0",
                "-vf", filter_graph, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(output),
            ]
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=max(300, duration_seconds * 15),
                creationflags=creation_flags,
            )
            if completed.returncode != 0:
                raise RuntimeError("FFmpeg could not assemble the generated audio and video.")

    if lyrics.strip():
        lyrics_path(job_id).write_text(lyrics.strip() + "\n", encoding="utf-8", newline="\n")
    return {
        "formats": list(_FORMATS.keys()),
        "duration_seconds": duration_seconds,
        "lyrics_available": bool(lyrics.strip()),
    }
