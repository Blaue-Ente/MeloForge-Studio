"""Sing a finished song in a cloned voice (local, zero-shot).

Pipeline (the established approach for AI "cover" vocals):
1. Demucs ``htdemucs`` splits the generated song into vocals and instrumental.
2. Seed-VC (singing model, 44.1 kHz, F0-conditioned) converts the vocal stem to
   the timbre of a 5-30 s reference recording of the user's own voice. The
   melody, timing and lyrics come from the source vocal, so the language of the
   song does not matter.
3. The converted vocal is level-matched to the original stem, mixed back over
   the instrumental and mastered with the normal delivery presets.

Seed-VC and Demucs live in their own Python environment (torch + CUDA), run as
subprocesses so MeloForge itself stays light. Voice profiles are personal data:
they are stored only under ``data/voices`` and are created only with an
explicit consent confirmation that the voice belongs to the uploader (or that
they hold the owner's permission).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from app.services import jobs
from app.services.mastering import measure, probe_duration

REFERENCE_MIN_SECONDS = 5.0
REFERENCE_MAX_SECONDS = 25.0  # Seed-VC's prompt window; longer clips only add cost.
MAX_UPLOAD_BYTES = 40 * 1024 * 1024
_SAFE_ID = re.compile(r"^[0-9a-f]{32}$")
QUALITY_STEPS = {"fast": 15, "balanced": 30, "best": 50}
# Runs Seed-VC's inference.py with the BigVGAN vocoder under fp16 autocast. On a
# 4 GB RTX 2050 the fp32 vocoder dominated (RTF 9.1 -> 3.2 for the whole run).
_SEEDVC_DRIVER = """
import runpy, sys, torch
from modules.bigvgan import bigvgan
_orig = bigvgan.BigVGAN.forward
def _fp16(self, x):
    with torch.autocast('cuda', dtype=torch.float16):
        return _orig(self, x).float()
if torch.cuda.is_available():
    bigvgan.BigVGAN.forward = _fp16
