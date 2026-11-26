"""Public OpenRouter model catalog (no key needed) for one-click setup with live prices.

A person connecting OpenRouter should only have to paste a key: we preselect a
cheap model that writes good Bulgarian and fill in its real per-token prices,
so the budget guard has what it needs.
"""

from __future__ import annotations

import time

import httpx

CATALOG_URL = "https://openrouter.ai/api/v1/models"
# Cheap, strong multilingual writers, best first. Only those present in the live catalog are offered.
RECOMMENDED = (
    ("anthropic/claude-haiku-5.5", "Claude Haiku 5.5 — най-добър български за цената"),
    ("google/gemini-3.7-flash", "Gemini 3.7 Flash — бърз и евтин"),
    ("openai/gpt-5-mini", "GPT-5 mini"),
    ("deepseek/deepseek-chat-v3.1", "DeepSeek Chat v3.1 — най-евтин"),
    ("anthropic/claude-sonnet-5.5", "Claude Sonnet 5.5 — най-високо качество, по-скъп"),
)
_cache: dict = {"at": 0.0, "models": {}}


def _per_million(value) -> float:
    try:
        return round(float(value) * 1_000_000, 4)
    except (TypeError, ValueError):
        return 0.0


def catalog(timeout: float = 15) -> dict[str, dict]:
    """{model id: {name, input_usd_per_1m, output_usd_per_1m}}; cached for 6 hours."""
    if _cache["models"] and time.time() - _cache["at"] < 6 * 3600:
        return _cache["models"]
    response = httpx.get(CATALOG_URL, timeout=timeout)
    response.raise_for_status()
    models = {}
    for item in response.json().get("data", []):
        pricing = item.get("pricing") or {}
        models[item["id"]] = {"name": item.get("name") or item["id"], "input_usd_per_1m": _per_million(pricing.get("prompt")),
                              "output_usd_per_1m": _per_million(pricing.get("completion"))}
    _cache.update(at=time.time(), models=models)
    return models


def recommended() -> list[dict]:
    models = catalog()
    out = []
    for model_id, label in RECOMMENDED:
        if model_id in models:
            info = models[model_id]
            # A song text is ~600 input + ~1500 output tokens.
            per_song = (600 * info["input_usd_per_1m"] + 1500 * info["output_usd_per_1m"]) / 1_000_000
            out.append({"id": model_id, "label": label, **info, "usd_per_lyrics": round(per_song, 5)})
    return out


def price(model_id: str) -> dict | None:
    return catalog().get(model_id)
