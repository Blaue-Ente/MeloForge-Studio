import asyncio
import logging
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.schemas import (
    AceStepConfigUpdate,
    AtelierVideoRequest,
    ChatRequest,
    ComposeRequest,
    LyricsDraftRequest,
    ProviderConfigUpdate,
    RuntimeSettingsUpdate,
    SongRequest,
    StudioDraftRequest,
    TrendRequest,
    VideoRequest,
    VisualizerRequest,
    VoiceSongRequest,
)
from app.services import atelier, jobs, voice_clone
from app.services.ace_step import AceStepConfig
from app.services.ace_step import list_models as ace_step_models
from app.services.ace_step import song_status as ace_step_song_status
from app.services.ace_step import submit_song as ace_step_submit_song
from app.services.composer import compose_song_video, lyrics_path, output_path
from app.services.hardware import get_hardware_status, local_tool_status
from app.services.lyrics import (
    clean_generated_lyrics,
    lyric_warnings,
    lyrics_writer_messages,
    structure_lyrics,
)
from app.services.providers import (
    create_chat_completion,
    novita_create_video,
    novita_video_status,
    public_provider_status,
)
from app.services.router import RoutingError, choose_provider
from app.services.runtime_settings import (
    load_runtime_preferences,
    public_runtime_preferences,
    update_provider_preferences,
    update_runtime_preferences,
)
from app.services.secret_store import store_secret
from app.services.song_package import PackageError, export_package
from app.services.songs import finalize_song, finalize_voice_song, song_file
from app.services.trends import (
    GENRES,
    ChartTrack,
    analysis_messages,
    chart_stats,
    default_brief,
    fetch_chart,
    freshness_notes,
    load_cached,
    parse_brief,
    public_genres,
    save_cache,
)
from app.services.visualizer import render_visualizer

settings = get_settings()
logger = logging.getLogger("meloforge")
load_runtime_preferences(settings)
app = FastAPI(title="MeloForge Studio API", version="0.4.0", description="Adaptive local/cloud AI orchestration")
app.add_middleware(CORSMiddleware, allow_origins=settings.origins(), allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "meloforge-api", "version": "0.4.0"}


@app.get("/api/v1/resources")
async def resources():
    return get_hardware_status(settings)


@app.get("/api/v1/providers")
async def providers():
    return {"providers": public_provider_status(settings), **public_runtime_preferences(settings)}


@app.get("/api/v1/settings")
async def runtime_settings():
    return public_runtime_preferences(settings)


@app.patch("/api/v1/settings")
async def update_settings(payload: RuntimeSettingsUpdate):
    return update_runtime_preferences(settings, payload.model_dump(exclude_none=True))


@app.post("/api/v1/providers/configure")
async def configure_provider(payload: ProviderConfigUpdate):
    try:
        store_secret(payload.provider, payload.api_key.strip())
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(503, "Ключът не беше шифрован и записан локално.")

    key_fields = {"openrouter": "openrouter_api_key", "novita": "novita_api_key", "nvidia": "nvidia_api_key", "huggingface": "hf_token"}
    model_fields = {"openrouter": "openrouter_model", "novita": "novita_model", "nvidia": "nvidia_model", "huggingface": "hf_model"}
    setattr(settings, key_fields[payload.provider], payload.api_key.strip())
    safe_values = {model_fields[payload.provider]: payload.model.strip()}
    prefix = "hf" if payload.provider == "huggingface" else payload.provider
    if payload.input_usd_per_1m is not None:
        safe_values[f"{prefix}_input_usd_per_1m"] = payload.input_usd_per_1m
    if payload.output_usd_per_1m is not None:
        safe_values[f"{prefix}_output_usd_per_1m"] = payload.output_usd_per_1m
    if payload.novita_video_cost_per_second_usd is not None and payload.provider == "novita":
        safe_values["novita_video_cost_per_second_usd"] = payload.novita_video_cost_per_second_usd
    try:
        update_provider_preferences(settings, payload.provider, safe_values)
    except OSError:
        raise HTTPException(500, "Ключът е записан локално, но моделните настройки не се записаха.")
    status = next(row for row in public_provider_status(settings) if row["id"] == payload.provider)
    return {"provider": status, "api_key_stored": True, "storage": "Windows DPAPI"}


@app.post("/api/v1/music/configure")
async def configure_music_engine(payload: AceStepConfigUpdate):
    base_url = str(payload.base_url).rstrip("/")
    if not _is_local_endpoint(base_url) and payload.cost_per_second_usd <= 0:
        raise HTTPException(409, "За външен ACE-Step endpoint въведи актуална цена за секунда.")
    if payload.api_key and payload.api_key.strip():
        try:
            store_secret("ace_step", payload.api_key.strip())
            settings.ace_step_api_key = payload.api_key.strip()
        except (OSError, RuntimeError, ValueError):
            raise HTTPException(503, "Ключът не беше шифрован и записан локално.")
    safe_values = {
        "ace_step_enabled": True,
        "ace_step_base_url": base_url,
        "ace_step_model": payload.model.strip(),
        "ace_step_cost_per_second_usd": payload.cost_per_second_usd,
        "ace_step_lm_enabled": payload.lm_enabled,
    }
    try:
        update_provider_preferences(settings, "ace_step", safe_values)
    except OSError:
        raise HTTPException(500, "Настройките на ACE-Step не бяха запазени.")
    return {"configured": True, "base_url": base_url, "model": settings.ace_step_model, "readiness": await music_readiness()}


