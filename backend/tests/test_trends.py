import asyncio
from datetime import date

import pytest
from fastapi import HTTPException

from app import main
from app.schemas import LyricsDraftRequest, TrendRequest
from app.services import jobs, trends
from app.services.lyrics import lyrics_writer_messages
from app.services.trends import GENRES, ChartTrack


def _tracks():
    return [
        ChartTrack(1, "A", "Artist One", 200, "2026-11-01", 120.0, False),
        ChartTrack(2, "B", "Artist Two", 180, "2026-03-01", None, True),
        ChartTrack(3, "C", "Artist One", 220, "2024-01-01", 124.0, False),
    ]


def test_chart_stats_summarise_length_tempo_and_recency():
    stats = trends.chart_stats(_tracks(), today=date(2026, 11, 25))
    assert stats["median_duration_seconds"] == 200
    assert stats["median_bpm"] == 122 and stats["bpm_samples"] == 2
    assert stats["released_last_90_days_pct"] == 33
    assert stats["released_last_year_pct"] == 67
    assert stats["explicit_pct"] == 33
    assert stats["repeat_artists"] == ["Artist One"]


def test_default_brief_ignores_implausible_chart_bpm():
    pop = GENRES["pop"]
    assert trends.default_brief(pop, {"median_bpm": 150, "median_duration_seconds": 208})["bpm"] == 110
    brief = trends.default_brief(pop, {"median_bpm": 104, "median_duration_seconds": 208})
    assert brief["bpm"] == 104 and brief["duration_seconds"] == 210


def test_llm_brief_is_parsed_and_clamped():
    fallback = trends.default_brief(GENRES["dance"], {})
    text = 'Sure!\n```json\n{"caption": "dance pop, sidechain", "bpm": 999, "duration_seconds": 187, "themes": ["нощ", "свобода"], "summary": "Кратко."}\n```'
    brief = trends.parse_brief(text, fallback)
    assert brief["caption"] == "dance pop, sidechain"
    assert brief["bpm"] == fallback["bpm"]  # 999 rejected
    assert brief["duration_seconds"] == 185
    assert brief["themes"] == ["нощ", "свобода"] and brief["source"] == "llm"
    assert trends.parse_brief("no json here", fallback) == fallback


def test_analysis_prompt_forbids_artist_names_in_caption():
    messages = trends.analysis_messages(GENRES["pop"], _tracks(), {}, "bg")
    assert "NEVER mention artist" in messages[0]["content"]
    assert "Artist One — A" in messages[1]["content"]


def test_trend_endpoint_uses_cache_and_falls_back_without_llm(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    monkeypatch.setattr(main.settings, "local_llm_enabled", False)
    monkeypatch.setattr(main.settings, "openrouter_api_key", "")
    calls = []

    async def chart(genre, limit=25):
        calls.append(genre.id)
        return _tracks()

    monkeypatch.setattr(main, "fetch_chart", chart)
    first = asyncio.run(main.music_trends(TrendRequest(genre="pop")))
    second = asyncio.run(main.music_trends(TrendRequest(genre="pop", analyze=False)))
    assert calls == ["pop"]  # second call served from cache
    assert first["brief"]["source"] == "preset"
    assert first["analysis"]["used_llm"] is False and first["analysis"]["note"]
    assert second["stats"]["tracks"] == 3
    with pytest.raises(HTTPException):
        asyncio.run(main.music_trends(TrendRequest(genre="unknown")))


def test_lyrics_prompt_includes_trend_brief():
    request = LyricsDraftRequest(prompt="лято", themes=["море", "приятели"], structure="[Verse 1] [Chorus]", lyric_style="short lines")
    messages = lyrics_writer_messages(prompt=request.prompt, genre="pop", mood="", language="bg", duration_seconds=90,
                                      themes=request.themes, structure=request.structure, lyric_style=request.lyric_style)
    assert "море; приятели" in messages[1]["content"]
    assert "Section order: [Verse 1] [Chorus]" in messages[1]["content"]


def test_freshness_note_flags_charts_full_of_old_hits():
    assert trends.freshness_notes({"released_last_year_pct": 4, "bpm_samples": 19})
    assert trends.freshness_notes({"released_last_year_pct": 60, "bpm_samples": 19}) == []
