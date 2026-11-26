"""ACE-Step 1.5 async API adapter.

The connector only submits work after a user confirmed a server-side quote.
"""

import json
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx


@dataclass(frozen=True)
class AceStepConfig:
    base_url: str
    enabled: bool = False
    api_key: str = ""


def _headers(config: AceStepConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


async def list_models(config: AceStepConfig) -> dict:
    if not config.enabled or not config.base_url:
        raise RuntimeError("ACE-Step is not configured")
    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
        response = await client.get(f"{config.base_url.rstrip('/')}/v1/models", headers=_headers(config))
        response.raise_for_status()
        return response.json()


async def submit_song(config: AceStepConfig, payload: dict) -> dict:
    if not config.enabled or not config.base_url:
        raise RuntimeError("ACE-Step is not configured")
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=8.0)) as client:
        response = await client.post(f"{config.base_url.rstrip('/')}/release_task", headers=_headers(config), json=payload)
        response.raise_for_status()
        body = response.json()
    data = body.get("data") or {}
    task_id = data.get("task_id") or body.get("task_id")
    if not task_id:
        raise ValueError("ACE-Step returned no task_id")
    return {"task_id": str(task_id), "provider_response": body}


async def song_status(config: AceStepConfig, task_id: str) -> dict:
    if not config.enabled or not config.base_url:
        raise RuntimeError("ACE-Step is not configured")
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0)) as client:
        response = await client.post(
            f"{config.base_url.rstrip('/')}/query_result",
            headers=_headers(config),
            json={"task_id_list": [task_id]},
        )
        response.raise_for_status()
        body = response.json()
    entries = body.get("data") or []
    task = next((item for item in entries if str(item.get("task_id")) == task_id), None)
    if task is None:
        raise ValueError("ACE-Step task was not found")
    result = task.get("result") or []
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            result = []
    if isinstance(result, dict):
        result = [result]
    first = result[0] if isinstance(result, list) and result and isinstance(result[0], dict) else {}
    file_value = first.get("file") or first.get("audio_url")
    audio_url = None
    if isinstance(file_value, str) and file_value:
        audio_url = file_value if file_value.startswith(("http://", "https://")) else urljoin(f"{config.base_url.rstrip('/')}/", file_value.lstrip("/"))
    return {
        "status": int(task.get("status", 0)),
        "audio_url": audio_url,
        "lyrics": first.get("lyrics") or "",
        "metadata": first.get("metas") or {},
        "provider_result": first,
        "progress": float(first.get("progress") or 0.0),
        "stage": first.get("stage") or "",
    }