@app.get("/api/v1/diagnostics")
async def diagnostics():
    hardware = get_hardware_status(settings)
    tools = local_tool_status()
    return {
        "api": "ok",
        "hardware": hardware,
        "tools": tools,
        "checks": [
            {"id": "backend", "label": "MeloForge backend", "ok": True, "detail": "API is responding"},
            {"id": "nvidia", "label": "NVIDIA diagnostics", "ok": tools["nvidia_smi"], "detail": "nvidia-smi found" if tools["nvidia_smi"] else "nvidia-smi is not available"},
            {"id": "ollama", "label": "Ollama", "ok": tools["ollama"], "detail": "Ollama command found" if tools["ollama"] else "Install Ollama to use local LLMs"},
            {"id": "ffmpeg", "label": "FFmpeg", "ok": tools["ffmpeg"], "detail": "FFmpeg found" if tools["ffmpeg"] else "Install FFmpeg for final video assembly"},
        ],
    }


def _ace_step_config() -> AceStepConfig:
    return AceStepConfig(settings.ace_step_base_url, settings.ace_step_enabled, settings.ace_step_api_key)


def _is_local_endpoint(base_url: str) -> bool:
    return urlparse(base_url).hostname in {"localhost", "127.0.0.1", "::1"}


def _ace_step_model_catalog(payload: dict) -> tuple[list[str], str | None]:
    data = payload.get("data")
    if isinstance(data, list):
        entries = data
        default_model = payload.get("default_model")
    elif isinstance(data, dict):
        entries = data.get("models") or []
        default_model = data.get("default_model") or payload.get("default_model")
    else:
        entries = []
        default_model = payload.get("default_model")

    names = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        identifier = item.get("id") or item.get("name")
        if identifier:
            name = str(identifier).rsplit("/", 1)[-1]
            if name not in names:
                names.append(name)

    normalized_default = str(default_model).rsplit("/", 1)[-1] if default_model else None
    return names, normalized_default


@app.get("/api/v1/music/readiness")
async def music_readiness():
    """Read-only ACE-Step preflight; this endpoint never submits a generation."""
    if not settings.ace_step_enabled:
        return {"ready": False, "reason": "ACE-Step е изключен.", "models": [], "base_url": settings.ace_step_base_url, "model": settings.ace_step_model}
    try:
        body = await ace_step_models(_ace_step_config())
        names, default_model = _ace_step_model_catalog(body)
        model = settings.ace_step_model or default_model
        if model:
            model = str(model).rsplit("/", 1)[-1]
        ready = bool(names and model in names)
        return {"ready": ready, "model": model, "models": names, "base_url": settings.ace_step_base_url, "lm_enabled": settings.ace_step_lm_enabled, "reason": None if ready else "Избраният ACE-Step модел не е зареден."}
    except Exception:
        return {"ready": False, "reason": "ACE-Step API не отговаря. Провери адреса и дали услугата работи.", "models": [], "base_url": settings.ace_step_base_url, "model": settings.ace_step_model}


@app.post("/api/v1/studio/plan")
async def studio_plan(request: StudioDraftRequest):
    """Route a music/video brief without contacting a provider or spending money."""
    message = "\n".join(part for part in [request.prompt, f"Genre: {request.genre}" if request.genre else "", f"Mood: {request.mood}" if request.mood else ""] if part)
    preview = ChatRequest(messages=[{"role": "user", "content": message}], max_output_tokens=min(1200, max(250, request.duration_seconds * 2)))
    try:
        _, decision = choose_provider(preview, settings)
        return {"ready": True, "decision": decision, "brief": {"duration_seconds": request.duration_seconds}}
    except RoutingError as exc:
        return {"ready": False, "reason": {"code": exc.code, "message": exc.message}, "brief": {"duration_seconds": request.duration_seconds}}

@app.post("/api/v1/jobs/video/quote")
async def create_video_quote(request: VideoRequest):
    if not settings.novita_api_key:
        raise HTTPException(409, "Novita не е конфигуриран. Добави нов ключ в локалния .env файл.")
    if request.duration > settings.novita_video_max_seconds:
        raise HTTPException(400, "Продължителността надвишава зададения лимит.")
    if settings.novita_video_cost_per_second_usd <= 0:
        raise HTTPException(409, "Липсва тарифа за Novita видео. Попълни NOVITA_VIDEO_COST_PER_SECOND_USD в .env.")
    estimate = round(request.duration * settings.novita_video_cost_per_second_usd * 1.25, 4)
    budget = request.max_cost_usd if request.max_cost_usd is not None else settings.max_task_budget_usd
    if estimate > budget:
        raise HTTPException(402, f"Оценката ${estimate:.4f} надхвърля лимита ${budget:.2f}.")
    job = jobs.create("video", request.model_dump(exclude={"max_cost_usd"}), estimate)
    return {**job.__dict__, "max_cost_usd": budget, "estimate_note": "Тарифата от локалния .env плюс 25% резерв; потвърди преди изпращане."}


