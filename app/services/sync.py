"""Part 2.1 / 4.6: pull streams from Keitaro and reconcile them with our DB.

Rules
-----
* Streams without offers (``schema != "landings"``) are stored only as name/position.
  Their filters and redirect targets are not read or stored.
* For a *clean* offer stream Keitaro is the source of truth:
    - offers in Keitaro → active (``state: disabled`` → removed), weights taken as is;
    - offers we knew but Keitaro no longer has → ``removed`` (grey, Bring back available);
    - offers unknown to us → added as active.
* A *dirty* stream (unpushed local changes) is NOT touched; it is reported in
  ``skipped_dirty`` so the UI can ask the user to Push or Cancel first.
* Streams deleted in Keitaro are deleted locally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.keitaro.client import KeitaroClient, KeitaroError
from app.models import Campaign, OfferStatus, Stream, StreamOffer
from app.services import offers as offer_svc
from app.services.errors import NotFound


@dataclass
class SyncReport:
    streams_total: int = 0
    skipped_dirty: list[str] = field(default_factory=list)
    deleted_streams: list[str] = field(default_factory=list)
    offers_added: int = 0
    offers_marked_removed: int = 0


def is_offer_stream(k_stream: dict) -> bool:
    return k_stream.get("schema") == "landings"


async def load_campaign(session: AsyncSession, keitaro_id: int) -> Campaign | None:
    return await session.scalar(
        select(Campaign)
        .where(Campaign.keitaro_id == keitaro_id)
        .options(selectinload(Campaign.streams).selectinload(Stream.links).joinedload(StreamOffer.offer))
        .execution_options(populate_existing=True)
    )


async def _upsert_campaign(session: AsyncSession, keitaro: KeitaroClient, keitaro_id: int) -> Campaign:
    try:
        k = await keitaro.get_campaign(keitaro_id)
    except KeitaroError as exc:
        if exc.status_code == 404:
            raise NotFound(f"Campaign #{keitaro_id} not found in Keitaro") from exc
        raise
    campaign = await load_campaign(session, keitaro_id)
    if campaign is None:
        campaign = Campaign(keitaro_id=keitaro_id, name=k.get("name", ""))
        session.add(campaign)
        await session.flush()
        campaign = await load_campaign(session, keitaro_id)
    campaign.name = k.get("name", campaign.name)
    campaign.domain_id = k.get("domain_id", campaign.domain_id)
    campaign.group_id = k.get("group_id", campaign.group_id)
    campaign.source_id = k.get("traffic_source_id", campaign.source_id)
    return campaign


def reconcile_links(stream: Stream, k_offers: list[dict], offer_by_kid: dict) -> tuple[int, int]:
    """Apply Keitaro's offer list to a clean stream. Returns (added, marked_removed)."""
    existing = {link.offer.keitaro_id: link for link in stream.links}
    seen: set[int] = set()
    added = marked = 0
    pos = 0
    for ko in k_offers:
        kid = int(ko["offer_id"])
        if kid in seen:
            continue
        seen.add(kid)
        active = ko.get("state", "active") == "active"
        status = OfferStatus.active if active else OfferStatus.removed
        share = int(ko.get("share") or 0) if active else 0
        link = existing.get(kid)
        if link is None:
            link = StreamOffer(offer=offer_by_kid[kid], offer_id=offer_by_kid[kid].id)
            stream.links.append(link)
            added += 1
        link.position = pos
        link.status = link.published_status = status
        link.share = link.published_share = share
        link.added_in_draft = False
        if not active:
            link.is_pinned = False
        pos += 1

    for link in sorted(stream.links, key=lambda x: x.position):
        if link.offer.keitaro_id in seen:
            continue
        if link.published_status == OfferStatus.active:
            marked += 1
        link.position = pos
        link.status = link.published_status = OfferStatus.removed
        link.share = link.published_share = 0
        link.is_pinned = False
        link.added_in_draft = False
        pos += 1
    stream.is_dirty = False
    return added, marked


async def sync_campaign(session: AsyncSession, keitaro: KeitaroClient, keitaro_id: int) -> SyncReport:
    campaign = await _upsert_campaign(session, keitaro, keitaro_id)
    k_streams = await keitaro.list_streams(keitaro_id)
    report = SyncReport(streams_total=len(k_streams))
    now = datetime.now(UTC)

    # Offer names for any offer we may need to create.
    names = {o["id"]: o["name"] for o in await offer_svc.catalog(keitaro)}
    offer_by_kid = {}
    for ks in k_streams:
        if is_offer_stream(ks):
            for ko in ks.get("offers") or []:
                kid = int(ko["offer_id"])
                if kid not in offer_by_kid:
                    offer_by_kid[kid] = await offer_svc.upsert_offer(session, kid, names.get(kid))

    local = {s.keitaro_id: s for s in campaign.streams}
    k_ids = set()
    for ks in sorted(k_streams, key=lambda s: (s.get("position") or 0, s["id"])):
        kid = int(ks["id"])
        k_ids.add(kid)
        stream = local.get(kid)
        if stream is None:
            stream = Stream(keitaro_id=kid, campaign_id=campaign.id, links=[])
            campaign.streams.append(stream)
        stream.name = ks.get("name") or f"Stream {kid}"
        stream.position = int(ks.get("position") or 0)
        stream.has_offers = is_offer_stream(ks)

        if not stream.has_offers:
            stream.links.clear()
            stream.is_dirty = False
            stream.synced_at = now
            continue
        if stream.is_dirty:
            report.skipped_dirty.append(stream.name)
            continue
        added, marked = reconcile_links(stream, ks.get("offers") or [], offer_by_kid)
        report.offers_added += added
        report.offers_marked_removed += marked
        stream.synced_at = now

    for kid, stream in local.items():
        if kid not in k_ids:
            report.deleted_streams.append(stream.name)
            campaign.streams.remove(stream)

    campaign.synced_at = now
    await session.commit()
    return report
