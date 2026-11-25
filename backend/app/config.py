import os
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    default_mode: Literal["local_first", "hybrid", "cloud_quality"] = "hybrid"
    max_task_budget_usd: float = 2.0
    allow_cloud_fallback: bool = True

    local_llm_enabled: bool = False
    local_llm_base_url: str = "http://127.0.0.1:11434/v1"
    local_llm_model: str = ""
    local_min_free_ram_gb: float = 5.0

    openrouter_api_key: str = ""
    openrouter_model: str = ""
    openrouter_input_usd_per_1m: float = 0.0
    openrouter_output_usd_per_1m: float = 0.0

    novita_api_key: str = ""
    novita_model: str = ""
    novita_input_usd_per_1m: float = 0.0
    novita_output_usd_per_1m: float = 0.0

    nvidia_api_key: str = ""
    nvidia_model: str = ""
    nvidia_input_usd_per_1m: float = 0.0
    nvidia_output_usd_per_1m: float = 0.0

    hf_token: str = ""
    hf_model: str = ""
    hf_input_usd_per_1m: float = 0.0
    hf_output_usd_per_1m: float = 0.0

    novita_video_cost_per_second_usd: float = 0.0
    novita_video_max_seconds: int = 8
    primary_cloud_provider: str = "openrouter"

    # ACE-Step may run locally or behind a private endpoint managed by the user.
    ace_step_enabled: bool = False
    ace_step_base_url: str = "http://127.0.0.1:8001"
    ace_step_api_key: str = ""
    ace_step_model: str = "acestep-v15-turbo"
    ace_step_cost_per_second_usd: float = 0.0
    # ACE-Step's 5Hz LM powers thinking/sample mode; GPUs under ~6 GB start without it.
    ace_step_lm_enabled: bool = False

    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    env_path = os.environ.get("MELOFORGE_ENV_FILE")
    settings = Settings(_env_file=env_path) if env_path else Settings()
    try:
        from app.services.secret_store import read_secret

        secret_fields = {"openrouter": "openrouter_api_key", "novita": "novita_api_key", "nvidia": "nvidia_api_key", "huggingface": "hf_token", "ace_step": "ace_step_api_key"}
        for provider, field_name in secret_fields.items():
            secret = read_secret(provider)
            if secret:
                setattr(settings, field_name, secret)
    except (OSError, RuntimeError):
        # Environment variables remain available for development and non-Windows use.
        pass
    return settings