@app.post("/api/v1/jobs/song/quote")
async def create_song_quote(request: SongRequest):
    if not settings.ace_step_enabled:
        raise HTTPException(409, "ACE-Step е изключен. Настрой ACE_STEP_ENABLED и адреса му в локалния .env.")
    try:
        model_data = await ace_step_models(_ace_step_config())
    except Exception:
        raise HTTPException(409, "ACE-Step API не отговаря. Стартирай услугата и провери ACE_STEP_BASE_URL.")
    available_models, default_model = _ace_step_model_catalog(model_data)
    model = settings.ace_step_model or default_model
    if model:
        model = str(model).rsplit("/", 1)[-1]
    if not model or model not in available_models:
        raise HTTPException(409, "Избраният ACE-Step модел не е зареден. Зареди го или коригирай ACE_STEP_MODEL.")

    local_endpoint = _is_local_endpoint(settings.ace_step_base_url)
    if not local_endpoint and settings.ace_step_cost_per_second_usd <= 0:
        raise HTTPException(409, "За отдалечен ACE-Step endpoint задай актуална ACE_STEP_COST_PER_SECOND_USD.")
    estimate = 0.0 if local_endpoint else round(request.duration_seconds * settings.ace_step_cost_per_second_usd * 1.25, 4)
    budget = request.max_cost_usd if request.max_cost_usd is not None else settings.max_task_budget_usd
    if estimate > budget:
        raise HTTPException(402, f"Оценката ${estimate:.4f} надхвърля лимита ${budget:.2f}.")
    payload = request.model_dump(exclude={"max_cost_usd"})
    warnings: list[str] = []
    if request.instrumental:
        payload["lyrics"] = "[Instrumental]"
    elif request.lyrics.strip():
        structured = structure_lyrics(request.lyrics)
        if structured != request.lyrics.strip():
            warnings.append("Текстът нямаше секции; добавени са [Verse]/[Chorus] тагове за ACE-Step.")
        payload["lyrics"] = structured
        warnings += lyric_warnings(structured, request.duration_seconds)
    elif not settings.ace_step_lm_enabled:
        raise HTTPException(409, "ACE-Step работи без езиковия си модел (5Hz LM) и не може сам да напише текст. Въведи текст, използвай „Напиши текст с AI“ или избери инструментал.")
    payload["_ace_step_model"] = model
    job = jobs.create("song", payload, estimate)
    note = "Локален ACE-Step; не се таксува API." if local_endpoint else "Отдалечена ACE-Step тарифа от .env плюс 25% резерв."
    return {**job.__dict__, "max_cost_usd": budget, "warnings": warnings, "estimate_note": f"{note} Потвърди преди изпращане."}


@app.post("/api/v1/music/lyrics")
async def draft_lyrics(request: LyricsDraftRequest):
    """Draft ACE-Step-tagged lyrics with the routed LLM (local first, budget-gated cloud)."""
    messages = lyrics_writer_messages(prompt=request.prompt, genre=request.genre, mood=request.mood, language=request.language, duration_seconds=request.duration_seconds, title=request.title, themes=request.themes, structure=request.structure, lyric_style=request.lyric_style)
    chat_request = ChatRequest(messages=messages, provider=request.provider, max_output_tokens=min(2048, 300 + request.duration_seconds * 6), max_cost_usd=request.max_cost_usd)
    try:
        selected, decision = choose_provider(chat_request, settings)
        result = await create_chat_completion(selected, messages, chat_request.max_output_tokens)
    except RoutingError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    except Exception:
        raise HTTPException(502, {"code": "provider_error", "message": "LLM доставчикът не върна текст. Провери модела и логовете."})
    lyrics = clean_generated_lyrics(result.get("content") or "")
    if not lyrics:
        raise HTTPException(502, {"code": "empty_lyrics", "message": "Моделът върна празен текст."})
    return {"lyrics": lyrics, "provider": selected.name, "model": selected.model, "estimated_cost_usd": decision["estimated_cost_usd"], "warnings": lyric_warnings(lyrics, request.duration_seconds)}

@app.get("/api/v1/music/genres")
async def music_genres():
    return {"genres": public_genres()}


