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
    instrumental: bool = False
    # Optional musical metadata. ACE-Step treats these as anchors; leave empty to let it choose.
    bpm: int | None = Field(default=None, ge=30, le=300)
    key_scale: str = Field(default="", max_length=24, pattern=r"^$|^[A-Ga-g][#b]?\s?(m|min|minor|maj|major|Major|Minor)?$")
    time_signature: Literal["2", "3", "4", "6"] | None = None
    seed: int | None = Field(default=None, ge=0, le=2147483647)
    inference_steps: int = Field(default=8, ge=1, le=20)
    master_preset: Literal["streaming", "apple", "broadcast"] = "streaming"
    max_cost_usd: float | None = Field(default=None, ge=0, le=100)


class LyricsDraftRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1200)
    title: str = Field(default="", max_length=120)
    genre: str = Field(default="", max_length=80)
    mood: str = Field(default="", max_length=80)
    language: Literal["bg", "en"] = "bg"
    duration_seconds: int = Field(default=90, ge=10, le=600)
    provider: ProviderName | None = None
    max_cost_usd: float | None = Field(default=None, ge=0, le=100)
    # Optional trend brief from /api/v1/music/trends to steer themes and structure.
    themes: list[str] = Field(default_factory=list, max_length=8)
    structure: str = Field(default="", max_length=300)
    lyric_style: str = Field(default="", max_length=600)


class TrendRequest(BaseModel):
    genre: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9_-]+$")
    language: Literal["bg", "en"] = "bg"
    analyze: bool = True
    refresh: bool = False
    provider: ProviderName | None = None
    max_cost_usd: float | None = Field(default=None, ge=0, le=100)


class ComposeRequest(BaseModel):
    song_job_id: UUID
    video_job_id: UUID


class ElevenLabsKey(BaseModel):
    key: str = Field(min_length=10, max_length=200)


class ElevenLabsImport(BaseModel):
    voice_id: str = Field(min_length=4, max_length=64, pattern=r"^[A-Za-z0-9_]+$")
    name: str = Field(default="", max_length=60)
    language: Literal["bg", "en"] = "bg"
    consent: bool = False


class VoiceSongRequest(BaseModel):
    """Re-sing a finished song in a saved voice profile (local Seed-VC)."""

    song_job_id: UUID
    voice_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    semitones: int = Field(default=0, ge=-12, le=12)
    # Duet / choir: optional second voice and per-section parts {section index: mode}.
    voice_b_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    semitones_b: int = Field(default=0, ge=-12, le=12)
    parts: dict[int, Literal["A", "B", "AB", "choir", "original"]] = Field(default_factory=dict, max_length=40)
    quality: Literal["fast", "balanced", "best"] = "balanced"
    vocal_gain_db: float = Field(default=0.0, ge=-6, le=6)
    master_preset: Literal["streaming", "apple", "broadcast"] = "streaming"


class AtelierVideoRequest(BaseModel):
    """Music video through Atelier. Paid work there always waits for an explicit confirm."""

    song_job_id: UUID
    mode: Literal["stills", "mixed", "video"] = "mixed"
    aspect: Literal["16x9", "9x16"] = "16x9"
    lyrics_on_screen: bool = True
    local_only: bool = False
    budget_usd: float = Field(default=1.05, ge=0, le=20)
    notes: str = Field(default="", max_length=1000)


class VisualizerRequest(BaseModel):
    """Free local music video from a finished song (no AI video provider)."""

    song_job_id: UUID
    style: Literal["spectrum", "wave", "pulse"] = "spectrum"
    palette: Literal["neon", "sunset", "ocean", "mono"] = "neon"
    show_lyrics: bool = False
    title: str | None = Field(default=None, max_length=120)
    subtitle: str | None = Field(default=None, max_length=120)


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
    # True only when the ACE-Step server was started with its 5Hz LM (ACESTEP_INIT_LLM).
    lm_enabled: bool = False


class RuntimeSettingsUpdate(BaseModel):
    """User-controlled routing preferences. Provider keys deliberately never pass this boundary."""

    default_mode: Literal["local_first", "hybrid", "cloud_quality"] | None = None
    max_task_budget_usd: float | None = Field(default=None, ge=0.1, le=100)
    allow_cloud_fallback: bool | None = None
    atelier_base_url: str | None = Field(default=None, max_length=200, pattern=r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?/?$")


class StudioDraftRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1200)
    genre: str = Field(default="", max_length=80)
    mood: str = Field(default="", max_length=80)
    duration_seconds: int = Field(default=30, ge=10, le=600)
