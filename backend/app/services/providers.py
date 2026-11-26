from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str
    api_key: str
    model: str
    input_usd_per_1m: float
    output_usd_per_1m: float
    kind: str = "cloud"


def provider_specs(settings: Settings) -> dict[str, ProviderSpec]:
    return {
        "ollama": ProviderSpec("ollama", settings.local_llm_base_url, "ollama", settings.local_llm_model, 0, 0, "local"),
        "openrouter": ProviderSpec("openrouter", "https://openrouter.ai/api/v1", settings.openrouter_api_key, settings.openrouter_model, settings.openrouter_input_usd_per_1m, settings.openrouter_output_usd_per_1m),
        "novita": ProviderSpec("novita", "https://api.novita.ai/openai", settings.novita_api_key, settings.novita_model, settings.novita_input_usd_per_1m, settings.novita_output_usd_per_1m),
        "nvidia": ProviderSpec("nvidia", "https://integrate.api.nvidia.com/v1", settings.nvidia_api_key, settings.nvidia_model, settings.nvidia_input_usd_per_1m, settings.nvidia_output_usd_per_1m),
        "huggingface": ProviderSpec("huggingface", "https://router.huggingface.co/v1", settings.hf_token, settings.hf_model, settings.hf_input_usd_per_1m, settings.hf_output_usd_per_1m),
    }


def public_provider_status(settings: Settings) -> list[dict[str, Any]]:
    specs = provider_specs(settings)
    descriptions = {
        "ollama": "Local LLM via Ollama / OpenAI-compatible endpoint",
        "openrouter": "Multi-provider LLM routing",
        "novita": "OpenAI-compatible LLM API; separate async video API",
        "nvidia": "NVIDIA NIM hosted LLM API",
        "huggingface": "Inference Providers chat endpoint and task-specific clients",
    }
    labels = {"ollama": "Ollama", "openrouter": "OpenRouter", "novita": "Novita", "nvidia": "NVIDIA", "huggingface": "Hugging Face"}
    return [
        {
            "id": key,
            "name": labels[key],
            "description": descriptions[key],
            "configured": bool(spec.api_key and spec.model) if spec.kind == "cloud" else bool(settings.local_llm_enabled and spec.model),
            "model": spec.model or None,
            "pricing_configured": spec.kind == "local" or (spec.input_usd_per_1m > 0 and spec.output_usd_per_1m > 0),
            "input_usd_per_1m": spec.input_usd_per_1m,
            "output_usd_per_1m": spec.output_usd_per_1m,
            "video_cost_per_second_usd": settings.novita_video_cost_per_second_usd if key == "novita" else None,
            "kind": spec.kind,
        }
        for key, spec in specs.items()
    ]


async def create_chat_completion(spec: ProviderSpec, messages: list[dict[str, str]], max_tokens: int) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {spec.api_key}", "Content-Type": "application/json"}
    if spec.name == "openrouter":
        headers["X-Title"] = "MeloForge Studio"
    payload = {"model": spec.model, "messages": messages, "max_tokens": max_tokens, "stream": False}
    # Local models on a laptop CPU/GPU can need several minutes for a full song text.
    read_timeout = 420.0 if spec.kind == "local" else 120.0
    async with httpx.AsyncClient(timeout=httpx.Timeout(read_timeout, connect=15.0)) as client:
        response = await client.post(f"{spec.base_url.rstrip('/')}/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("Provider returned no choices")
    message = choices[0].get("message") or {}
    return {"content": message.get("content") or "", "usage": data.get("usage") or {}, "provider_response_id": data.get("id")}


async def novita_create_video(settings: Settings, request_data: dict) -> dict:
    if not settings.novita_api_key:
        raise ValueError("NOVITA_API_KEY is not configured")
    body = {
        "input": {"prompt": request_data["prompt"], "negative_prompt": request_data.get("negative_prompt", "")},
        "parameters": {"size": request_data["size"], "duration": request_data["duration"], "prompt_extend": True},
    }
    if request_data.get("seed") is not None:
        body["parameters"]["seed"] = request_data["seed"]
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post("https://api.novita.ai/v3/async/wan-2.2-t2v", headers={"Authorization": f"Bearer {settings.novita_api_key}"}, json=body)
        response.raise_for_status()
        return response.json()


async def novita_video_status(settings: Settings, task_id: str) -> dict:
    if not settings.novita_api_key:
        raise ValueError("NOVITA_API_KEY is not configured")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get("https://api.novita.ai/v3/async/task-result", params={"task_id": task_id}, headers={"Authorization": f"Bearer {settings.novita_api_key}"})
        response.raise_for_status()
        return response.json()