@app.post("/api/v1/music/trends")
async def music_trends(request: TrendRequest):
    """Current chart for a genre (Deezer, cached 6 h) plus a production/lyrics brief.

    With ``analyze`` the brief comes from the routed LLM (budget-gated); otherwise,
    or if no LLM is available, a deterministic brief from preset + chart numbers.
    """
    genre = GENRES.get(request.genre)
    if not genre:
        raise HTTPException(404, "Непознат жанр.")
    cached = None if request.refresh else load_cached(jobs.ROOT, genre.id)
    if cached is None:
        try:
            tracks = await fetch_chart(genre)
        except Exception:
            raise HTTPException(502, "Класацията не можа да бъде заредена (Deezer). Провери интернет връзката.")
        if not tracks:
            raise HTTPException(502, "Класацията за този жанр е празна.")
        cached = save_cache(jobs.ROOT, genre.id, tracks, chart_stats(tracks))
    tracks = [ChartTrack(**row) for row in cached["tracks"]]
    stats = cached["stats"]
    brief = default_brief(genre, stats)
    analysis = {"used_llm": False, "provider": None, "model": None, "estimated_cost_usd": 0.0, "note": None}
    if request.analyze:
        messages = analysis_messages(genre, tracks, stats, request.language)
        chat_request = ChatRequest(messages=messages, provider=request.provider, max_output_tokens=700, max_cost_usd=request.max_cost_usd)
        try:
            selected, decision = choose_provider(chat_request, settings)
            result = await create_chat_completion(selected, messages, chat_request.max_output_tokens)
            brief = parse_brief(result.get("content") or "", brief)
            analysis.update(used_llm=brief.get("source") == "llm", provider=selected.name, model=selected.model, estimated_cost_usd=decision["estimated_cost_usd"])
        except RoutingError as exc:
            analysis["note"] = exc.message
        except Exception:
            analysis["note"] = "LLM анализът не беше успешен; показан е анализ по класацията."
    return {
        "genre": {"id": genre.id, "label": genre.label},
        "source": "Deezer chart (регионална класация)",
        "fetched_at": cached["fetched_at"],
        "tracks": [row for row in cached["tracks"]][:25],
        "stats": stats,
        "notes": freshness_notes(stats),
        "brief": brief,
        "analysis": analysis,
    }


@app.get("/api/v1/jobs")
async def list_jobs(kind: str | None = Query(default=None, pattern="^(song|video|composition)$"), limit: int = Query(default=20, ge=1, le=200)):
    return {"jobs": jobs.list_recent(kind=kind, limit=limit)}


@app.get("/api/v1/songs/{job_id}/{kind}")
async def download_song(job_id: str, kind: str):
    job = jobs.get(job_id)
    if not job or job.kind != "song" or job.status != "completed":
        raise HTTPException(404, "Готовата песен не е намерена.")
    found = song_file(job.id, kind)
    if not found or not found[0].is_file():
        raise HTTPException(404, "Файлът не е наличен.")
    path, media_type = found
    title = "".join(ch for ch in (job.payload.get("title") or "MeloForge-song") if ch.isalnum() or ch in " -_").strip() or "MeloForge-song"
    return FileResponse(path, media_type=media_type, filename=f"{title}{path.suffix}" if kind in {"mp3", "wav", "raw"} else f"{title} - {kind}{path.suffix}" if kind in {"vocals", "instrumental"} else path.name)


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Задачата не е намерена.")
    if job.kind == "song" and job.status == "running" and job.provider_task_id:
        try:
            provider_result = await ace_step_song_status(_ace_step_config(), job.provider_task_id)
            if provider_result["status"] == 1:
                if provider_result.get("audio_url"):
                    result = {key: provider_result[key] for key in ("audio_url", "lyrics", "metadata")}
                    job = jobs.update(job.id, status="mastering", result=result) or job
                    _start_finalize(job.id)
                else:
                    job = jobs.update(job.id, status="failed", error="ACE-Step приключи задачата, но не върна аудио файл.") or job
            elif provider_result["status"] == 2:
                job = jobs.update(job.id, status="failed", error="ACE-Step не успя да генерира песента.") or job
        except Exception:
            # Provider polling is read-only; transient failures leave the job recoverable.
            pass
    elif job.kind == "song" and job.status == "running" and job.payload.get("mode") == "voice_swap" and job.id not in _voice_running:
        # The worker thread died with the previous app process.
        job = jobs.update(job.id, status="failed", error="Обработката беше прекъсната (приложението се рестартира). Пусни я отново.") or job
    elif job.kind == "song" and job.status == "mastering":
        # Resume after a restart; the in-memory guard prevents duplicate work.
        _start_finalize(job.id)
    if job.kind == "video" and job.status == "running" and job.provider_task_id:
        try:
            provider_result = await novita_video_status(settings, job.provider_task_id)
            task = provider_result.get("task") or provider_result
            raw_status = str(task.get("status") or task.get("task_status") or "running").lower()
            result = _video_result(provider_result)
            if raw_status in {"success", "succeeded", "succeed", "completed", "done"} or raw_status.endswith(("_succeed", "_succeeded")):
                job = jobs.update(job.id, status="completed", result=result) or job
            elif raw_status in {"failed", "failure", "error", "canceled", "cancelled"} or raw_status.endswith(("_failed", "_failure", "_error", "_canceled", "_cancelled")):
                job = jobs.update(job.id, status="failed", error="Novita не успя да генерира видеото.") or job
        except Exception:
            # A transient status poll failure does not change the provider job state.
            pass
    return job

