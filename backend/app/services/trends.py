"""Genre presets and chart-trend analysis.

Chart data comes from Deezer's public API (no key; charts reflect the caller's
region). Only metadata is used — titles, artists, rank, length, release date and
BPM when Deezer has it. No lyrics or audio of existing songs are fetched, and the
generated ACE-Step caption never names artists: the goal is to follow current
trends, not to imitate specific works.
"""

from __future__ import annotations

import asyncio
import json
import re
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

import httpx

DEEZER = "https://api.deezer.com"
CACHE_SECONDS = 6 * 3600


@dataclass(frozen=True)
class GenrePreset:
    id: str
    label: str
    deezer_id: int
    caption: str
    bpm: tuple[int, int]
    mood: str


GENRES: dict[str, GenrePreset] = {g.id: g for g in [
    GenrePreset("pop", "Поп", 132, "modern pop, polished production, catchy hook, bright synths, tight drums, clear lead vocal", (95, 125), "uplifting, catchy"),
    GenrePreset("dance", "Денс / EDM", 113, "dance pop, four-on-the-floor kick, sidechained synth chords, big build-up and drop, energetic vocal", (118, 130), "euphoric, energetic"),
    GenrePreset("hiphop", "Хип-хоп / Рап", 116, "modern hip hop, 808 bass, crisp trap hi-hats, sparse dark piano, confident rap vocal", (80, 150), "confident, gritty"),
    GenrePreset("rnb", "R&B", 165, "contemporary r&b, smooth electric piano, deep sub bass, laid-back groove, silky vocal harmonies", (65, 100), "sensual, intimate"),
    GenrePreset("rock", "Рок", 152, "modern rock, driving electric guitars, live drums, bass guitar, powerful vocal", (100, 150), "energetic, raw"),
    GenrePreset("alternative", "Алтернативна / Инди", 85, "indie alternative, jangly guitars, warm analog textures, airy vocal, dynamic chorus", (90, 130), "bittersweet, dreamy"),
    GenrePreset("electronic", "Електронна", 106, "electronic, analog synthesizers, arpeggiated sequences, deep bass, atmospheric pads", (110, 128), "hypnotic, atmospheric"),
    GenrePreset("synthwave", "Synthwave", 106, "synthwave, retro 80s analog synths, gated reverb drums, pulsing bass, nostalgic lead", (95, 118), "nostalgic, cinematic"),
    GenrePreset("folk", "Фолк / Акустична", 466, "acoustic folk, fingerpicked guitar, warm upright bass, soft percussion, intimate vocal", (80, 115), "warm, heartfelt"),
    GenrePreset("balkan", "Балкан поп / Поп-фолк", 132, "balkan pop, oriental melodic hooks, clarinet and accordion riffs, punchy dance beat, passionate vocal", (95, 130), "passionate, festive"),
    GenrePreset("latin", "Латино", 197, "latin pop, reggaeton dembow rhythm, nylon guitar, warm bass, sensual vocal", (88, 100), "sensual, sunny"),
    GenrePreset("country", "Кънтри", 84, "modern country, acoustic and electric guitars, pedal steel, steady backbeat, storytelling vocal", (75, 120), "honest, warm"),
    GenrePreset("metal", "Метъл", 464, "heavy metal, distorted down-tuned guitars, double kick drums, powerful bass, intense vocal", (100, 180), "aggressive, epic"),
    GenrePreset("soul", "Соул / Фънк", 169, "soul funk, slap bass, brass section, rhodes piano, tight groove, soulful vocal", (90, 115), "groovy, joyful"),
    GenrePreset("jazz", "Джаз", 129, "modern jazz, upright bass, brushed drums, piano trio, smoky vocal", (70, 140), "smooth, late-night"),
    GenrePreset("reggae", "Реге", 144, "reggae, offbeat guitar skank, deep bass, one drop drums, relaxed vocal", (70, 90), "relaxed, sunny"),
    GenrePreset("cinematic", "Филмова / Епична", 173, "cinematic orchestral, strings and brass, epic percussion, choir, piano motif", (70, 120), "epic, emotional"),
]}


