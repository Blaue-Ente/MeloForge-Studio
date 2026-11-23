from app.config import Settings
from app.schemas import ChatMessage, ChatRequest
from app.services.providers import provider_specs
from app.services.router import RoutingError, choose_provider, estimate_cost


def test_local_provider_has_zero_inference_cost():
    settings = Settings(local_llm_enabled=True, local_llm_model="qwen2.5:3b")
    assert estimate_cost(provider_specs(settings)["ollama"], 1000, 500) == 0.0


def test_cloud_estimate_includes_safety_margin():
    settings = Settings(openrouter_api_key="dummy", openrouter_model="dummy/model", openrouter_input_usd_per_1m=1, openrouter_output_usd_per_1m=2)
    assert estimate_cost(provider_specs(settings)["openrouter"], 1_000_000, 1_000_000) == 3.75


def test_unpriced_cloud_request_is_blocked():
    settings = Settings(openrouter_api_key="dummy", openrouter_model="dummy/model")
    request = ChatRequest(messages=[ChatMessage(role="user", content="Write a chorus")])
    try:
        choose_provider(request, settings)
    except RoutingError as error:
        assert error.code == "cloud_price_missing"
    else:
        raise AssertionError("An unpriced paid request must be blocked")