@app.post("/api/v1/jobs/{job_id}/confirm")
async def confirm_job(job_id: str):
    job = jobs.confirm(job_id)
    if not job:
        raise HTTPException(409, "Задачата не чака потвърждение.")
    try:
        if job.kind == "song":
            request_data = job.payload.copy()
            model = request_data.pop("_ace_step_model", settings.ace_step_model)
            provider_payload = build_ace_step_payload(request_data, model, lm_enabled=settings.ace_step_lm_enabled)
            provider_result = await ace_step_submit_song(_ace_step_config(), provider_payload)
            updated_payload = {**request_data, "model": model}
            return jobs.update(job.id, status="running", provider_task_id=provider_result["task_id"], payload=updated_payload)
        if job.kind != "video":
            jobs.update(job.id, status="failed", error="Този тип генерация няма свързан engine.")
            raise HTTPException(409, "За този тип генерация engine не е конфигуриран.")
        provider_result = await novita_create_video(settings, job.payload)
        task_id = provider_result.get("task_id") or (provider_result.get("task") or {}).get("task_id")
        if not task_id:
            jobs.update(job.id, status="failed", error="Novita не върна идентификатор на задачата.")
            raise HTTPException(502, "Novita не върна идентификатор на задачата.")
        return jobs.update(job.id, status="running", provider_task_id=str(task_id))
    except HTTPException:
        raise
    except Exception:
        message = "ACE-Step заявката не бе успешна. Провери конфигурацията и услугата." if job.kind == "song" else "Novita заявката не бе успешна. Провери ключа и баланса."
        jobs.update(job.id, status="failed", error=message)
        raise HTTPException(502, message)


def build_ace_step_payload(request_data: dict, model: str, *, lm_enabled: bool) -> dict:
    """Translate a confirmed SongRequest into ACE-Step 1.5 /release_task parameters."""
    lyrics = (request_data.get("lyrics") or "").strip()
    genre, mood = request_data.get("genre", ""), request_data.get("mood", "")
    # ACE-Step guidance: caption = style/emotion/instruments; tempo and key go in metadata fields.
    caption = ", ".join(part for part in [genre, mood, request_data.get("prompt", "")] if part)
    payload = {
        "task_type": "text2music",
        "prompt": caption,
        "vocal_language": request_data.get("language", "bg"),
        "audio_duration": request_data.get("duration_seconds", 45),
        # Lossless from the engine; MeloForge produces the MP3/WAV deliverables itself.
        "audio_format": "wav",
        "model": model,
        "thinking": lm_enabled,
        "use_cot_caption": lm_enabled,
        "use_cot_language": lm_enabled,
        "inference_steps": int(request_data.get("inference_steps") or 8),
        "batch_size": 1,
    }
    if lyrics:
        payload["lyrics"] = lyrics
    elif lm_enabled:
        payload["sample_mode"] = True
        payload["sample_query"] = caption
    if request_data.get("bpm"):
        payload["bpm"] = int(request_data["bpm"])
    if request_data.get("key_scale"):
        payload["key_scale"] = request_data["key_scale"]
    if request_data.get("time_signature"):
        payload["time_signature"] = str(request_data["time_signature"])
    if request_data.get("seed") is not None:
        payload["use_random_seed"] = False
        payload["seed"] = int(request_data["seed"])
    return payload


_finalizing: set[str] = set()


async def _finalize_song_job(job_id: str) -> None:
    try:
        result = await asyncio.to_thread(finalize_song, job_id, ace_step_base_url=settings.ace_step_base_url, ace_step_api_key=settings.ace_step_api_key)
        jobs.update(job_id, status="completed", result=result)
    except Exception as exc:
        logger.error("Song finalisation %s failed (%s: %s)", job_id, type(exc).__name__, exc)
        jobs.update(job_id, status="failed", error="Песента е генерирана, но не беше изтеглена или мастерирана. Провери FFmpeg и ACE-Step.")
    finally:
        _finalizing.discard(job_id)


def _start_finalize(job_id: str) -> None:
    if job_id in _finalizing:
        return
    _finalizing.add(job_id)
    asyncio.get_running_loop().create_task(_finalize_song_job(job_id))


def _run_composition(job_id: str, song_job_id: str, video_job_id: str) -> None:
    try:
        song = jobs.get(song_job_id)
        video = jobs.get(video_job_id)
        if not song or not video or song.kind != "song" or video.kind != "video" or song.status != "completed" or video.status != "completed":
            raise ValueError("Both source jobs must be complete before assembly.")
        audio_url = (song.result or {}).get("audio_url")
        video_urls = (video.result or {}).get("video_urls") or []
        if not audio_url or not video_urls:
            raise ValueError("A source job is missing its media file.")
        lyrics = (song.result or {}).get("lyrics") or song.payload.get("lyrics") or ""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise ValueError("FFmpeg is not installed.")
        mastered = song_file(song.id, "mp3")
        result = compose_song_video(
            job_id,
            audio_url=audio_url,
            local_audio=mastered[0] if mastered and mastered[0].is_file() else None,
            video_url=video_urls[0],
            duration_seconds=int(song.payload.get("duration_seconds", 0)),
            lyrics=lyrics,
            ffmpeg=ffmpeg,
            ace_step_base_url=settings.ace_step_base_url,
            ace_step_api_key=settings.ace_step_api_key,
        )
        result["song_job_id"] = song_job_id
        result["video_job_id"] = video_job_id
        jobs.update(job_id, status="completed", result=result)
    except Exception as exc:
        logger.error("Media composition %s failed (%s)", job_id, type(exc).__name__)
        jobs.update(job_id, status="failed", error="Неуспешно сглобяване. Провери дали FFmpeg е наличен и файловете са достъпни.")


