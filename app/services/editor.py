"""Part 2.2–2.7: draft editing of offer streams and Push / Cancel."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.keitaro.client import KeitaroClient, KeitaroError
from app.models import OfferStatus, Stream, StreamOffer
from app.services import offers as offer_svc
from app.services.errors import Conflict, NotFound, ServiceError
from app.services.sync import active_signature, parse_offers, parse_share
from app.services.weights import WeightError, WeightItem, distribute, push_problem


def weight_items(links: list[StreamOffer]) -> list[WeightItem]:
    return [WeightItem(status=link.status.value, pinned=link.is_pinned, share=link.share) for link in links]


def ordered(stream: Stream) -> list[StreamOffer]:
    return sorted(stream.links, key=lambda x: (x.position, x.id or 0))


def recalc(stream: Stream) -> None:
    links = ordered(stream)
    try:
        shares = distribute(weight_items(links))
    except WeightError as exc:
        raise ServiceError(str(exc), 422) from exc
    for link, share in zip(links, shares, strict=True):
        link.share = share
    refresh_dirty(stream)


def refresh_dirty(stream: Stream) -> None:
    stream.is_dirty = any(link.is_changed for link in stream.links)


def stream_problem(stream: Stream) -> str | None:
    if not stream.has_offers:
        return None
    return push_problem(weight_items(ordered(stream)))


async def load_stream(session: AsyncSession, stream_id: int) -> Stream:
    stream = await session.scalar(
        select(Stream)
        .where(Stream.id == stream_id)
        .with_for_update(of=Stream)  # serialize edits of one stream (no-op on SQLite)
        .options(selectinload(Stream.links).joinedload(StreamOffer.offer))
        .execution_options(populate_existing=True)
    )
    if stream is None:
        raise NotFound("Stream not found. Press Fetch streams to reload the campaign.")
    if not stream.has_offers:
        raise ServiceError("This stream has no offers; it cannot be edited here.")
    return stream


def _link(stream: Stream, link_id: int) -> StreamOffer:
    for link in stream.links:
        if link.id == link_id:
            return link
    raise NotFound("Offer is not in this stream")


async def _save(session: AsyncSession, stream: Stream) -> Stream:
    await session.commit()
    return await load_stream(session, stream.id)


async def add_offer(session: AsyncSession, keitaro: KeitaroClient, stream_id: int, offer_kid: int) -> Stream:
    stream = await load_stream(session, stream_id)
    for link in stream.links:
        if link.offer.keitaro_id == offer_kid:
            if link.status == OfferStatus.active:
                raise ServiceError(f"Offer #{offer_kid} is already in this stream")
            link.status = OfferStatus.active
            recalc(stream)
            return await _save(session, stream)

    name = await offer_svc.resolve_name(keitaro, offer_kid)
    if name is None:
        raise ServiceError(f"Offer #{offer_kid} does not exist in Keitaro")
    offer = await offer_svc.upsert_offer(session, offer_kid, name)
    stream.links.append(
        StreamOffer(
            offer=offer,
            offer_id=offer.id,
            position=max((x.position for x in stream.links), default=-1) + 1,
            status=OfferStatus.active,
            published_status=OfferStatus.removed,
            published_share=0,
            added_in_draft=True,
        )
    )
    recalc(stream)
    return await _save(session, stream)


async def remove_offer(session: AsyncSession, stream_id: int, link_id: int) -> Stream:
    stream = await load_stream(session, stream_id)
    link = _link(stream, link_id)
    if link.status == OfferStatus.removed:
        raise ServiceError("Offer is already removed")
    link.status = OfferStatus.removed
    link.is_pinned = False
    recalc(stream)
    return await _save(session, stream)


async def bring_back(session: AsyncSession, stream_id: int, link_id: int) -> Stream:
    stream = await load_stream(session, stream_id)
    link = _link(stream, link_id)
    if link.status == OfferStatus.active:
        raise ServiceError("Offer is already active")
    link.status = OfferStatus.active
    recalc(stream)
    return await _save(session, stream)


async def set_pin(session: AsyncSession, stream_id: int, link_id: int, pinned: bool, share: int | None) -> Stream:
    stream = await load_stream(session, stream_id)
    link = _link(stream, link_id)
    if link.status != OfferStatus.active:
        raise ServiceError("Removed offers cannot be pinned. Bring the offer back first.")
    if pinned:
        value = link.share if share is None else share
        if not 0 <= value <= 100:
            raise ServiceError("Pinned weight must be between 0 and 100%", 422)
        link.share = value
    link.is_pinned = pinned
    recalc(stream)  # raises 422 (and nothing is committed) if pinned > 100
    return await _save(session, stream)


async def cancel(session: AsyncSession, stream_id: int) -> Stream:
    stream = await load_stream(session, stream_id)
    for link in list(stream.links):
        if link.added_in_draft:
            stream.links.remove(link)  # delete the link, the Offer row stays
            continue
        link.share = link.published_share
        link.status = link.published_status
        if link.status == OfferStatus.removed:
            link.is_pinned = False
    stream.is_dirty = False
    return await _save(session, stream)


def _mark_published(stream: Stream, links: list[StreamOffer]) -> None:
    for link in list(links):
        if link.added_in_draft and link.status == OfferStatus.removed:
            # added and removed inside one draft: Keitaro never had it, nothing to archive
            stream.links.remove(link)
            continue
        link.published_share = link.share
        link.published_status = link.status
        link.added_in_draft = False
    stream.is_dirty = False
    stream.synced_at = datetime.now(UTC)


async def push(session: AsyncSession, keitaro: KeitaroClient, stream_id: int, force: bool = False) -> Stream:
    stream = await load_stream(session, stream_id)
    links = ordered(stream)
    problem = push_problem(weight_items(links))
    if problem:
        raise ServiceError(problem, 422)

    try:
        remote = await keitaro.get_stream(stream.keitaro_id)
    except KeitaroError as exc:
        if exc.status_code == 404:
            raise Conflict("This stream was deleted in Keitaro. Press Fetch streams.") from exc
        raise
    remote_offers = remote.get("offers") or []
    remote_now = active_signature(remote_offers)
    draft = {link.offer.keitaro_id: link.share for link in links if link.status == OfferStatus.active}
    if remote_now == draft:
        # Keitaro already has exactly this draft (e.g. an earlier Push reached Keitaro
        # but we failed afterwards): just record it as published.
        _mark_published(stream, links)
        return await _save(session, stream)

    published = {
        link.offer.keitaro_id: link.published_share
        for link in links
        if link.published_status == OfferStatus.active
    }
    if not force and remote_now != published:
        now = ", ".join(f"#{kid} {share}%" for kid, share in remote_now.items()) or "no active offers"
        raise Conflict(
            "Offers of this stream were changed in Keitaro after your last fetch. "
            f"Keitaro now has: {now}. "
            "Push anyway to overwrite them, or Cancel and Fetch streams to load the new state."
        )

    payload_offers = [
        {"offer_id": link.offer.keitaro_id, "share": link.share, "state": "active"}
        for link in links
        if link.status == OfferStatus.active
    ]
    # Offers switched off in Keitaro (state: disabled) are not ours to delete: keep them as they are.
    removed_here = {link.offer.keitaro_id for link in links if link.published_status == OfferStatus.active}
    for kid, active, _ in parse_offers(remote_offers):
        if not active and kid not in draft and kid not in removed_here:
            original = next(o for o in remote_offers if int(o["offer_id"]) == kid)
            payload_offers.append(
                {"offer_id": kid, "share": parse_share(original.get("share")), "state": "disabled"}
            )

    updated = await keitaro.update_stream(stream.keitaro_id, {"offers": payload_offers})
    after = (updated or {}).get("offers")
    if after is None:
        after = (await keitaro.get_stream(stream.keitaro_id)).get("offers") or []
    if active_signature(after) != draft:
        raise ServiceError(
            "Keitaro accepted the update but returned different weights. Press Fetch streams to see the real state.",
            502,
        )

    _mark_published(stream, links)
    return await _save(session, stream)
