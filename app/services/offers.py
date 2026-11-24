"""Offer catalog: cached proxy over Keitaro ``GET /offers`` + local name cache."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.keitaro.client import KeitaroClient
from app.models import Offer

_cache: dict[str, tuple[float, list[dict]]] = {}


def clear_cache() -> None:
    _cache.clear()


async def catalog(keitaro: KeitaroClient, fresh: bool = False) -> list[dict]:
    ttl = get_settings().offers_cache_ttl
    hit = _cache.get("offers")
    if hit and not fresh and time.monotonic() - hit[0] < ttl:
        return hit[1]
    raw = await keitaro.list_offers()
    offers = [{"id": int(o["id"]), "name": str(o.get("name") or f"Offer {o['id']}")} for o in raw]
    _cache["offers"] = (time.monotonic(), offers)
    return offers


def search(offers: list[dict], query: str, limit: int = 20) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return offers[:limit]
    if q.isdigit():
        exact = [o for o in offers if str(o["id"]) == q]
        starts = [o for o in offers if str(o["id"]).startswith(q) and o not in exact]
        by_name = [o for o in offers if q in o["name"].lower() and o not in exact and o not in starts]
        return (exact + starts + by_name)[:limit]
    words = q.split()
    return [o for o in offers if all(w in o["name"].lower() for w in words)][:limit]


async def upsert_offer(session: AsyncSession, keitaro_id: int, name: str | None = None) -> Offer:
    offer = await session.scalar(select(Offer).where(Offer.keitaro_id == keitaro_id))
    if offer is None:
        try:
            async with session.begin_nested():  # another request may insert the same offer
                offer = Offer(keitaro_id=keitaro_id, name=name or "")
                session.add(offer)
        except IntegrityError:
            offer = await session.scalar(select(Offer).where(Offer.keitaro_id == keitaro_id))
    elif name and offer.name != name:
        offer.name = name
    return offer


async def resolve_name(keitaro: KeitaroClient, keitaro_id: int) -> str | None:
    for fresh in (False, True):  # a cache miss may just be a brand-new offer
        for o in await catalog(keitaro, fresh=fresh):
            if o["id"] == keitaro_id:
                return o["name"]
    return None
