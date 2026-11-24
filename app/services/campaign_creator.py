"""Part 1: create a campaign with two streams (geo → Google, everyone else → offer)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.keitaro.client import KeitaroClient, KeitaroError
from app.models import Campaign, OfferStatus, Stream, StreamOffer
from app.services import offers as offer_svc
from app.services.errors import ServiceError
from app.services.geo import normalize_geo

log = logging.getLogger(__name__)

GOOGLE_URL = "https://google.com"


def enforce_prefix(name: str) -> str:
    prefix = get_settings().campaign_prefix
    name = (name or "").strip()
    if name.startswith(prefix):
        name = name[len(prefix):]
    if not name:
        raise ServiceError("Campaign name is empty")
    return prefix + name


@dataclass
class CreateCampaignInput:
    name: str
    geo: str
    offer_id: int
    domain_id: int
    group_id: int
    source_id: int


def campaign_payload(data: CreateCampaignInput, name: str) -> dict:
    return {
        "name": name,
        "type": "position",
        "state": "active",
        "domain_id": data.domain_id,
        "group_id": data.group_id,
        "traffic_source_id": data.source_id,
    }


def geo_stream_payload(campaign_id: int, geo: str) -> dict:
    return {
        "campaign_id": campaign_id,
        "name": f"{geo} → Google",
        "type": "regular",
        "state": "active",
        "position": 1,
        "schema": "redirect",
        "action_type": "http",
        "action_payload": GOOGLE_URL,
        "filters": [{"name": "country", "mode": "accept", "payload": [geo]}],
        "offers": [],
    }


def offer_stream_payload(campaign_id: int, offer_id: int) -> dict:
    return {
        "campaign_id": campaign_id,
        "name": "Offers",
        "type": "default",  # catches everyone not caught by the streams above
        "state": "active",
        "position": 2,
        "schema": "landings",
        "action_type": "http",
        "action_payload": None,
        "filters": [],
        "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
    }


async def create_campaign(session: AsyncSession, keitaro: KeitaroClient, data: CreateCampaignInput) -> Campaign:
    try:
        geo = normalize_geo(data.geo)
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc
    name = enforce_prefix(data.name)

    offer_name = await offer_svc.resolve_name(keitaro, data.offer_id)
    if offer_name is None:
        raise ServiceError(f"Offer #{data.offer_id} does not exist in Keitaro")

    created = await keitaro.create_campaign(campaign_payload(data, name))
    kid = int(created["id"])
    try:
        geo_stream = await keitaro.create_stream(geo_stream_payload(kid, geo))
        offer_stream = await keitaro.create_stream(offer_stream_payload(kid, data.offer_id))
    except KeitaroError:
        # Do not leave a half-built campaign behind.
        log.warning("stream creation failed, deleting campaign %s", kid)
        try:
            await keitaro.delete_campaign(kid)
        except KeitaroError:
            log.exception("cleanup of campaign %s failed", kid)
        raise

    now = datetime.now(UTC)
    campaign = Campaign(
        keitaro_id=kid,
        name=created.get("name", name),
        geo=geo,
        domain_id=data.domain_id,
        group_id=data.group_id,
        source_id=data.source_id,
        synced_at=now,
    )
    session.add(campaign)
    await session.flush()
    session.add(
        Stream(
            keitaro_id=int(geo_stream["id"]),
            campaign_id=campaign.id,
            name=geo_stream.get("name", f"{geo} → Google"),
            position=int(geo_stream.get("position") or 1),
            has_offers=False,
            synced_at=now,
        )
    )
    stream = Stream(
        keitaro_id=int(offer_stream["id"]),
        campaign_id=campaign.id,
        name=offer_stream.get("name", "Offers"),
        position=int(offer_stream.get("position") or 2),
        has_offers=True,
        synced_at=now,
    )
    session.add(stream)
    await session.flush()
    offer = await offer_svc.upsert_offer(session, data.offer_id, offer_name)
    session.add(
        StreamOffer(
            stream_id=stream.id,
            offer_id=offer.id,
            position=0,
            share=100,
            status=OfferStatus.active,
            published_share=100,
            published_status=OfferStatus.active,
        )
    )
    await session.commit()
    return campaign
