from typing import Literal

from pydantic import BaseModel, Field

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
