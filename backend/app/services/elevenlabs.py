"""ElevenLabs voices as singing targets.

ElevenLabs does not sing our songs directly. We take a short spoken sample of
one of the account's voices (text-to-speech, ~250 characters, billed in the
user's ElevenLabs credits) and save it as a MeloForge voice profile. Seed-VC
then sings in that timbre locally. Only voices the account may use are listed
(its own clones, designed voices and added library voices); respect each
voice's terms on the ElevenLabs side.

The API key is stored with the OS secret store (DPAPI on Windows) under
``elevenlabs`` and never returned to the browser.
"""

from __future__ import annotations

import httpx

from app.services import voice_clone

API = "https://api.elevenlabs.io/v1"
SAMPLE_MODEL = "eleven_multilingual_v2"
SAMPLE_TEXT = {
    "bg": ("Днес е хубав ден. Слънцето грее над града, а аз пея любимата си песен. "
           "Музиката ме кара да се чувствам свободен и щастлив. Понякога пея тихо, понякога силно, "
           "но винаги от сърце, за всички, които обичам."),
    "en": ("Today is a beautiful day. The sun is shining over the city and I am singing my favourite song. "
           "Music makes me feel free and happy. Sometimes I sing softly, sometimes loud, "
           "but always from the heart, for everyone I love."),
}


class ElevenLabsError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def api_key() -> str:
    from app.services.secret_store import read_secret

    try:
        return read_secret("elevenlabs") or ""
    except (OSError, RuntimeError):
        return ""


def save_key(key: str) -> None:
    from app.services.secret_store import store_secret

    store_secret("elevenlabs", key.strip())


def _headers(key: str) -> dict:
    return {"xi-api-key": key, "Accept": "application/json"}


def _raise_for(response: httpx.Response) -> None:
    if response.status_code in {401, 403}:
        raise ElevenLabsError("ElevenLabs отказа ключа или достъпа до този глас.", 401)
    if response.status_code == 429:
        raise ElevenLabsError("ElevenLabs: лимитът или кредитите са изчерпани.", 429)
    if response.status_code >= 400:
        raise ElevenLabsError(f"ElevenLabs върна грешка {response.status_code}.", 502)


async def list_voices(key: str | None = None) -> list[dict]:
    key = key or api_key()
    if not key:
        raise ElevenLabsError("Няма ElevenLabs ключ.", 400)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{API}/voices", headers=_headers(key))
    except httpx.HTTPError as exc:
        raise ElevenLabsError("ElevenLabs не отговаря.", 503) from exc
    _raise_for(response)
    voices = []
    for item in response.json().get("voices", []):
        labels = item.get("labels") or {}
        voices.append({
            "voice_id": item.get("voice_id"), "name": item.get("name"), "category": item.get("category"),
            "gender": labels.get("gender"), "accent": labels.get("accent"), "age": labels.get("age"),
            "description": labels.get("description") or item.get("description"), "preview_url": item.get("preview_url"),
        })
    return voices


def sample_text(language: str) -> str:
    return SAMPLE_TEXT.get(language, SAMPLE_TEXT["en"])


async def import_voice(voice_id: str, name: str, *, language: str = "bg", key: str | None = None) -> dict:
    """Render a ~20 s sample with the voice and store it as a local voice profile."""
    key = key or api_key()
    if not key:
        raise ElevenLabsError("Няма ElevenLabs ключ.", 400)
    if not voice_id or not voice_id.replace("_", "").isalnum() or len(voice_id) > 64:
        raise ElevenLabsError("Невалиден ElevenLabs глас.", 400)
    body = {"text": sample_text(language), "model_id": SAMPLE_MODEL,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.85}}
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(f"{API}/text-to-speech/{voice_id}", params={"output_format": "mp3_44100_128"},
                                         headers={**_headers(key), "Accept": "audio/mpeg"}, json=body)
    except httpx.HTTPError as exc:
        raise ElevenLabsError("ElevenLabs не отговаря.", 503) from exc
    _raise_for(response)
    profile = voice_clone.create_voice(name=name, data=response.content, filename="elevenlabs.mp3", consent=True)
    return voice_clone.tag_voice(profile["id"], source="elevenlabs", elevenlabs_voice_id=voice_id,
                                 characters=len(body["text"]))
