import math
from typing import Any

from app.config import Settings
from app.schemas import ChatRequest
from app.services.hardware import get_hardware_status
from app.services.providers import ProviderSpec, provider_specs


class RoutingError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _estimated_input_tokens(messages: list[dict[str, str]]) -> int:
    return max(1, math.ceil(sum(len(m.get("content", "")) for m in messages) / 4))


def estimate_cost(spec: ProviderSpec, input_tokens: int, output_tokens: int) -> float | None:
    if spec.kind == "local":
        return 0.0
    if spec.input_usd_per_1m <= 0 or spec.output_usd_per_1m <= 0:
        return None
    raw = (input_tokens * spec.input_usd_per_1m + output_tokens * spec.output_usd_per_1m) / 1_000_000
    return round(raw * 1.25, 6)


def _available(spec: ProviderSpec) -> bool:
    return bool(spec.api_key and spec.model)


def choose_provider(request: ChatRequest, settings: Settings) -> tuple[ProviderSpec, dict[str, Any]]:
    specs = provider_specs(settings)
    messages = [message.model_dump() for message in request.messages]
    input_tokens = _estimated_input_tokens(messages)
    mode = request.mode or settings.default_mode
    hardware = get_hardware_status(settings)
    local = specs["ollama"]
    local_ready = settings.local_llm_enabled and bool(local.model) and hardware["local_llm"]["resource_check_passed"]
    cloud_specs = [specs[name] for name in ("openrouter", "novita", "nvidia", "huggingface") if _available(specs[name])]

    if request.provider:
        selected = specs[request.provider]
        if selected.kind == "local" and not local_ready:
            raise RoutingError("local_unavailable", "Локалният модел не е конфигуриран или RAM е под безопасния праг.", 409)
        if selected.kind == "cloud" and not _available(selected):
            raise RoutingError("provider_not_configured", f"{selected.name} няма зададен API ключ и модел.", 409)
    elif mode == "local_first" and local_ready:
        selected = local
    elif mode == "hybrid" and local_ready and input_tokens <= 1800:
        selected = local
    else:
        local_last_resort = settings.local_llm_enabled and bool(local.model)
        if mode == "local_first" and not settings.allow_cloud_fallback and not local_last_resort:
            raise RoutingError("local_unavailable", "Cloud fallback е изключен.", 409)
        if (not cloud_specs or (mode == "local_first" and not settings.allow_cloud_fallback)) and local_last_resort:
            # Last resort: the local model even when free RAM is under the comfort threshold
            # (slower, but a fresh install without cloud keys still works).
            selected = local
        elif not cloud_specs:
            raise RoutingError("no_provider_available", "Няма свързан AI модел за текст. Пусни Ollama или добави облачен ключ в Resource Manager.", 409)
        elif mode == "cloud_quality":
            selected = next((s for s in cloud_specs if s.name == settings.primary_cloud_provider), cloud_specs[0])
        else:
            priced = [s for s in cloud_specs if estimate_cost(s, input_tokens, request.max_output_tokens) is not None]
            if not priced:
                raise RoutingError("cloud_price_missing", "Няма облачен доставчик с въведени тарифи; заявката е блокирана.", 409)
            selected = min(priced, key=lambda s: estimate_cost(s, input_tokens, request.max_output_tokens) or 0)

    if request.model and request.model != selected.model:
        raise RoutingError("model_pricing_mismatch", "Защитата на бюджета не позволява модел ID, различен от конфигурирания и тарифиран модел.", 409)

    estimated = estimate_cost(selected, input_tokens, request.max_output_tokens)
    budget = request.max_cost_usd if request.max_cost_usd is not None else settings.max_task_budget_usd
    if estimated is None and selected.kind != "local":
        raise RoutingError("cloud_price_missing", "Цената на модела не е конфигурирана. Платена заявка няма да бъде изпратена.", 409)
    if estimated is not None and estimated > budget:
        raise RoutingError("budget_exceeded", f"Прогнозната цена {estimated:.6f} USD надвишава лимита {budget:.2f} USD.", 402)
    details = {
        "mode": mode, "provider": selected.name, "model": selected.model,
        "estimated_input_tokens": input_tokens, "max_output_tokens": request.max_output_tokens,
        "estimated_cost_usd": estimated, "max_cost_usd": budget,
        "local": selected.kind == "local", "hardware": hardware,
        "estimate_note": "Оценка по приблизителен брой токени и въведена тарифа; добавен е 25% резерв.",
    }
    return selected, details
