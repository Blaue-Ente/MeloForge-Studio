"""Loudness mastering and delivery exports for generated songs.

Targets follow the published delivery norms:
- streaming: -14 LUFS integrated, -1 dBTP (Spotify, YouTube, Tidal, Amazon)
- apple: -16 LUFS integrated, -1 dBTP (Apple Music Sound Check)
- broadcast: -23 LUFS integrated, -1 dBTP (EBU R128)

Measurement uses FFmpeg's ``loudnorm`` filter (ITU-R BS.1770 / EBU R128) in a
two-pass, linear configuration so the dynamics of the track are preserved
whenever the true-peak ceiling allows it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

PRESETS: dict[str, dict[str, float]] = {
    "streaming": {"lufs": -14.0, "true_peak": -1.0, "lra": 11.0},
    "apple": {"lufs": -16.0, "true_peak": -1.0, "lra": 11.0},
    "broadcast": {"lufs": -23.0, "true_peak": -1.0, "lra": 15.0},
}
SAMPLE_RATE = 44_100
LUFS_TOLERANCE = 1.0


@dataclass
class LoudnessReport:
    integrated_lufs: float
    true_peak_dbtp: float
    loudness_range_lu: float
    duration_seconds: float


class MasteringError(RuntimeError):
    pass


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise MasteringError(f"{name} is not installed")
    return path


def _run(command: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=_creation_flags(),
    )


def probe_duration(path: Path) -> float:
    completed = _run([
        _tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ], timeout=60)
    try:
        return float(completed.stdout.strip())
    except ValueError as exc:
        raise MasteringError("Could not read the audio duration") from exc


def _loudnorm_json(stderr: str) -> dict:
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.S)
    if not match:
        raise MasteringError("FFmpeg did not report loudness statistics")
    return json.loads(match.group(0))


def _num(value: str | float) -> float:
    number = float(value)
    # Digital silence reports -inf; clamp to a printable floor.
    return max(number, -99.0)


def measure(path: Path) -> LoudnessReport:
    """Measure integrated loudness, true peak and LRA without changing the file."""
    completed = _run([
        _tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path),
        "-af", "loudnorm=print_format=json", "-f", "null", "-",
    ])
    if completed.returncode != 0:
        raise MasteringError("FFmpeg could not analyse the audio")
    stats = _loudnorm_json(completed.stderr)
    return LoudnessReport(
        integrated_lufs=round(_num(stats["input_i"]), 2),
        true_peak_dbtp=round(_num(stats["input_tp"]), 2),
        loudness_range_lu=round(_num(stats["input_lra"]), 2),
        duration_seconds=round(probe_duration(path), 2),
    )


def _metadata_args(title: str, artist: str, lyrics: str, genre: str) -> list[str]:
    args: list[str] = []
    for key, value in (("title", title), ("artist", artist), ("album_artist", artist), ("genre", genre)):
        if value:
            args += ["-metadata", f"{key}={value}"]
    if lyrics:
        args += ["-metadata", f"lyrics={lyrics}"]
    return args


def master_track(
    source: Path,
    destination: Path,
    *,
    preset: str = "streaming",
    title: str = "",
    artist: str = "MeloForge Studio",
    genre: str = "",
    lyrics: str = "",
    fade_out_seconds: float = 1.5,
) -> dict:
    """Two-pass loudness master; writes ``master.wav`` (24-bit) and ``master.mp3`` (320k)."""
    if preset not in PRESETS:
        raise MasteringError(f"Unknown mastering preset: {preset}")
    target = PRESETS[preset]
    ffmpeg = _tool("ffmpeg")
    destination.mkdir(parents=True, exist_ok=True)

    before = measure(source)
    if before.integrated_lufs <= -70:
        raise MasteringError("The generated audio is silent")

    fade = ""
    if fade_out_seconds > 0 and before.duration_seconds > fade_out_seconds * 4:
        start = max(0.0, before.duration_seconds - fade_out_seconds)
        fade = f"afade=t=out:st={start:.3f}:d={fade_out_seconds:.3f},"

    # Pass 1 statistics feed pass 2 so the gain is computed for the whole song.
    pass1 = _run([
        ffmpeg, "-hide_banner", "-nostats", "-i", str(source), "-af",
        f"{fade}loudnorm=I={target['lufs']}:TP={target['true_peak']}:LRA={target['lra']}:print_format=json",
        "-f", "null", "-",
    ])
    if pass1.returncode != 0:
        raise MasteringError("FFmpeg loudness analysis failed")
    stats = _loudnorm_json(pass1.stderr)
    loudnorm = (
        f"loudnorm=I={target['lufs']}:TP={target['true_peak']}:LRA={target['lra']}"
        f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
        f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
        f":offset={stats['target_offset']}:linear=true:print_format=json"
    )
    # loudnorm upsamples internally to 192 kHz; resample back with a quality resampler.
    chain = f"{fade}{loudnorm},aresample={SAMPLE_RATE}:resampler=soxr:precision=28"

    wav_path = destination / "master.wav"
    mp3_path = destination / "master.mp3"
    meta = _metadata_args(title, artist, lyrics, genre)
    wav = _run([
        ffmpeg, "-y", "-hide_banner", "-nostats", "-i", str(source), "-af", chain,
        "-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", "pcm_s24le", *meta, str(wav_path),
    ])
    if wav.returncode != 0 or not wav_path.is_file():
        raise MasteringError("FFmpeg could not write the WAV master")
    # Encode MP3 from the finished master so both deliverables are identical in level.
    mp3 = _run([
        ffmpeg, "-y", "-hide_banner", "-nostats", "-i", str(wav_path), "-c:a", "libmp3lame",
        "-b:a", "320k", "-id3v2_version", "3", *meta, str(mp3_path),
    ])
    if mp3.returncode != 0 or not mp3_path.is_file():
        raise MasteringError("FFmpeg could not write the MP3 master")

    after = measure(wav_path)
    mp3_after = measure(mp3_path)
    compliant = (
        abs(after.integrated_lufs - target["lufs"]) <= LUFS_TOLERANCE
        and after.true_peak_dbtp <= target["true_peak"] + 0.1
        and mp3_after.true_peak_dbtp <= target["true_peak"] + 0.5
    )
    report = {
        "preset": preset,
        "target": target,
        "sample_rate": SAMPLE_RATE,
        "channels": 2,
        "before": asdict(before),
        "after": asdict(after),
        "mp3_after": asdict(mp3_after),
        "compliant": compliant,
        "files": {"wav": wav_path.name, "mp3": mp3_path.name},
    }
    (destination / "mastering-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
