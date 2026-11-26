"""Lyric timing and multi-voice arrangement (duets, choir) on top of voice conversion.

* ``transcribe_words`` runs faster-whisper (CPU int8) on the separated vocal stem.
* ``align_lyrics`` matches the known lyric lines to those words in order, so
  every line gets start/end times (``lyric_timing`` in the song package).
* ``section_spans`` turns the timed lines into time ranges per lyric section
  ([Verse 1], [Chorus] ...), which is what duet and choir assignments use.
* ``plan_layers`` builds the vocal mix: each section is sung by voice A, B,
  both together, the original AI singer, or a choir (several detuned, delayed
  and panned doublings of the available voices).
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
from pathlib import Path

from app.services.arrangement_worker import WORKER_SOURCE

PART_MODES = ("A", "B", "AB", "choir", "original")
_TAG = re.compile(r"^\s*\[([^\]\n]{1,60})\]\s*$")
_WORD = re.compile(r"[^\w']+", re.UNICODE)


class ArrangementError(RuntimeError):
    pass


def run_worker(job: dict, *, timeout: int = 3600) -> dict:
    from app.services import voice_clone

    if not voice_clone.engine_status()["installed"]:
        raise ArrangementError("Seed-VC environment is not installed")
    env = voice_clone._engine_env()
    env.pop("HF_HOME", None)  # faster-whisper models live in the normal HF cache
    completed = subprocess.run(
        [str(voice_clone.engine_python()), "-c", WORKER_SOURCE, json.dumps(job, ensure_ascii=False)],
        check=False, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        creationflags=voice_clone._flags(), env=env,
    )
    marker = "@@RESULT@@"
    if completed.returncode != 0 or marker not in completed.stdout:
        raise ArrangementError(f"worker {job.get('cmd')} failed: {(completed.stderr or completed.stdout)[-600:]}")
    return json.loads(completed.stdout.rsplit(marker, 1)[1])


# ------------------------------------------------------------------ lyric timing

def parse_lyrics(lyrics: str) -> tuple[list[dict], list[dict]]:
    """Return (sections, lines). Each line carries the index of its section."""
    sections: list[dict] = []
    lines: list[dict] = []
    for raw in (lyrics or "").splitlines():
        text = raw.strip()
        if not text:
            continue
        tag = _TAG.match(text)
        if tag:
            sections.append({"index": len(sections), "label": tag.group(1).strip()})
            continue
        if not sections:
            sections.append({"index": 0, "label": "Verse"})
        lines.append({"text": text, "section": sections[-1]["index"]})
    return sections, lines


def _norm(text: str) -> str:
    return " ".join(_WORD.sub(" ", text.lower()).split())


def transcribe_words(vocals: Path, *, language: str = "bg", cache: Path | None = None) -> list[dict]:
    if cache and cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    words = run_worker({"cmd": "words", "audio": str(vocals), "language": language})["words"]
    if cache:
        cache.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    return words


def align_lyrics(lyrics: str, words: list[dict], duration: float) -> list[dict]:
    """Sequentially match lyric lines to recognised words; interpolate the misses."""
    """Monotonic global alignment (dynamic programming): lines may be skipped by the
    singer and words may be noise, but order is kept, so a missed first chorus
    cannot steal the second one."""
    _, lines = parse_lyrics(lyrics)
    tokens = [_norm(w["word"]) for w in words]
    n_lines, n_words = len(lines), len(tokens)
    targets = [_norm(line["text"]) for line in lines]
    threshold = 0.42
    neg = float("-inf")
    # best[i][j]: max score aligning first i lines within first j words.
    best = [[neg] * (n_words + 1) for _ in range(n_lines + 1)]
    back: list[list[tuple | None]] = [[None] * (n_words + 1) for _ in range(n_lines + 1)]
    best[0] = [0.0] * (n_words + 1)
    for i in range(n_lines):
        size = max(1, len(targets[i].split()))
        for j in range(n_words + 1):
            base = best[i][j]
            if base == neg:
                continue
            if base > best[i + 1][j]:  # line not sung / not recognised
                best[i + 1][j], back[i + 1][j] = base, ("skip", j)
            for length in range(max(1, size - 2), size + 4):
                k = j + length
                if k > n_words:
                    break
                score = difflib.SequenceMatcher(None, targets[i], " ".join(tokens[j:k])).ratio()
                if score >= threshold and base + score > best[i + 1][k]:
                    best[i + 1][k], back[i + 1][k] = base + score, ("match", j, score)
        # Allow leaving words unused (noise, ad-libs) before the next line.
        for j in range(1, n_words + 1):
            if best[i + 1][j - 1] > best[i + 1][j]:
                best[i + 1][j], back[i + 1][j] = best[i + 1][j - 1], ("noise", j - 1)
    matches: dict[int, tuple[int, int, float]] = {}
    i, j = n_lines, max(range(n_words + 1), key=lambda col: best[n_lines][col])
    while i > 0:
        step = back[i][j]
        if step is None:
            break
        if step[0] == "noise":
            j = step[1]
            continue
        if step[0] == "match":
            matches[i - 1] = (step[1], j, step[2])
            j = step[1]
        i -= 1
    timed: list[dict] = []
    for index, line in enumerate(lines):
        if index in matches:
            start, end, score = matches[index]
            timed.append({**line, "start": words[start]["start"], "end": words[end - 1]["end"], "heard": True, "score": round(score, 2)})
        else:
            timed.append({**line, "start": None, "end": None, "heard": False, "score": 0.0})
    _interpolate(timed, duration)
    return timed


def _interpolate(timed: list[dict], duration: float) -> None:
    """Give unheard lines times between their heard neighbours (or the song edges)."""
    i = 0
    while i < len(timed):
        if timed[i]["heard"]:
            i += 1
            continue
        j = i
        while j < len(timed) and not timed[j]["heard"]:
            j += 1
        left = timed[i - 1]["end"] if i > 0 else duration * 0.05
        right = timed[j]["start"] if j < len(timed) else duration * 0.97
        if right <= left:
            right = left + 0.5 * (j - i)
        step = (right - left) / (j - i)
        for k in range(i, j):
            timed[k]["start"] = round(left + step * (k - i), 3)
            timed[k]["end"] = round(left + step * (k - i + 1) - min(0.1, step / 4), 3)
        i = j


def section_spans(lyrics: str, timed: list[dict], duration: float) -> list[dict]:
    """Time range of every lyric section; sections without lines borrow the gap they sit in."""
    sections, _ = parse_lyrics(lyrics)
    for section in sections:
        own = [line for line in timed if line["section"] == section["index"]]
        section["lines"] = len(own)
        section["start"] = round(max(0.0, own[0]["start"] - 0.35), 3) if own else None
        section["end"] = round(own[-1]["end"] + 0.35, 3) if own else None
    # Fill empty sections and close gaps so spans tile the song.
    previous_end = 0.0
    for idx, section in enumerate(sections):
        if section["start"] is None:
            following = next((s["start"] for s in sections[idx + 1:] if s["start"] is not None), duration)
            section["start"], section["end"] = previous_end, following
        else:
            section["start"] = max(section["start"], previous_end)
        previous_end = section["end"]
    # Tile the song: each section runs until the next one starts (instrumental gaps
    # stay with the section before them, so no sung note falls outside every span).
    for current, following in zip(sections, sections[1:]):
        current["end"] = following["start"]
    if sections:
        sections[0]["start"] = 0.0
        sections[-1]["end"] = max(sections[-1]["end"], duration)
    return sections


def lyric_timing(timed: list[dict]) -> list[dict]:
    """Contract shape for the song package."""
    return [{"start": line["start"], "end": line["end"], "text": line["text"], "heard": line["heard"]} for line in timed]


# ------------------------------------------------------------------ arrangement

def is_chorus(label: str) -> bool:
    """[Chorus], [Chorus 2], [Припев] — but not [Pre-Chorus] / [Post-Chorus]."""
    return bool(re.match(r"^\s*(chorus|припев|refrain|hook)\b", label.strip().lower()))


def default_parts(sections: list[dict], *, duet: bool) -> dict[int, str]:
    """Sensible duet: A sings odd verses, B even verses, both on choruses; choir only if asked."""
    parts = {}
    verse_count = 0
    for section in sections:
        label = section["label"].lower()
        if not section.get("lines"):
            continue
        if not duet:
            parts[section["index"]] = "A"
        elif is_chorus(section["label"]):
            parts[section["index"]] = "AB"
        elif "verse" in label or "куплет" in label:
            verse_count += 1
            parts[section["index"]] = "A" if verse_count % 2 else "B"
        else:
            parts[section["index"]] = "AB"
    return parts


def plan_layers(*, spans: list[dict], parts: dict[int, str], converted: dict[str, Path], original: Path) -> list[dict]:
    """Translate section assignments into mix layers for the worker."""
    # (voice, together) -> spans; voices singing together drop 3 dB each and spread slightly.
    segments: dict[tuple[str, bool], list[tuple[float, float]]] = {}
    choir: list[tuple[float, float]] = []
    for section in spans:
        mode = parts.get(section["index"], "A")
        span = (section["start"], section["end"])
        if mode == "choir":
            choir.append(span)
            continue
        voices = [v for v in ("A", "B") if v in converted] if mode == "AB" else [mode]
        for voice in voices:
            key = voice if voice in converted or voice == "original" else "A"
            segments.setdefault((key, len(voices) > 1), []).append(span)
    layers = []
    for (key, together), spans_for_key in segments.items():
        path = original if key == "original" else converted[key]
        pan = (-0.2 if key == "A" else 0.2) if together else 0.0
        layers.append({"path": str(path), "segments": spans_for_key, "gain_db": -3.0 if together else 0.0, "pan": pan})
    if choir:
        voices = [converted[k] for k in ("A", "B") if k in converted] + [original]
        spreads = [(0, 0, 0.0), (18, 9, -0.55), (31, -11, 0.55), (12, 14, -0.85), (25, -7, 0.85), (40, 5, 0.0)]
        for index, (delay, cents, pan) in enumerate(spreads):
            voice = voices[index % len(voices)]
            layers.append({"path": str(voice), "segments": choir, "delay_ms": delay, "cents": cents, "pan": pan,
                           "gain_db": -1.0 if index == 0 else -7.5})
    return layers