def _run_visualizer(job_id: str, song_job_id: str) -> None:
    try:
        song = jobs.get(song_job_id)
        mastered = song_file(song_job_id, "mp3") if song else None
        if not song or not mastered or not mastered[0].is_file():
            raise ValueError("The song has no mastered audio.")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise ValueError("FFmpeg is not installed.")
        job = jobs.get(job_id)
        options = job.payload if job else {}
        lyrics = (song.result or {}).get("lyrics") or song.payload.get("lyrics") or ""
        if lyrics.strip() == "[Instrumental]":
            lyrics = ""
        title = options.get("title") if options.get("title") is not None else song.payload.get("title", "")
        subtitle = options.get("subtitle") if options.get("subtitle") is not None else " · ".join(
            part for part in [song.payload.get("genre", ""), "MeloForge"] if part)
        result = render_visualizer(
            audio=mastered[0], output_dir=output_path(job_id, "16x9").parent, ffmpeg=ffmpeg, title=title or "",
            subtitle=subtitle or "", lyrics=lyrics, style=options.get("style", "spectrum"),
            palette=options.get("palette", "neon"), show_lyrics=bool(options.get("show_lyrics")),
        )
        if lyrics.strip():
            lyrics_path(job_id).write_text(lyrics.strip() + "\n", encoding="utf-8", newline="\n")
        result.update(song_job_id=song_job_id, lyrics_available=bool(lyrics.strip()))
        jobs.update(job_id, status="completed", result=result)
    except Exception as exc:
        logger.error("Visualizer %s failed (%s: %s)", job_id, type(exc).__name__, exc)
        jobs.update(job_id, status="failed", error="Локалният клип не беше създаден. Провери FFmpeg и дали песента е мастерирана.")


_VOICE_ERRORS = {
    "consent": (400, "Потвърди, че гласът е твой или имаш изричното съгласие на собственика му."),
    "empty": (400, "Файлът е празен."),
    "too_large": (413, "Файлът е над 40 MB. Качи 10–30 секунди запис."),
    "unreadable": (400, "Записът не може да бъде прочетен. Опитай WAV, MP3, M4A или запис от браузъра."),
    "too_short": (400, "Записът е под 5 секунди чист глас. Нужни са 10–30 секунди."),
}


@app.get("/api/v1/voices")
async def list_voice_profiles():
    return {"engine": voice_clone.engine_status(), "voices": voice_clone.list_voices()}


@app.post("/api/v1/voices")
async def create_voice_profile(request: Request, name: str = Query(default="Моят глас", max_length=60),
                               filename: str = Query(default="recording.webm", max_length=200), consent: bool = Query(default=False)):
    """Raw audio body (any FFmpeg-readable format). Consent is mandatory."""
    length = int(request.headers.get("content-length") or 0)
    if length > voice_clone.MAX_UPLOAD_BYTES:
        raise HTTPException(*_VOICE_ERRORS["too_large"])
    data = await request.body()
    try:
        return await asyncio.to_thread(voice_clone.create_voice, name=name, data=data, filename=filename, consent=consent)
    except voice_clone.VoiceCloneError as exc:
        code, message = _VOICE_ERRORS.get(str(exc), (400, "Гласовият профил не беше създаден."))
        raise HTTPException(code, message) from exc


@app.get("/api/v1/voices/{voice_id}/sample")
async def voice_sample(voice_id: str):
    if not voice_clone.get_voice(voice_id):
        raise HTTPException(404, "Гласът не е намерен.")
    return FileResponse(voice_clone.voice_dir(voice_id) / "reference.wav", media_type="audio/wav")


@app.post("/api/v1/voices/{voice_id}/delete")
async def delete_voice_profile(voice_id: str):
    try:
        removed = voice_clone.delete_voice(voice_id)
    except voice_clone.VoiceCloneError:
        removed = False
    if not removed:
        raise HTTPException(404, "Гласът не е намерен.")
    return {"deleted": voice_id}


_voice_running: set[str] = set()


def _run_voice_song(job_id: str, source_job_id: str, voice: dict) -> None:
    _voice_running.add(job_id)
    try:
        result = finalize_voice_song(job_id, source_job_id, voice)
        jobs.update(job_id, status="completed", result=result)
    except Exception as exc:
        logger.error("Voice song %s failed (%s: %s)", job_id, type(exc).__name__, str(exc)[-400:])
        jobs.update(job_id, status="failed", error="Песента не беше изпята с избрания глас. Провери дали Seed-VC е инсталиран и има свободна видео памет (спри други AI задачи).")
    finally:
        _voice_running.discard(job_id)