@dataclass
class ChartTrack:
    rank: int
    title: str
    artist: str
    duration: int
    release_date: str | None
    bpm: float | None
    explicit: bool


def public_genres() -> list[dict]:
    return [{"id": g.id, "label": g.label, "caption": g.caption, "bpm": list(g.bpm), "mood": g.mood} for g in GENRES.values()]


def _cache_path(root: Path, genre_id: str) -> Path:
    return root / "trends" / f"{genre_id}.json"


async def _get(client: httpx.AsyncClient, path: str) -> dict:
    response = await client.get(f"{DEEZER}{path}")
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("error"):
        raise ValueError("Deezer returned an error")
    return data


async def fetch_chart(genre: GenrePreset, limit: int = 25) -> list[ChartTrack]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0), headers={"Accept-Language": "en"}) as client:
        chart = await _get(client, f"/chart/{genre.deezer_id}/tracks?limit={limit}")
        entries = chart.get("data") or []
        # Track details carry release date and (sometimes) BPM; fetch them concurrently.
        semaphore = asyncio.Semaphore(6)

        async def details(track_id):
            async with semaphore:
                try:
                    return await _get(client, f"/track/{track_id}")
                except (httpx.HTTPError, ValueError):
                    return {}

        extra = await asyncio.gather(*(details(item.get("id")) for item in entries))
    tracks = []
    for index, (item, info) in enumerate(zip(entries, extra), start=1):
        bpm = info.get("bpm") or None
        tracks.append(ChartTrack(
            rank=index,
            title=str(item.get("title") or ""),
            artist=str((item.get("artist") or {}).get("name") or ""),
            duration=int(item.get("duration") or info.get("duration") or 0),
            release_date=info.get("release_date") or None,
            bpm=float(bpm) if bpm and float(bpm) > 0 else None,
            explicit=bool(item.get("explicit_lyrics")),
        ))
    return tracks


def chart_stats(tracks: list[ChartTrack], today: date | None = None) -> dict:
    today = today or date.today()
    durations = [t.duration for t in tracks if t.duration > 0]
    bpms = [t.bpm for t in tracks if t.bpm]
    ages = []
    for t in tracks:
        try:
            ages.append((today - datetime.strptime(t.release_date or "", "%Y-%m-%d").date()).days)
        except ValueError:
            continue
    artists: dict[str, int] = {}
    for t in tracks:
        artists[t.artist] = artists.get(t.artist, 0) + 1
    return {
        "tracks": len(tracks),
        "median_duration_seconds": int(statistics.median(durations)) if durations else None,
        "median_bpm": round(statistics.median(bpms)) if bpms else None,
        "bpm_samples": len(bpms),
        "released_last_90_days_pct": round(100 * sum(a <= 90 for a in ages) / len(ages)) if ages else None,
        "released_last_year_pct": round(100 * sum(a <= 365 for a in ages) / len(ages)) if ages else None,
        "explicit_pct": round(100 * sum(t.explicit for t in tracks) / len(tracks)) if tracks else None,
        "repeat_artists": sorted([name for name, count in artists.items() if count > 1]),
    }


def freshness_notes(stats: dict) -> list[str]:
    notes = []
    recent = stats.get("released_last_year_pct")
    if recent is not None and recent < 25:
        notes.append(
            f"Само {recent}% от песните в класацията са издадени през последната година — "
            "доминират стари или сезонни хитове, затова тенденциите са с ограничена актуалност."
        )
    if stats.get("bpm_samples", 0) < 5:
        notes.append("Deezer има BPM за малко песни; темпото е по жанровия профил.")
    return notes


