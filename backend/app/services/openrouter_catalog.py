"""Public OpenRouter model catalog (no key needed) for one-click setup with live prices.

A person connecting OpenRouter should only have to paste a key: we offer the
newest model of each relevant family (picked by the catalog's ``created`` date,
so the list stays current without code changes) and fill in its real
per-token prices for the budget guard.
"""

from __future__ import annotations

import re
import time

import httpx

CATALOG_URL = "https://openrouter.ai/api/v1/models"
# (group, family label, include pattern). The newest matching model per family is offered.
FAMILIES = (
    ("OpenAI", "GPT Luna (евтин, бърз)", r"^openai/gpt-[\d.]+-luna$"),
    ("OpenAI", "GPT Sol (по-силен)", r"^openai/gpt-[\d.]+-sol$"),
    ("Google Gemini", "Gemini Flash (евтин)", r"^google/gemini-[\d.]+-flash$"),
    ("Google Gemini", "Gemini Flash Lite (най-евтин)", r"^google/gemini-[\d.]+-flash-lite$"),
    ("Google Gemini", "Gemini (най-нов)", r"^google/gemini-\d+(\.\d+)?-[a-z]+$"),
    ("Anthropic Claude", "Claude Haiku (евтин, добър български)", r"^anthropic/claude-haiku-[\d.]+$"),
    ("Anthropic Claude", "Claude Sonnet (високо качество)", r"^anthropic/claude-sonnet-[\d.]+$"),
    ("Китайски", "Qwen Flash", r"^qwen/qwen[\d.]+-flash$"),
    ("Китайски", "Qwen Max", r"^qwen/qwen[\d.]+-max$"),
    ("Китайски", "DeepSeek Flash", r"^deepseek/deepseek-v[\d.]+-flash(-\d{4})?$"),
    ("Китайски", "Kimi (Moonshot)", r"^moonshotai/kimi-k[\d.]+(-pro)?$"),
    ("Китайски", "GLM (Zhipu)", r"^z-ai/glm-[\d.]+(-flash)?$"),
    ("Китайски", "MiniMax", r"^minimax/minimax-m[\d.]+(-flash)?$"),
    ("Европейски", "Mistral Large", r"^mistralai/mistral-large-[\d-]+$"),
    ("Европейски", "Mistral Medium", r"^mistralai/mistral-medium-[\d-]+$"),
)
_EXCLUDE = re.compile(r"(image|vision|omni|embed|audio|tts|legal|code|preview|exp|nano|banana)", re.I)
_cache: dict = {"at": 0.0, "models": {}}


def _per_million(value) -> float:
    try:
        return round(float(value) * 1_000_000, 4)
    except (TypeError, ValueError):
        return 0.0


def catalog(timeout: float = 15) -> dict[str, dict]:
    """{model id: {name, created, input_usd_per_1m, output_usd_per_1m}}; cached for 6 hours."""
    if _cache["models"] and time.time() - _cache["at"] < 6 * 3600:
        return _cache["models"]
    response = httpx.get(CATALOG_URL, timeout=timeout)
    response.raise_for_status()
    models = {}
    for item in response.json().get("data", []):
        pricing = item.get("pricing") or {}
        models[item["id"]] = {"name": item.get("name") or item["id"], "created": int(item.get("created") or 0),
                              "input_usd_per_1m": _per_million(pricing.get("prompt")),
                              "output_usd_per_1m": _per_million(pricing.get("completion"))}
    _cache.update(at=time.time(), models=models)
    return models


def newest_per_family(models: dict[str, dict]) -> list[dict]:
    out, seen = [], set()
    for group, label, pattern in FAMILIES:
        regex = re.compile(pattern)
        candidates = [(model_id, info) for model_id, info in models.items()
                      if regex.match(model_id) and not _EXCLUDE.search(model_id) and model_id not in seen
                      and info["output_usd_per_1m"] > 0]
        if not candidates:
            continue
        model_id, info = max(candidates, key=lambda item: item[1]["created"])
        seen.add(model_id)
        # A song text is ~600 input + ~1500 output tokens.
        per_song = (600 * info["input_usd_per_1m"] + 1500 * info["output_usd_per_1m"]) / 1_000_000
        out.append({"id": model_id, "group": group, "label": f"{label}: {info['name'].split(':')[-1].strip()}",
                    **info, "usd_per_lyrics": round(per_song, 5)})
    return out


def recommended() -> list[dict]:
    return newest_per_family(catalog())


def price(model_id: str) -> dict | None:
    return catalog().get(model_id)


def check_key(api_key: str, timeout: float = 15) -> dict:
    """Validate a key with OpenRouter's free /key endpoint. Returns {ok, label, limit_remaining} or {ok: False}."""
    try:
        response = httpx.get("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
    except httpx.HTTPError:
        return {"ok": None, "reason": "network"}
    if response.status_code in {401, 403}:
        return {"ok": False, "reason": "invalid"}
    if response.status_code >= 400:
        return {"ok": None, "reason": f"http_{response.status_code}"}
    data = (response.json() or {}).get("data") or {}
    return {"ok": True, "limit_remaining": data.get("limit_remaining"), "usage": data.get("usage"), "is_free_tier": data.get("is_free_tier")}
