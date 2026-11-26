from app.config import Settings
from app.services import local_llm

MODELS = [{"name": "qwen2.5:7b", "size_gb": 4.4}, {"name": "qwen2.5:3b", "size_gb": 1.8}, {"name": "bonsai-2:9b", "size_gb": 3.0}]


def test_pick_model_prefers_qwen_and_respects_free_ram():
    assert local_llm.pick_model(MODELS, None) == "qwen2.5:7b"
    assert local_llm.pick_model(MODELS, 8.0) == "qwen2.5:7b"
    assert local_llm.pick_model(MODELS, 3.0) == "qwen2.5:3b"
    assert local_llm.pick_model(MODELS, 0.5) == "qwen2.5:3b"  # smallest preferred as last resort
    assert local_llm.pick_model([], 8.0) is None


def test_auto_enable_only_without_cloud(monkeypatch):
    monkeypatch.setattr(local_llm, "list_models", lambda *a, **k: MODELS)
    settings = Settings(_env_file=None, local_llm_enabled=False, local_llm_model="")
    assert local_llm.auto_enable(settings) == "qwen2.5:7b" and settings.local_llm_enabled
    cloud = Settings(_env_file=None, local_llm_enabled=False, local_llm_model="", openrouter_api_key="k", openrouter_model="m")
    assert local_llm.auto_enable(cloud) is None and not cloud.local_llm_enabled


def test_router_uses_local_as_last_resort_when_ram_is_low(monkeypatch):
    from app.schemas import ChatMessage, ChatRequest
    from app.services import router

    monkeypatch.setattr(router, "get_hardware_status", lambda s: {"local_llm": {"resource_check_passed": False}})
    settings = Settings(_env_file=None, local_llm_enabled=True, local_llm_model="qwen2.5:3b", default_mode="hybrid")
    selected, _ = router.choose_provider(ChatRequest(messages=[ChatMessage(role="user", content="текст")]), settings)
    assert selected.name == "ollama"


def test_lyrics_title_is_extracted_and_stripped_from_text():
    from app.services.lyrics import clean_generated_lyrics, extract_title

    raw = 'Title: "Баба Пенка"\n[Verse 1]\nред едно'
    assert extract_title(raw) == "Баба Пенка"
    assert "Баба Пенка" not in clean_generated_lyrics(raw)
    assert extract_title("[Verse]\nбез заглавие") == ""


def test_story_reaches_the_lyrics_prompt():
    from app.services.lyrics import lyrics_writer_messages

    messages = lyrics_writer_messages(prompt="pop", genre="Поп", mood="", language="bg", duration_seconds=90,
                                      story="За баба Пенка от Враца")
    assert "За баба Пенка от Враца" in messages[1]["content"]


def test_openrouter_save_fills_live_prices(monkeypatch):
    import asyncio

    from app import main
    from app.schemas import ProviderConfigUpdate
    from app.services import openrouter_catalog

    saved = {}
    for field in ("openrouter_api_key", "openrouter_model", "openrouter_input_usd_per_1m", "openrouter_output_usd_per_1m"):
        monkeypatch.setattr(main.settings, field, getattr(main.settings, field))  # restored after the test
    monkeypatch.setattr(openrouter_catalog, "price", lambda model: {"name": model, "input_usd_per_1m": 0.1, "output_usd_per_1m": 0.5} if model == "anthropic/claude-haiku-5.5" else None)
    monkeypatch.setattr(main, "store_secret", lambda name, value: saved.update(name=name))
    monkeypatch.setattr(main, "update_provider_preferences", lambda settings, provider, values: saved.update(values=values))
    result = asyncio.run(main.configure_provider(ProviderConfigUpdate(provider="openrouter", api_key="sk-or-123456789", model="anthropic/claude-haiku-5.5")))
    assert saved["values"]["openrouter_input_usd_per_1m"] == 0.1 and saved["values"]["openrouter_output_usd_per_1m"] == 0.5
    assert result["api_key_stored"] is True

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.configure_provider(ProviderConfigUpdate(provider="openrouter", api_key="sk-or-123456789", model="no/such-model")))
    assert error.value.status_code == 400


def test_openrouter_offers_newest_model_per_family():
    from app.services import openrouter_catalog as c

    def m(created, out=1.0):
        return {"name": "x", "created": created, "input_usd_per_1m": 0.1, "output_usd_per_1m": out}

    models = {"openai/gpt-5.6-luna": m(1), "openai/gpt-6-luna": m(3), "openai/gpt-6-luna:batch": m(4),
              "google/gemini-3.8-flash": m(2), "google/gemini-3.1-flash-image": m(9), "qwen/qwen4-max": m(5),
              "mistralai/mistral-large-4-0": m(6), "z-ai/glm-5.3-flashx-legal": m(7), "deepseek/deepseek-v4.1-flash": m(8, out=0)}
    picked = {item["id"]: item["group"] for item in c.newest_per_family(models)}
    assert "openai/gpt-6-luna" in picked and "openai/gpt-5.6-luna" not in picked and "openai/gpt-6-luna:batch" not in picked
    assert picked["google/gemini-3.8-flash"] == "Google Gemini" and "google/gemini-3.1-flash-image" not in picked
    assert picked["qwen/qwen4-max"] == "Китайски" and picked["mistralai/mistral-large-4-0"] == "Европейски"
    assert "z-ai/glm-5.3-flashx-legal" not in picked and "deepseek/deepseek-v4.1-flash" not in picked  # no free/zero-priced
