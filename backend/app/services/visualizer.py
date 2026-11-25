"""Free, fully local music video: animated background + audio-reactive visualizer.

No AI video provider is involved. FFmpeg renders 16:9 and 9:16 versions from the
mastered song: an animated gradient in the chosen palette, a glowing spectrum /
waveform / vectorscope that reacts to the audio, title and genre with a fade-in,
a progress bar, and (optionally) the lyrics on screen. Lyric timing is an
estimate spread over the song by word count; ACE-Step returns no timestamps.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from app.services.lyrics import sung_word_count
from app.services.mastering import probe_duration

FORMATS = {"16x9": (1280, 720), "9x16": (720, 1280)}
STYLES = ("spectrum", "wave", "pulse")
PALETTES: dict[str, dict[str, str]] = {
    # Two gradient colours and the visualizer colour.
    "neon": {"c0": "0x1a0b3d", "c1": "0x0b2a4a", "viz": "0x6fe3ff", "accent": "0xff5fd2"},
    "sunset": {"c0": "0x3d0f2b", "c1": "0x5a2a0b", "viz": "0xffc46b", "accent": "0xff6b6b"},
    "ocean": {"c0": "0x041c2e", "c1": "0x0a3d3a", "viz": "0x7affd6", "accent": "0x5ab0ff"},
    "mono": {"c0": "0x0c0c0e", "c1": "0x222228", "viz": "0xf2f2f2", "accent": "0x9a9aa4"},
}
FPS = 30
_FONT_CANDIDATES = {
    "bold": ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "regular": ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}
_TAG = re.compile(r"^\s*\[[^\]\n]{1,60}\]\s*$")


class VisualizerError(RuntimeError):
    pass


def _font(kind: str) -> str:
    for candidate in _FONT_CANDIDATES[kind]:
        if Path(candidate).is_file():
            return candidate
    raise VisualizerError("No font with Cyrillic support was found")


def _ff_path(path: Path | str) -> str:
    """Escape a path for use inside an FFmpeg filter option value."""
    text = str(path).replace("\\", "/")
    return text.replace(":", r"\:").replace("'", r"\'")


def lyric_timeline(lyrics: str, duration: float) -> list[tuple[float, float, str]]:
    """Spread sung lines over the song in proportion to their word count.

    Leaves ~8% for an intro and ~6% for an outro. An approximation only.
    """
    lines = [line.strip() for line in lyrics.splitlines() if line.strip() and not _TAG.match(line)]
    if not lines or duration <= 10:
        return []
    start, end = duration * 0.08, duration * 0.94
    weights = [max(1, sung_word_count(line)) + 1 for line in lines]
    unit = (end - start) / sum(weights)
    timeline, cursor = [], start
    for line, weight in zip(lines, weights):
        length = weight * unit
        timeline.append((round(cursor, 2), round(cursor + length - 0.15, 2), line))
        cursor += length
    return timeline


def _viz_filter(style: str, width: int, height: int, colour: str) -> tuple[str, int, int]:
    if style == "wave":
        h = int(height * 0.32)
        return f"showwaves=s={width}x{h}:mode=cline:rate={FPS}:colors=white:scale=sqrt:draw=full", width, h
    if style == "pulse":
        size = int(width * 0.62) if height > width else int(height * 0.50)
        # The scope draws on opaque black; key it out so only the trace remains.
        return (f"avectorscope=s={size}x{size}:rate={FPS}:mode=lissajous_xy:draw=line:scale=sqrt:zoom=1.3"
                f":rc=255:gc=255:bc=255:rf=40:gf=40:bf=40,format=rgba,colorkey=black:0.12:0.08"), size, size
    h = int(height * 0.30) // 2 * 2
    # Log-amplitude bar spectrum: a "skyline" across the full width.
    return (f"showfreqs=s={width}x{h}:rate={FPS}:mode=bar:ascale=log:fscale=log:win_size=2048"
            f":averaging=3:colors=white,format=rgba,colorchannelmixer=aa=0.92"), width, h


def _tint(colour: str) -> str:
    """Multiply a white visualizer by the palette colour (keeps its alpha)."""
    value = int(colour, 16)
    r, g, b = (value >> 16) & 255, (value >> 8) & 255, value & 255
    return f"colorchannelmixer=rr={r / 255:.3f}:rg=0:rb=0:gr=0:gg={g / 255:.3f}:gb=0:br=0:bg=0:bb={b / 255:.3f}"


def build_filter_script(*, workdir: Path, width: int, height: int, duration: float, style: str, palette: str,
                        title: str, subtitle: str, timeline: list[tuple[float, float, str]]) -> str:
    colours = PALETTES[palette]
    portrait = height > width
    bold, regular = _ff_path(_font("bold")), _ff_path(_font("regular"))
    viz, vw, vh = _viz_filter(style, width, height, colours["viz"])
    viz_y = int(height * (0.50 if portrait else 0.55)) - vh // 2 if style == "pulse" else int(height * (0.58 if portrait else 0.56)) - vh // 2
    viz_x = (width - vw) // 2

    def text_file(name: str, text: str) -> str:
        path = workdir / name
        path.write_text(text, encoding="utf-8", newline="\n")
        return _ff_path(path)

    title_size = int(width * (0.075 if portrait else 0.05))
    sub_size = int(title_size * 0.42)
    title_y = int(height * (0.16 if portrait else 0.12))
    chains = [
        f"gradients=s={width}x{height}:r={FPS}:d={duration:.2f}:c0={colours['c0']}:c1={colours['c1']}"
        f":x0=0:y0=0:x1={width}:y1={height}:speed=0.008,format=yuv420p[bg]",
        f"[0:a]{viz},format=rgba,{_tint(colours['viz'])},split[vz1][vz2]",
        "[vz2]gblur=sigma=12,colorchannelmixer=aa=0.85[glow]",
        f"[bg][glow]overlay=x={viz_x}:y={viz_y}[b1]",
        f"[b1][vz1]overlay=x={viz_x}:y={viz_y}[b2]",
        f"color=c={colours['accent']}@0.9:s={width}x{max(4, height // 180)}:r={FPS}[bar]",
        f"[b2][bar]overlay=x='-w+w*t/{duration:.2f}':y=H-h:shortest=1[b3]",
    ]
    last = "b3"
    if title:
        chains.append(
            f"[{last}]drawtext=fontfile='{bold}':textfile='{text_file('title.txt', title)}':fontsize={title_size}"
            f":fontcolor=white:x=(w-text_w)/2:y={title_y}:shadowcolor=black@0.6:shadowx=2:shadowy=2"
            f":alpha='min(1,t/1.5)'[t1]"
        )
        last = "t1"
    if subtitle:
        chains.append(
            f"[{last}]drawtext=fontfile='{regular}':textfile='{text_file('subtitle.txt', subtitle)}':fontsize={sub_size}"
            f":fontcolor={colours['viz']}:x=(w-text_w)/2:y={title_y + int(title_size * 1.35)}:alpha='min(1,max(0,(t-0.6)/1.5))'[t2]"
        )
        last = "t2"
    lyric_size = int(width * (0.05 if portrait else 0.032))
    lyric_y = int(height * (0.80 if portrait else 0.84))
    for index, (start, end, line) in enumerate(timeline):
        fade = "0.25"
        alpha = f"if(lt(t,{start}+{fade}),(t-{start})/{fade},if(gt(t,{end}-{fade}),({end}-t)/{fade},1))"
        chains.append(
            f"[{last}]drawtext=fontfile='{regular}':textfile='{text_file(f'l{index:03d}.txt', line)}':fontsize={lyric_size}"
            f":fontcolor=white:box=1:boxcolor=black@0.35:boxborderw={lyric_size // 3}:x=(w-text_w)/2:y={lyric_y}"
            f":enable='between(t,{start},{end})':alpha='{alpha}'[l{index}]"
        )
        last = f"l{index}"
    chains.append(f"[{last}]format=yuv420p[vout]")
    return ";\n".join(chains)


def render_visualizer(
    *, audio: Path, output_dir: Path, ffmpeg: str, title: str = "", subtitle: str = "", lyrics: str = "",
    style: str = "spectrum", palette: str = "neon", show_lyrics: bool = False, formats: tuple[str, ...] = ("16x9", "9x16"),
) -> dict:
    if style not in STYLES:
        raise VisualizerError(f"Unknown style {style}")
    if palette not in PALETTES:
        raise VisualizerError(f"Unknown palette {palette}")
    duration = probe_duration(audio)
    timeline = lyric_timeline(lyrics, duration) if show_lyrics else []
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for aspect in formats:
        width, height = FORMATS[aspect]
        workdir = output_dir / f".viz-{aspect}"
        workdir.mkdir(exist_ok=True)
        script = workdir / "graph.txt"
        script.write_text(build_filter_script(workdir=workdir, width=width, height=height, duration=duration, style=style,
                                              palette=palette, title=title, subtitle=subtitle, timeline=timeline),
                          encoding="utf-8", newline="\n")
        target = output_dir / f"music-video-{aspect}.mp4"
        command = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(audio),
            "-filter_complex_script", str(script), "-map", "[vout]", "-map", "0:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-t", f"{duration:.2f}", "-movflags", "+faststart", str(target),
        ]
        completed = subprocess.run(
            command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=max(600, int(duration * 20)), creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if completed.returncode != 0 or not target.is_file():
            raise VisualizerError(f"FFmpeg visualizer failed: {completed.stderr.strip()[-400:]}")
        for leftover in workdir.iterdir():
            leftover.unlink()
        workdir.rmdir()
        outputs[aspect] = target.name
    return {"formats": list(outputs), "duration_seconds": round(duration, 2), "mode": "visualizer", "style": style,
            "palette": palette, "lyrics_on_screen": bool(timeline), "lyrics_timing": "approximate" if timeline else None}
