"""Small, local-only persistence layer for non-secret studio preferences."""

import json
import os
from pathlib import Path
from typing import Any

from app.config import Settings


_ALLOWED_FIELDS = {"default_mode", "max_task_budget_usd", "allow_cloud_fallback"}
_PROVIDER_FIELDS = {
    "openrouter": {"openrouter_model", "openrouter_input_usd_per_1m", "openrouter_output_usd_per_1m"},
    "novita": {"novita_model", "novita_input_usd_per_1m", "novita_output_usd_per_1m", "novita_video_cost_per_second_usd"},
    "nvidia": {"nvidia_model", "nvidia_input_usd_per_1m", "nvidia_output_usd_per_1m"},
    "huggingface": {"hf_model", "hf_input_usd_per_1m", "hf_output_usd_per_1m"},
    "ace_step": {"ace_step_enabled", "ace_step_base_url", "ace_step_model", "ace_step_cost_per_second_usd"},
}


def _settings_file() -> Path:
    data_root = Path(os.environ.get("MELOFORGE_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    return data_root / "runtime-settings.json"


def load_runtime_preferences(settings: Settings) -> None:
    path = _settings_file()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stored = {}
    if isinstance(stored, dict):
        for key, value in stored.items():
            if key in _ALLOWED_FIELDS:
                setattr(settings, key, value)
    load_provider_preferences(settings)


def _provider_settings_file() -> Path:
    data_root = Path(os.environ.get("MELOFORGE_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    return data_root / "provider-settings.json"


def load_provider_preferences(settings: Settings) -> None:
    try:
        stored = json.loads(_provider_settings_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(stored, dict):
        return
    for provider, values in stored.items():
        allowed = _PROVIDER_FIELDS.get(provider)
        if not allowed or not isinstance(values, dict):
            continue
        for key, value in values.items():
            if key in allowed:
                setattr(settings, key, value)


def public_runtime_preferences(settings: Settings) -> dict[str, Any]:
    return {
        "default_mode": settings.default_mode,
        "max_task_budget_usd": settings.max_task_budget_usd,
        "allow_cloud_fallback": settings.allow_cloud_fallback,
    }


def update_runtime_preferences(settings: Settings, values: dict[str, Any]) -> dict[str, Any]:
    updated = {key: value for key, value in values.items() if key in _ALLOWED_FIELDS and value is not None}
    for key, value in updated.items():
        setattr(settings, key, value)
    path = _settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(public_runtime_preferences(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    return public_runtime_preferences(settings)


def update_provider_preferences(settings: Settings, provider: str, values: dict[str, Any]) -> None:
    allowed = _PROVIDER_FIELDS.get(provider)
    if not allowed:
        raise ValueError("Unsupported provider")
    safe_values = {key: value for key, value in values.items() if key in allowed and value is not None}
    for key, value in safe_values.items():
        setattr(settings, key, value)
    path = _provider_settings_file()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    stored[provider] = {**stored.get(provider, {}), **safe_values}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