def default_brief(genre: GenrePreset, stats: dict) -> dict:
    """Deterministic brief from the preset and chart numbers (no LLM needed)."""
    low, high = genre.bpm
    bpm = stats.get("median_bpm")
    bpm = int(bpm) if bpm and low - 15 <= bpm <= high + 15 else (low + high) // 2
    duration = stats.get("median_duration_seconds") or 180
    return {
        "caption": genre.caption,
        "mood": genre.mood,
        "bpm": bpm,
        "duration_seconds": max(60, min(300, int(round(duration / 5) * 5))),
        "structure": "[Intro] [Verse 1] [Pre-Chorus] [Chorus] [Verse 2] [Pre-Chorus] [Chorus] [Bridge] [Chorus] [Outro]",
        "themes": [],
        "lyric_style": "short lines, a hook in the first 30 seconds, chorus repeated verbatim",
        "source": "preset",
    }


def analysis_messages(genre: GenrePreset, tracks: list[ChartTrack], stats: dict, language: str) -> list[dict[str, str]]:
    listing = "\n".join(f"{t.rank}. {t.artist} — {t.title} ({t.duration}s, {t.release_date or 'n/a'}{f', {t.bpm:.0f} BPM' if t.bpm else ''})" for t in tracks[:25])
    system = (
        "You are an A&R analyst and music producer. From a current chart you infer production and songwriting "
        "trends of the genre. Return ONLY a JSON object with keys: "
        '"caption" (English ACE-Step style prompt, max 40 words: instruments, production, vocal type, energy; '
        'NEVER mention artist or song names), "mood" (2-4 English words), "bpm" (integer), '
        '"duration_seconds" (integer), "structure" (section tags in order, e.g. "[Intro] [Verse 1] [Chorus]"), '
        '"themes" (3-5 lyric themes written in the requested language), "lyric_style" (one sentence in English), '
        '"summary" (2-3 sentences in the requested language explaining what is trending). '
        "Describe general trends only; do not copy melodies, lyrics or signature hooks of listed songs. "
        "Weight recently released songs more than old or seasonal evergreens."
    )
    user = (
        f"Genre: {genre.label} ({genre.id}). Baseline sound: {genre.caption}.\n"
        f"Chart statistics: {json.dumps(stats, ensure_ascii=False)}\n"
        f"Requested language for themes/summary: {'Bulgarian' if language == 'bg' else 'English'}\n"
        f"Current chart:\n{listing}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_brief(text: str, fallback: dict) -> dict:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return fallback
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return fallback
    brief = dict(fallback)
    if isinstance(data.get("caption"), str) and data["caption"].strip():
        brief["caption"] = data["caption"].strip()[:400]
    if isinstance(data.get("mood"), str) and data["mood"].strip():
        brief["mood"] = data["mood"].strip()[:80]
    for key, low, high in (("bpm", 40, 220), ("duration_seconds", 60, 300)):
        try:
            value = int(data.get(key))
            if low <= value <= high:
                brief[key] = value if key == "bpm" else int(round(value / 5) * 5)
        except (TypeError, ValueError):
            pass
    if isinstance(data.get("structure"), str):
        brief["structure"] = data["structure"].strip()[:300]
    if isinstance(data.get("themes"), list):
        brief["themes"] = [str(item)[:120] for item in data["themes"][:6]]
    for key in ("lyric_style", "summary"):
        if isinstance(data.get(key), str):
            brief[key] = data[key].strip()[:600]
    brief["source"] = "llm"
    return brief


def load_cached(root: Path, genre_id: str) -> dict | None:
    try:
        cached = json.loads(_cache_path(root, genre_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - cached.get("fetched_at", 0) > CACHE_SECONDS:
        return None
    return cached


def save_cache(root: Path, genre_id: str, tracks: list[ChartTrack], stats: dict) -> dict:
    payload = {"fetched_at": time.time(), "tracks": [asdict(t) for t in tracks], "stats": stats}
    path = _cache_path(root, genre_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