@app.post("/api/v1/music/voice-swap")
async def create_voice_song(request: VoiceSongRequest, background_tasks: BackgroundTasks):
    status = voice_clone.engine_status()
    if not status["installed"]:
        raise HTTPException(503, "Seed-VC не е инсталиран. " + (status["install_hint"] or ""))
    source = jobs.get(str(request.song_job_id))
    if not source or source.kind != "song" or source.status != "completed":
        raise HTTPException(409, "Избери завършена песен.")
    if source.payload.get("instrumental") or ((source.result or {}).get("lyrics") or "").strip() == "[Instrumental]":
        raise HTTPException(409, "Инструменталната песен няма вокал за заменяне.")
    voice = voice_clone.get_voice(request.voice_id)
    if not voice:
        raise HTTPException(404, "Гласът не е намерен.")
    if not shutil.which("ffmpeg"):
        raise HTTPException(503, "FFmpeg не е инсталиран.")
    base = source.payload
    payload = {
        "mode": "voice_swap", "source_song_id": source.id, "voice_id": voice["id"],
        "title": f"{base.get('title') or 'Песен'} ({voice.get('name')})"[:120], "prompt": base.get("prompt", ""),
        "genre": base.get("genre", ""), "duration_seconds": base.get("duration_seconds"), "lyrics": base.get("lyrics", ""),
        **request.model_dump(exclude={"song_job_id", "voice_id"}),
    }
    job = jobs.create("song", payload, 0)
    # No provider_task_id: the status poller leaves this job to the background worker.
    jobs.update(job.id, status="running")
    _voice_running.add(job.id)
    background_tasks.add_task(_run_voice_song, job.id, source.id, voice)
    return jobs.get(job.id)


_PACKAGE_ERRORS = {"not_ready": "Избери завършена песен.", "no_master": "Песента няма мастериран запис."}


@app.post("/api/v1/songs/{job_id}/package")
async def song_package(job_id: str, stems: bool = Query(default=True)):
    """Export the ``meloforge.song/1`` package (song.json + master + aligned stems)."""
    try:
        return await asyncio.to_thread(export_package, job_id, None, stems=stems)
    except PackageError as exc:
        raise HTTPException(409, _PACKAGE_ERRORS.get(str(exc), "Пакетът не беше създаден.")) from exc


def _atelier_error(exc: atelier.AtelierError) -> HTTPException:
    return HTTPException(exc.status if 400 <= exc.status < 600 else 502, str(exc))


@app.get("/api/v1/atelier/status")
async def atelier_status():
    try:
        return {"base_url": settings.atelier_base_url, **(await atelier.health(settings.atelier_base_url))}
    except atelier.AtelierError as exc:
        return {"base_url": settings.atelier_base_url, "online": False, "error": str(exc)}


@app.post("/api/v1/atelier/musicvideo")
async def atelier_music_video(request: AtelierVideoRequest):
    """Package the song, hand it to Atelier and return its estimate (nothing paid starts here)."""
    try:
        package = await asyncio.to_thread(export_package, str(request.song_job_id), None)
    except PackageError as exc:
        raise HTTPException(409, _PACKAGE_ERRORS.get(str(exc), "Пакетът не беше създаден.")) from exc
    body = {"song_dir": package["song_dir"], **request.model_dump(exclude={"song_job_id"})}
    try:
        result = await atelier.create_music_video(settings.atelier_base_url, body)
    except atelier.AtelierError as exc:
        raise _atelier_error(exc) from exc
    return {"package": {"song_dir": package["song_dir"], "stems": "vocals" in package["manifest"]["files"]}, **result}


@app.post("/api/v1/atelier/musicvideo/{project}/confirm")
async def atelier_confirm(project: str):
    try:
        return await atelier.confirm(settings.atelier_base_url, project)
    except atelier.AtelierError as exc:
        raise _atelier_error(exc) from exc


@app.get("/api/v1/atelier/musicvideo/{project}")
async def atelier_project(project: str):
    try:
        return await atelier.status(settings.atelier_base_url, project)
    except atelier.AtelierError as exc:
        raise _atelier_error(exc) from exc


@app.get("/api/v1/atelier/musicvideo/{project}/video")
async def atelier_video(project: str):
    """Serve the finished MP4 that Atelier reports for this project (local file)."""
    try:
        state = await atelier.status(settings.atelier_base_url, project)
    except atelier.AtelierError as exc:
        raise _atelier_error(exc) from exc
    video = ((state.get("outputs") or {}).get("video") or "")
    path = Path(video) if video else None
    if not path or path.suffix.lower() != ".mp4" or not path.is_file():
        raise HTTPException(404, "Видеото още не е готово.")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.post("/api/v1/media/visualizer")
