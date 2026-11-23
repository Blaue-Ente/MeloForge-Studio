from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.schemas import ChatRequest, VideoRequest
from app.services.hardware import get_hardware_status
from app.services.providers import create_chat_completion, novita_create_video, novita_video_status, public_provider_status
from app.services.router import RoutingError, choose_provider

settings = get_settings()
app = FastAPI(title="MeloForge Studio API", version="0.1.0", description="Adaptive local/cloud AI orchestration")
app.add_middleware(CORSMiddleware, allow_origins=settings.origins(), allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "meloforge-api", "version": "0.1.0"}


@app.get("/api/v1/resources")
async def resources():
    return get_hardware_status(settings)


@app.get("/api/v1/providers")
async def providers():
    return {"providers": public_provider_status(settings), "default_mode": settings.default_mode, "max_task_budget_usd": settings.max_task_budget_usd}


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
    if not settings.novita_api_key:
        raise HTTPException(status_code=409, detail="NOVITA_API_KEY не е конфигуриран.")
    if request.duration > settings.novita_video_max_seconds:
        raise HTTPException(status_code=400, detail="Продължителността надвишава зададения лимит.")
    if settings.novita_video_cost_per_second_usd <= 0:
        raise HTTPException(status_code=409, detail="Въведи актуалната NOVITA_VIDEO_COST_PER_SECOND_USD преди генерация.")
    estimate = round(request.duration * settings.novita_video_cost_per_second_usd * 1.25, 4)
    budget = request.max_cost_usd if request.max_cost_usd is not None else settings.max_task_budget_usd
    if estimate > budget:
        raise HTTPException(status_code=402, detail=f"Прогнозната цена {estimate:.4f} USD надвишава лимита {budget:.2f} USD.")
    try:
        result = await novita_create_video(settings, request.model_dump())
        return {"provider": "novita", "model": "wan-2.2-t2v", "estimated_cost_usd": estimate, **result}
    except Exception:
        raise HTTPException(status_code=502, detail={"code": "novita_video_error", "message": "Novita video API заявката не бе успешна. Провери ключа и наличността на модела."})


@app.get("/api/v1/video/novita/tasks/{task_id}")
async def get_wan22_video_status(task_id: str):
    if not task_id or len(task_id) > 200:
        raise HTTPException(status_code=400, detail="Невалиден task_id.")
    try:
        return await novita_video_status(settings, task_id)
    except Exception:
        raise HTTPException(status_code=502, detail={"code": "novita_status_error", "message": "Неуспешна проверка на статуса в Novita."})
