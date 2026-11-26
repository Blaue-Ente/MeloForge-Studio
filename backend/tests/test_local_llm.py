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