async def create_visualizer(request: VisualizerRequest, background_tasks: BackgroundTasks):
    song = jobs.get(str(request.song_job_id))
    if not song or song.kind != "song" or song.status != "completed":
        raise HTTPException(409, "Избери завършена песен.")
    mastered = song_file(song.id, "mp3")
    if not mastered or not mastered[0].is_file():
        raise HTTPException(409, "Песента няма мастериран запис. Генерирай я отново с тази версия на MeloForge.")
    if not shutil.which("ffmpeg"):
        raise HTTPException(503, "FFmpeg не е инсталиран.")
    payload = {"mode": "visualizer", "song_job_id": song.id, **request.model_dump(exclude={"song_job_id"})}
    composition = jobs.create("composition", payload, 0)
    jobs.update(composition.id, status="queued")
    background_tasks.add_task(_run_visualizer, composition.id, song.id)
    return jobs.get(composition.id)


@app.post("/api/v1/media/compose")
async def create_composition(request: ComposeRequest, background_tasks: BackgroundTasks):
    song_job_id, video_job_id = str(request.song_job_id), str(request.video_job_id)
    song = jobs.get(song_job_id)
    video = jobs.get(video_job_id)
    if not song or song.kind != "song" or song.status != "completed":
        raise HTTPException(409, "Избери завършена песен.")
    if not video or video.kind != "video" or video.status != "completed":
        raise HTTPException(409, "Избери завършено видео.")
    if not (song.result or {}).get("audio_url") or not (video.result or {}).get("video_urls"):
        raise HTTPException(409, "Източниците нямат готов аудио и видео файл.")
    if not shutil.which("ffmpeg"):
        raise HTTPException(503, "FFmpeg не е инсталиран.")
    composition = jobs.create("composition", {"song_job_id": song.id, "video_job_id": video.id}, 0)
    jobs.update(composition.id, status="queued")
    background_tasks.add_task(_run_composition, composition.id, song.id, video.id)
    return jobs.get(composition.id)


@app.get("/api/v1/media/{job_id}/lyrics")
async def download_composition_lyrics(job_id: str):
    job = jobs.get(job_id)
    if not job or job.kind != "composition" or job.status != "completed":
        raise HTTPException(404, "Текстът не е намерен.")
    target = lyrics_path(job.id)
    if not target.is_file():
        raise HTTPException(404, "За тази песен няма наличен текстов файл.")
    return FileResponse(target, media_type="text/plain; charset=utf-8", filename="lyrics.txt")


@app.get("/api/v1/media/{job_id}/{aspect}")
async def download_composition(job_id: str, aspect: str):
    job = jobs.get(job_id)
    if not job or job.kind != "composition" or job.status != "completed":
        raise HTTPException(404, "Готовият монтаж не е намерен.")
    try:
        target = output_path(job.id, aspect)
    except ValueError:
        raise HTTPException(404, "Неподдържан видео формат.")
    if not target.is_file():
        raise HTTPException(404, "Видео файлът липсва.")
    return FileResponse(target, media_type="video/mp4", filename=f"MeloForge-{aspect}.mp4")


def _video_result(data: dict) -> dict:
    """Keep only user-facing video URLs from a provider status response."""
    urls: list[str] = []
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"video_url", "url", "output_url"} and isinstance(child, str) and child.startswith("https://"):
                    urls.append(child)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(data)
    return {"video_urls": list(dict.fromkeys(urls))}


@app.post("/api/v1/route/preview")
async def route_preview(request: ChatRequest):
    try:
        _, decision = choose_provider(request, settings)
        return {"decision": decision}
    except RoutingError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@app.post("/api/v1/chat")
async def chat(request: ChatRequest):
    try:
        selected, decision = choose_provider(request, settings)
        result = await create_chat_completion(selected, [m.model_dump() for m in request.messages], request.max_output_tokens)
        return {"provider": selected.name, "model": selected.model, "content": result["content"], "usage": result["usage"], "estimated_cost_usd": decision["estimated_cost_usd"], "cost_note": decision["estimate_note"]}
    except RoutingError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    except Exception:
        # Do not send provider request headers or credentials back to the browser.
        raise HTTPException(status_code=502, detail={"code": "provider_error", "message": "Доставчикът върна грешка. Провери ключа, модела и логовете на backend."})


@app.post("/api/v1/video/novita/wan22")
async def create_wan22_video(request: VideoRequest):
    raise HTTPException(status_code=410, detail="Този endpoint е изведен от употреба. Използвай /api/v1/jobs/video/quote, после отделно потвърди задачата.")


@app.get("/api/v1/video/novita/tasks/{task_id}")
async def get_wan22_video_status(task_id: str):
    if not task_id or len(task_id) > 200:
        raise HTTPException(status_code=400, detail="Невалиден task_id.")
    try:
        return await novita_video_status(settings, task_id)
    except Exception:
        raise HTTPException(status_code=502, detail={"code": "novita_status_error", "message": "Неуспешна проверка на статуса в Novita."})


def _frontend_dist() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "frontend" / "dist"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


frontend_dist = _frontend_dist()
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def studio_frontend(path: str):
        target = frontend_dist / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(frontend_dist / "index.html")
