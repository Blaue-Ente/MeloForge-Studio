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

    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
