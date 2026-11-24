"""Async client for the Keitaro Admin API (v1).

Field names follow the emulator docs (https://keitaro-for-tests.etolegko.com/admin/ → docs)
and the real Keitaro Admin API: streams carry ``schema`` (``redirect``/``landings``/``action``),
``action_type``, ``action_payload``, ``filters`` and ``offers: [{offer_id, share, state}]``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

IDEMPOTENT = {"GET", "PUT", "DELETE"}


class KeitaroError(Exception):
    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload

    def __str__(self) -> str:
        return f"Keitaro {self.status_code}: {self.message}" if self.status_code else f"Keitaro: {self.message}"


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300] or resp.reason_phrase
    if isinstance(body, dict):
        for key in ("error", "message", "detail"):
            val = body.get(key)
            if isinstance(val, str):
                return val
            if isinstance(val, list):  # FastAPI-style validation errors
                return "; ".join(
                    f"{'.'.join(str(p) for p in e.get('loc', []))}: {e.get('msg')}" if isinstance(e, dict) else str(e)
                    for e in val
                )
    return str(body)[:300]


class KeitaroClient:
    def __init__(self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings or get_settings()
        self._client = httpx.AsyncClient(
            base_url=self.settings.keitaro_api_base,
            headers={"Api-Key": self.settings.keitaro_api_key, "Accept": "application/json"},
            timeout=self.settings.keitaro_timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> KeitaroClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        if not self.settings.keitaro_api_key:
            raise KeitaroError("KEITARO_API_KEY is not set (.env)")
        attempts = 1 + (self.settings.keitaro_retries if method in IDEMPOTENT else 0)
        for attempt in range(1, attempts + 1):
            try:
                resp = await self._client.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                if attempt < attempts:
                    await asyncio.sleep(0.3 * attempt)
                    continue
                raise KeitaroError(f"cannot reach Keitaro: {exc.__class__.__name__}") from exc
            if resp.status_code >= 500 and attempt < attempts:
                log.warning("Keitaro %s %s -> %s, retrying", method, path, resp.status_code)
                await asyncio.sleep(0.3 * attempt)
                continue
            if resp.is_error:
                raise KeitaroError(_error_message(resp), resp.status_code, _safe_json(resp))
            if resp.status_code == 204 or not resp.content:
                return None
            return resp.json()
        raise AssertionError("unreachable")

    # --- catalog -----------------------------------------------------------------
    async def list_offers(self) -> list[dict]:
        return await self._request("GET", "/offers")

    async def list_domains(self) -> list[dict]:
        return await self._request("GET", "/domains")

    async def list_groups(self) -> list[dict]:
        return await self._request("GET", "/groups", params={"type": "campaigns"})

    async def list_traffic_sources(self) -> list[dict]:
        return await self._request("GET", "/traffic_sources")

    # --- campaigns ---------------------------------------------------------------
    async def list_campaigns(self) -> list[dict]:
        return await self._request("GET", "/campaigns")

    async def get_campaign(self, campaign_id: int) -> dict:
        return await self._request("GET", f"/campaigns/{campaign_id}")

    async def create_campaign(self, payload: dict) -> dict:
        return await self._request("POST", "/campaigns", json=payload)

    async def delete_campaign(self, campaign_id: int) -> None:
        await self._request("DELETE", f"/campaigns/{campaign_id}")

    # --- streams -----------------------------------------------------------------
    async def list_streams(self, campaign_id: int) -> list[dict]:
        return await self._request("GET", f"/campaigns/{campaign_id}/streams")

    async def get_stream(self, stream_id: int) -> dict:
        return await self._request("GET", f"/streams/{stream_id}")

    async def create_stream(self, payload: dict) -> dict:
        return await self._request("POST", "/streams", json=payload)

    async def update_stream(self, stream_id: int, payload: dict) -> dict:
        return await self._request("PUT", f"/streams/{stream_id}", json=payload)


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text


async def get_keitaro():
    client = KeitaroClient()
    try:
        yield client
    finally:
        await client.aclose()
