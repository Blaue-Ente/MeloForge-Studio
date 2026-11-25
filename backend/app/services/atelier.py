"""Thin client for Atelier's music-video API (contract ``meloforge.song/1``).

Atelier runs locally. MeloForge hands it the absolute path of a song package;
Atelier answers with an estimate and never spends money before ``confirm``.
"""

from __future__ import annotations

from urllib.parse import quote, urlparse

import httpx

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class AtelierError(RuntimeError):
    def __init__(self, message: str, status: int = 502, detail: object = None):
        super().__init__(message)
        self.status = status
        self.detail = detail


def _base(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "") not in LOOPBACK:
        raise AtelierError("Atelier address must be a local (loopback) URL", 400)
    return url.rstrip("/")


async def _call(method: str, url: str, *, json: dict | None = None, timeout: float = 30) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, url, json=json)
    except httpx.HTTPError as exc:
        raise AtelierError("Atelier не отговаря. Стартирай Atelier и провери адреса в настройките.", 503) from exc
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text[:300]}
    if response.status_code >= 400:
        detail = body.get("detail") or body.get("error") if isinstance(body, dict) else body
        raise AtelierError(str(detail or f"Atelier върна {response.status_code}"), response.status_code, body)
    return body if isinstance(body, dict) else {"data": body}


async def health(base_url: str) -> dict:
    base = _base(base_url)
    for path in ("/api/health", "/health", "/api/status"):
        try:
            return {"online": True, **(await _call("GET", base + path, timeout=4))}
        except AtelierError as exc:
            if exc.status == 503:
                return {"online": False}
    return {"online": True}


async def create_music_video(base_url: str, payload: dict) -> dict:
    return await _call("POST", _base(base_url) + "/api/musicvideo", json=payload, timeout=120)


async def confirm(base_url: str, project: str) -> dict:
    return await _call("POST", f"{_base(base_url)}/api/musicvideo/{quote(project, safe='')}/confirm", json={})


async def status(base_url: str, project: str) -> dict:
    return await _call("GET", f"{_base(base_url)}/api/musicvideo/{quote(project, safe='')}")
