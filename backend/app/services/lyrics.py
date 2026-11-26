"""Lyrics preparation for ACE-Step 1.5.

ACE-Step reads song structure from bracketed meta tags ([Verse], [Chorus], ...).
Untagged text still renders, but sections blur together, so plain lyrics are
structured here before submission. Everything in this module is deterministic
and offline.
"""

from __future__ import annotations

import re

_TAG = re.compile(r"^\s*\[[^\]\n]{1,60}\]\s*$", re.M)
# Typical sung delivery is ~2-3 words per second in a pop arrangement once
# instrumental intro/outro and breaths are included.
_MAX_WORDS_PER_SECOND = 2.6
_MIN_WORDS_PER_SECOND = 0.6

LANGUAGE_NAMES = {"bg": "Bulgarian", "en": "English"}


def has_structure_tags(lyrics: str) -> bool:
    return bool(_TAG.search(lyrics))


def _paragraphs(lyrics: str) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", lyrics.strip())]
    return [block for block in blocks if block]


def _normalise(block: str) -> str:
    return re.sub(r"\W+", " ", block.lower()).strip()


def structure_lyrics(lyrics: str) -> str:
    """Add [Verse]/[Chorus] tags to plain lyrics. Tagged lyrics are returned unchanged.

    A paragraph that appears more than once is treated as the chorus; the rest
    become numbered verses. A single paragraph becomes one verse.
    """
    text = lyrics.strip()
    if not text or has_structure_tags(text):
        return text
    blocks = _paragraphs(text)
    counts: dict[str, int] = {}
    for block in blocks:
        counts[_normalise(block)] = counts.get(_normalise(block), 0) + 1
    out: list[str] = []
    verse = 0
    for block in blocks:
        if counts[_normalise(block)] > 1:
            out.append(f"[Chorus]\n{block}")
        else:
            verse += 1
            out.append(f"[Verse {verse}]\n{block}" if len(blocks) > 1 else f"[Verse]\n{block}")
    return "\n\n".join(out)


def sung_word_count(lyrics: str) -> int:
    without_tags = _TAG.sub("", lyrics)
    return len(re.findall(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", without_tags))


def lyric_warnings(lyrics: str, duration_seconds: int) -> list[str]:
    words = sung_word_count(lyrics)
    if not words:
        return []
    warnings: list[str] = []
    if words > duration_seconds * _MAX_WORDS_PER_SECOND:
        suggested = int(words / _MAX_WORDS_PER_SECOND / 5 + 1) * 5
        warnings.append(
            f"Текстът е дълъг за {duration_seconds} сек. ({words} думи). ACE-Step може да го ускори или съкрати; "
            f"препоръчителна дължина ≈ {min(600, suggested)} сек."
        )
    elif words < duration_seconds * _MIN_WORDS_PER_SECOND and duration_seconds >= 30:
        warnings.append(
            f"Текстът е кратък за {duration_seconds} сек. ({words} думи); очаквай дълги инструментални части или повторения."
        )
    return warnings


def lyrics_writer_messages(
    *, prompt: str, genre: str, mood: str, language: str, duration_seconds: int, title: str = "",
    themes: list[str] | None = None, structure: str = "", lyric_style: str = "", story: str = "",
) -> list[dict[str, str]]:
    """Prompt for an LLM that drafts singable, ACE-Step-tagged lyrics."""
    target_words = max(20, int(duration_seconds * 1.6))
    language_name = LANGUAGE_NAMES.get(language, language)
    system = (
        "You are a professional songwriter. Write original, singable song lyrics. "
        "Use ACE-Step section tags on their own lines: [Intro], [Verse 1], [Pre-Chorus], [Chorus], "
        "[Verse 2], [Bridge], [Outro]. Keep lines short (4-9 syllables per line is ideal), "
        "use consistent meter and rhyme, repeat the chorus verbatim. "
        "First line: 'Title: <a short song title, 1-5 words, in the lyrics language>'. "
        "Second line: 'Style: <the sound for the music engine as short ENGLISH comma-separated tags, max 35 words: "
        "genre, key instruments, vocal type, tempo/energy; translate any non-English style wishes>'. "
        "Turn wishes about the song's shape (calm start, wild middle, brass ending, a rapped or shouted line, "
        "an extra pre-chorus) into the section structure and short tag hints such as [Intro - calm accordion] "
        "or [Outro - festive brass]; put shouted or chanted phrases into the lyrics where they belong. "
        "Then ONLY the lyrics with tags: no explanations, no markdown."
    )
    user = (
        f"Language: {language_name} (write every sung line in {language_name}).\n"
        f"Song idea: {prompt}\n"
        f"Genre: {genre or 'any'}\nMood: {mood or 'any'}\n"
        f"Title: {title or 'none'}\n"
        f"Target length: about {duration_seconds} seconds, roughly {target_words} sung words in total."
    )
    if story:
        user += ("\nWhat the song must be about (from the person ordering it; follow it closely, keep names, "
                 f"places and details they mention): {story}")
    if themes:
        user += "\nCurrent trending themes in this genre (use as inspiration, stay original): " + "; ".join(themes)
    if structure:
        user += f"\nSection order: {structure}"
    if lyric_style:
        user += f"\nLyric style: {lyric_style}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def extract_title(text: str) -> str:
    """The 'Title: …' line the writer is asked to put first (empty when missing)."""
    for line in text.splitlines()[:6]:
        match = re.match(r"^\W*(?:title|заглавие)\s*:\s*(.+?)\W*$", line.strip(), re.I)
        if match:
            return match.group(1).strip().strip('"„“”«»')[:80]
    return ""


def extract_style(text: str) -> str:
    """The 'Style: …' line with English ACE-Step tags (empty when missing)."""
    for line in text.splitlines()[:8]:
        match = re.match(r"^\W*(?:style|стил)\s*:\s*(.+?)\s*$", line.strip(), re.I)
        if match:
            return match.group(1).strip().strip('"')[:400]
    return ""


def clean_generated_lyrics(text: str) -> str:
    """Strip markdown fences, headings and chatter that LLMs sometimes add."""
    cleaned = re.sub(r"```[a-z]*", "", text).replace("```", "")
    lines = []
    for line in cleaned.splitlines():
        stripped = line.strip().strip("*_").strip()
        if re.match(r"^(title|заглавие|style|стил)\s*:", stripped, re.I) or stripped.startswith("#"):
            continue
        lines.append(stripped)
    # One blank line before every section tag keeps the text readable and editable.
    result = re.sub(r"\n*(^\[[^\]\n]{1,60}\]\s*$)", r"\n\n\1", "\n".join(lines), flags=re.MULTILINE)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return structure_lyrics(result)
