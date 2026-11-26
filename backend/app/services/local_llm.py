"""Find and switch on a local Ollama model for lyrics, so a fresh install can write
text without any cloud key.

Ollama exposes ``/api/tags`` next to its OpenAI-compatible ``/v1`` endpoint. We
prefer instruction models that handle Bulgarian reasonably (Qwen 2.5 7B, then
3B), skip embedding/coder models, and pick the largest that fits the free RAM
at the moment of the request.
"""

from __future__ import annotations

import logging

import httpx
import psutil

from app.config import Settings

logger = logging.getLogger("meloforge.local_llm")
PREFERRED = ("qwen2.5:7b", "qwen2.5:14b", "qwen3:8b", "llama3.1:8b", "gemma2:9b", "qwen2.5:3b", "llama3.2:3b", "qwen3:4b")
_SKIP = ("embed", "coder", "code", "vision", "whisper")


def _tags_url(base_url: str) -> str:
    root = base_url.rstrip("/")
    return (root[:-3] if root.endswith("/v1") else root) + "/api/tags"


def list_models(base_url: str, timeout: float = 2.5) -> list[dict] | None:
    """Installed Ollama models [{name, size_gb}] or None when Ollama is not running."""
    try:
        response = httpx.get(_tags_url(base_url), timeout=timeout)
        response.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return None
    models = []
    for item in response.json().get("models", []):
        name = item.get("name") or item.get("model") or ""
        if not name or any(word in name.lower() for word in _SKIP):
            continue
        models.append({"name": name, "size_gb": round((item.get("size") or 0) / 1024**3, 1)})
    return models


def pick_model(models: list[dict], free_ram_gb: float | None = None) -> str | None:
    """Best preferred model that fits in RAM (size + 0.8 GB headroom); else the smallest preferred one."""
    if not models:
        return None
    by_name = {m["name"]: m for m in models}
    ranked = [by_name[name] for name in PREFERRED if name in by_name] or sorted(models, key=lambda m: -m["size_gb"])
    if free_ram_gb is not None:
        fitting = [m for m in ranked if m["size_gb"] + 0.8 <= free_ram_gb]
        if fitting:
            return fitting[0]["name"]
        return min(ranked, key=lambda m: m["size_gb"])["name"]
    return ranked[0]["name"]


def free_ram_gb() -> float:
    return round(psutil.virtual_memory().available / 1024**3, 2)


def cloud_configured(settings: Settings) -> bool:
    return any(key and model for key, model in (
        (settings.openrouter_api_key, settings.openrouter_model), (settings.novita_api_key, settings.novita_model),
        (settings.nvidia_api_key, settings.nvidia_model), (settings.hf_token, settings.hf_model)))


def auto_enable(settings: Settings) -> str | None:
    """Switch on Ollama when no text model is usable at all. Returns the model or None."""
    if settings.local_llm_enabled and settings.local_llm_model:
        return settings.local_llm_model
    if cloud_configured(settings):
        return None
    models = list_models(settings.local_llm_base_url)
    model = pick_model(models or [], None)
    if model:
        settings.local_llm_enabled = True
        settings.local_llm_model = model
        logger.info("Ollama auto-enabled for lyrics with %s", model)
    return model


def status(settings: Settings) -> dict:
    models = list_models(settings.local_llm_base_url)
    local_ready = bool(settings.local_llm_enabled and settings.local_llm_model and models is not None)
    return {
        "ready": local_ready or cloud_configured(settings),
        "local": {"running": models is not None, "enabled": settings.local_llm_enabled, "model": settings.local_llm_model,
                  "models": [m["name"] for m in models or []], "suggested": pick_model(models or [], free_ram_gb())},
        "cloud_configured": cloud_configured(settings),
        "free_ram_gb": free_ram_gb(),
    }


def _root(base_url: str) -> str:
    root = base_url.rstrip("/")
    return root[:-3] if root.endswith("/v1") else root


def unload_all(base_url: str, timeout: float = 10) -> list[str]:
    """Free the GPU: ask Ollama to unload every loaded model now (keep_alive=0).

    Ollama keeps a model in VRAM for 5 minutes after a request; on a 4 GB card that
    pushes ACE-Step's VAE decode to the CPU and a 1-minute song takes 20+ minutes.
    """
    try:
        loaded = httpx.get(_root(base_url) + "/api/ps", timeout=timeout).json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return []
    unloaded = []
    for item in loaded:
        name = item.get("name") or item.get("model")
        if not name:
            continue
        try:
            httpx.post(_root(base_url) + "/api/generate", json={"model": name, "keep_alive": 0}, timeout=timeout)
            unloaded.append(name)
        except httpx.HTTPError:
            continue
    if unloaded:
        logger.info("Unloaded Ollama models from VRAM: %s", ", ".join(unloaded))
    return unloaded
