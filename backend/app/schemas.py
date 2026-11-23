from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field

ProviderName = Literal["ollama", "openrouter", "novita", "nvidia", "huggingface"]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=30000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    provider: ProviderName | None = None
    model: str | None = Field(default=None, max_length=160)
    mode: Literal["local_first", "hybrid", "cloud_quality"] | None = None
    max_output_tokens: int = Field(default=700, ge=16, le=4096)
    max_cost_usd: float | None = Field(default=None, ge=0, le=100)


class VideoRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=800)
    negative_prompt: str = Field(default="", max_length=500)
    size: Literal["832*480", "480*832", "624*624", "1280*720", "720*1280", "1920*1080", "1080*1920"] = "1280*720"
    duration: Literal[5, 8] = 5
    seed: int | None = Field(default=None, ge=0, le=2147483647)
    max_cost_usd: float | None = Field(default=None, ge=0, le=100)


class SongRequest(BaseModel):
    title: str = Field(default="", max_length=120)
    prompt: str = Field(min_length=3, max_length=1200)
    genre: str = Field(default="", max_length=80)
    mood: str = Field(default="", max_length=80)
    language: Literal["bg", "en"] = "bg"
    duration_seconds: int = Field(default=45, ge=10, le=600)
    lyrics: str = Field(default="", max_length=10000)
    max_cost_usd: float | None = Field(default=None, ge=0, le=100)


class ComposeRequest(BaseModel):
    song_job_id: UUID
    video_job_id: UUID


class ProviderConfigUpdate(BaseModel):
    provider: Literal["openrouter", "novita", "nvidia", "huggingface"]
    api_key: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=180)
    input_usd_per_1m: float | None = Field(default=None, ge=0, le=10000)
    output_usd_per_1m: float | None = Field(default=None, ge=0, le=10000)
    novita_video_cost_per_second_usd: float | None = Field(default=None, ge=0, le=100)


class AceStepConfigUpdate(BaseModel):
    base_url: AnyHttpUrl
    model: str = Field(min_length=1, max_length=180)
    api_key: str | None = Field(default=None, max_length=500)
    cost_per_second_usd: float = Field(default=0, ge=0, le=100)


class RuntimeSettingsUpdate(BaseModel):
    """User-controlled routing preferences. Provider keys deliberately never pass this boundary."""

    default_mode: Literal["local_first", "hybrid", "cloud_quality"] | None = None
    max_task_budget_usd: float | None = Field(default=None, ge=0.1, le=100)
    allow_cloud_fallback: bool | None = None


class StudioDraftRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1200)
    genre: str = Field(default="", max_length=80)
    mood: str = Field(default="", max_length=80)
    duration_seconds: int = Field(default=30, ge=10, le=600)