sys.argv = ['inference.py'] + sys.argv[1:]
runpy.run_path('inference.py', run_name='__main__')
"""


class VoiceCloneError(RuntimeError):
    pass


def engine_dir() -> Path:
    default = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / "Seed-VC"
    return Path(os.environ.get("MELOFORGE_SEEDVC_DIR", default))


def engine_python() -> Path:
    folder = engine_dir() / ".venv"
    return folder / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def engine_status() -> dict:
    folder = engine_dir()
    python = engine_python()
    site_packages = [folder / ".venv" / "Lib" / "site-packages", *(folder / ".venv" / "lib").glob("python3*/site-packages")]
    packages_ready = any((site / "torch").is_dir() and (site / "demucs").is_dir() for site in site_packages)
    installed = (folder / "inference.py").is_file() and python.is_file() and packages_ready
    cache = folder / "checkpoints"  # Seed-VC's hf_utils downloads its models here
    return {
        "installed": installed,
        "engine": "Seed-VC (singing, zero-shot) + Demucs htdemucs",
        "dir": str(folder),
        "models_downloaded": cache.is_dir() and any(cache.rglob("*.pth")),
        "license": "Seed-VC GPL-3.0, Demucs MIT — local, personal use",
        "install_hint": None if installed else (
            "git clone https://github.com/Plachtaa/seed-vc into %LOCALAPPDATA%\\Programs\\Seed-VC, "
            "then create .venv (Python 3.10) with torch 2.4 cu121 and the packages in requirements.txt plus demucs."
        ),
    }


def _flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise VoiceCloneError("FFmpeg is not installed")
    return path


def _run(command: list[str], *, cwd: Path | None = None, timeout: int = 3600, env: dict | None = None) -> str:
    completed = subprocess.run(
        command, cwd=cwd, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=_flags(), env=env,
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "").strip()[-600:]
        raise VoiceCloneError(f"{Path(command[0]).name} failed: {tail}")
    return completed.stdout


def _engine_env() -> dict:
    env = os.environ.copy()
    env["HF_HOME"] = str(engine_dir() / "hf_cache")
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)
    return env


# ---------------------------------------------------------------- voice profiles

def voices_root() -> Path:
    return jobs.ROOT / "voices"


def voice_dir(voice_id: str) -> Path:
    if not _SAFE_ID.match(voice_id or ""):
        raise VoiceCloneError("Invalid voice id")
    return voices_root() / voice_id


def list_voices() -> list[dict]:
    root = voices_root()
    if not root.is_dir():
        return []
    voices = []
    for meta in root.glob("*/voice.json"):
        try:
            voices.append(json.loads(meta.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(voices, key=lambda item: item.get("created_at", 0), reverse=True)


def get_voice(voice_id: str) -> dict | None:
    try:
        meta = voice_dir(voice_id) / "voice.json"
    except VoiceCloneError:
        return None
    if not meta.is_file():
        return None
    return json.loads(meta.read_text(encoding="utf-8"))


def prepare_reference(source: Path, destination: Path) -> float:
    """Clean a user recording into a mono 44.1 kHz WAV prompt for Seed-VC."""
    _run([
        _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-af", (
            "highpass=f=70,"
            "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.2,"
            "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.3,areverse,"
            "loudnorm=I=-20:TP=-2:LRA=11"
        ),
        "-ac", "1", "-ar", "44100", "-t", f"{REFERENCE_MAX_SECONDS}", "-c:a", "pcm_s16le", str(destination),
    ], timeout=300)
    return probe_duration(destination)


def create_voice(*, name: str, data: bytes, filename: str, consent: bool) -> dict:
    if not consent:
        raise VoiceCloneError("consent")
    if not data:
        raise VoiceCloneError("empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise VoiceCloneError("too_large")
    voice_id = uuid.uuid4().hex
    folder = voice_dir(voice_id)
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename or "upload").suffix.lower()
    if suffix not in {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac", ".aac", ".opus"}:
        suffix = ".bin"
    upload = folder / f"upload{suffix}"
    upload.write_bytes(data)
    try:
        seconds = prepare_reference(upload, folder / "reference.wav")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise VoiceCloneError("unreadable")
    finally:
        upload.unlink(missing_ok=True)
    if seconds < REFERENCE_MIN_SECONDS:
        shutil.rmtree(folder, ignore_errors=True)
        raise VoiceCloneError("too_short")
    meta = {
        "id": voice_id,
        "name": (name or "Моят глас").strip()[:60],
        "reference_seconds": round(seconds, 1),
        "consent": "owner_or_permission_confirmed",
        "created_at": int(time.time()),
    }
    (folder / "voice.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def tag_voice(voice_id: str, **extra) -> dict:
    """Add provenance fields (e.g. source=elevenlabs) to a voice profile."""
    meta_path = voice_dir(voice_id) / "voice.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(extra)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def delete_voice(voice_id: str) -> bool:
    folder = voice_dir(voice_id)
    if not folder.is_dir():
        return False
    shutil.rmtree(folder)
    return True


# ---------------------------------------------------------------- conversion

def separate(audio: Path, workdir: Path) -> tuple[Path, Path]:
    """Split a song into (vocals, instrumental) with Demucs htdemucs."""
    workdir.mkdir(parents=True, exist_ok=True)
    base = [str(engine_python()), "-m", "demucs.separate", "-n", "htdemucs", "--two-stems", "vocals",
            "-o", str(workdir), "--filename", "{stem}.{ext}"]
    try:
        # Small segments keep the 4 GB laptop GPUs inside their memory budget.
        _run(base + ["-d", "cuda", "--segment", "7", str(audio)], env=_engine_env(), timeout=1800)
    except VoiceCloneError:
        _run(base + ["-d", "cpu", str(audio)], env=_engine_env(), timeout=3600)
    stems = workdir / "htdemucs"
    vocals, instrumental = stems / "vocals.wav", stems / "no_vocals.wav"
    if not vocals.is_file() or not instrumental.is_file():
        raise VoiceCloneError("Demucs did not produce stems")
    return vocals, instrumental


def convert_vocals(vocals: Path, reference: Path, workdir: Path, *, semitones: int = 0, quality: str = "balanced",
                   name: str = "converted") -> Path:
    out = workdir / name
    if out.exists():
        shutil.rmtree(out)
    _run([
        str(engine_python()), "-c", _SEEDVC_DRIVER, "--source", str(vocals), "--target", str(reference),
        "--output", str(out), "--diffusion-steps", str(QUALITY_STEPS.get(quality, 30)),
        "--length-adjust", "1.0", "--inference-cfg-rate", "0.7", "--f0-condition", "True",
        "--auto-f0-adjust", "False", "--semi-tone-shift", str(int(semitones)), "--fp16", "True",
    ], cwd=engine_dir(), env=_engine_env(), timeout=max(3600, int(probe_duration(vocals) * 60)))
    produced = sorted(out.glob("vc_*.wav"))
    if not produced:
        raise VoiceCloneError("Seed-VC produced no output")
    return produced[0]


def mix_vocals(converted: Path, original_vocals: Path, instrumental: Path, destination: Path, *, vocal_gain_db: float = 0.0) -> float:
    """Level-match the converted vocal to the original stem and lay it over the instrumental."""
    try:
        gain = measure(original_vocals).integrated_lufs - measure(converted).integrated_lufs
    except Exception:
        gain = 0.0
    gain = max(-12.0, min(12.0, gain)) + vocal_gain_db
    _run([
        _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(instrumental), "-i", str(converted),
        "-filter_complex",
        f"[0:a]aresample=44100,aformat=channel_layouts=stereo[inst];"
        f"[1:a]aresample=44100,aformat=channel_layouts=stereo,volume={gain:.2f}dB[vox];"
        "[inst][vox]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[out]",
        "-map", "[out]", "-c:a", "pcm_s24le", str(destination),
    ], timeout=600)
    return round(gain, 2)


def align_stem(source: Path, destination: Path, *, length_seconds: float, gain_db: float = 0.0) -> None:
    """Write a stem sample-aligned with the mix: starts at 0, padded/trimmed to the same length."""
    _run([
        _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-af", f"aresample=44100,aformat=channel_layouts=stereo,volume={gain_db:.2f}dB,apad,atrim=0:{length_seconds:.6f}",
        "-c:a", "pcm_s16le", str(destination),
    ], timeout=600)


def export_stems(audio: Path, output_dir: Path) -> dict:
    """Demucs vocals/instrumental for an existing song, aligned to ``audio`` (for video sync)."""
    if not engine_status()["installed"]:
        raise VoiceCloneError("Seed-VC/Demucs environment is not installed")
    work = output_dir / ".stems-work"
    started = time.time()
    try:
        vocals, instrumental = separate(audio, work)
        length = probe_duration(audio)
        align_stem(vocals, output_dir / "vocals.wav", length_seconds=length)
        align_stem(instrumental, output_dir / "instrumental.wav", length_seconds=length)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"separation_seconds": round(time.time() - started, 1)}


def sing_in_voice(*, source_audio: Path, reference: Path, output_dir: Path, semitones: int = 0,
                  quality: str = "balanced", vocal_gain_db: float = 0.0) -> dict:
    """Single voice over the whole song (kept for callers and the CLI)."""
    return sing_arrangement(source_audio=source_audio, voices={"A": (reference, semitones)}, output_dir=output_dir,
                            quality=quality, vocal_gain_db=vocal_gain_db)


def sing_arrangement(*, source_audio: Path, voices: dict[str, tuple[Path, int]], output_dir: Path,
                     parts: dict[int, str] | None = None, lyrics: str = "", language: str = "bg",
                     quality: str = "balanced", vocal_gain_db: float = 0.0,
                     line_parts: dict[int, str] | None = None, harmony: str = "off", keyscale: str = "") -> dict:
    """Re-sing a song with one or two cloned voices; sections may be solo, together, original or choir.

    ``voices`` maps "A"/"B" to (reference wav, semitone shift). ``parts`` maps lyric
    section index to a mode from ``arrangement.PART_MODES``. Without parts (or with
    A everywhere) this is the plain single-voice swap.
    """
    from app.services import arrangement

    status = engine_status()
    if not status["installed"]:
        raise VoiceCloneError("Seed-VC is not installed")
    work = output_dir / ".voice-work"
    work.mkdir(parents=True, exist_ok=True)
    timings: dict = {}
    started = time.time()
    vocals, instrumental = separate(source_audio, work / "stems")
    timings["separation_seconds"] = round(time.time() - started, 1)
    length = probe_duration(instrumental)
    parts = parts or {}
    line_parts = line_parts or {}
    all_modes = list(parts.values()) + list(line_parts.values())
    needed = {"A"} | {voice for mode in all_modes for voice in (("A", "B") if mode in {"AB", "choir"} else ("A",) if mode == "harmony" else (mode,))}
    needed = {voice for voice in needed if voice in voices}
    started = time.time()
    converted: dict[str, Path] = {}
    gains: dict[str, float] = {}
    for key in sorted(needed):
        reference, semitones = voices[key]
        raw = convert_vocals(vocals, reference, work, semitones=semitones, quality=quality, name=f"converted-{key}")
        try:
            gain = measure(vocals).integrated_lufs - measure(raw).integrated_lufs
        except Exception:
            gain = 0.0
        gains[key] = round(max(-12.0, min(12.0, gain)), 2)
        converted[key] = work / f"voice-{key}.wav"
        align_stem(raw, converted[key], length_seconds=length, gain_db=gains[key])
    timings["conversion_seconds"] = round(time.time() - started, 1)
    simple = set(all_modes) <= {"A"}
    sections_used = None
    if simple:
        vocal_mix = converted["A"]
    else:
        started = time.time()
        words = arrangement.transcribe_words(vocals, language=language, cache=work / "words.json")
        timed = arrangement.align_lyrics(lyrics, words, length)
        spans = arrangement.section_spans(lyrics, timed, length)
        sections_used = [{"label": s["label"], "start": s["start"], "end": s["end"], "mode": parts.get(s["index"], "A")} for s in spans]
        if line_parts:
            spans, parts = arrangement.apply_line_parts(spans, parts, timed, line_parts)
        original = work / "voice-original.wav"
        align_stem(vocals, original, length_seconds=length)
        layers = arrangement.plan_layers(spans=spans, parts=parts, converted=converted, original=original)
        key = arrangement.parse_key(keyscale)
        harmony_windows = {mode: [(s["start"], s["end"]) for s in spans if parts.get(s["index"]) == mode] for mode in ("harmony", "choir")}
        if harmony != "off" and key and (harmony_windows["harmony"] or harmony_windows["choir"]):
            notes = arrangement.run_worker({"cmd": "notes", "audio": str(vocals)})["notes"]
            groups = arrangement.harmony_segments(notes, key, harmony)
            for voice, pan in (("A", -0.35), ("B", 0.35)):
                if voice not in converted:
                    continue
                windows = harmony_windows["choir"] + (harmony_windows["harmony"] if voice == "A" else [])
                for shift, segments in groups.items():
                    chosen = arrangement.intersect(segments, windows)
                    if not chosen:
                        continue
                    shifted = work / f"harmony-{voice}-{shift}.wav"
                    if not shifted.is_file():
                        _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(converted[voice]), "-af",
                              f"rubberband=pitch={2 ** (shift / 12):.6f}:formant=preserved:pitchq=quality",
                              "-c:a", "pcm_s16le", str(shifted)], timeout=600)
                    layers.append({"path": str(shifted), "segments": chosen, "gain_db": -6.0, "pan": pan})
            timings["harmony"] = {"interval": harmony, "key": keyscale, "notes": len(notes)}
        vocal_mix = work / "vocal-mix.wav"
        arrangement.run_worker({"cmd": "mix", "length": length, "out": str(vocal_mix), "layers": layers})
        if line_parts:
            timings["line_overrides"] = len(line_parts)
        timings["arrangement_seconds"] = round(time.time() - started, 1)
        timings["lyric_lines_heard"] = sum(1 for line in timed if line["heard"])
        timings["lyric_lines"] = len(timed)
        (output_dir / "lyric-timing.json").write_text(json.dumps(arrangement.lyric_timing(timed), ensure_ascii=False, indent=2), encoding="utf-8")
    mixed = output_dir / "raw.wav"
    _run([
        _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(instrumental), "-i", str(vocal_mix),
        "-filter_complex",
        "[0:a]aresample=44100,aformat=channel_layouts=stereo[inst];"
        f"[1:a]aresample=44100,aformat=channel_layouts=stereo,volume={vocal_gain_db:.2f}dB[vox];"
        "[inst][vox]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[out]",
        "-map", "[out]", "-c:a", "pcm_s24le", str(mixed),
    ], timeout=600)
    align_stem(vocal_mix, output_dir / "vocals.wav", length_seconds=length, gain_db=vocal_gain_db)
    shutil.copyfile(instrumental, output_dir / "instrumental.wav")
    shutil.rmtree(work, ignore_errors=True)
    return {"mix": mixed, "vocal_gain_db": gains, "sections": sections_used, **timings}
