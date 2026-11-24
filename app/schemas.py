from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import Campaign, Stream
from app.services.editor import ordered, stream_problem


class CatalogItem(BaseModel):
    id: int
    name: str


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    geo: str = Field(min_length=2, max_length=2)
    offer_id: int
    domain_id: int
    group_id: int
    source_id: int


class CampaignCreated(BaseModel):
    id: int
    keitaro_id: int
    name: str
    editor_url: str
    keitaro_url: str


class OfferAdd(BaseModel):
    offer_id: int


class PinUpdate(BaseModel):
    pinned: bool
    share: int | None = Field(default=None, ge=0, le=100)


class PushRequest(BaseModel):
    force: bool = False


class LinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    offer_id: int
    name: str
    share: int
    pinned: bool
    status: str
    published_share: int
    published_status: str
    added_in_draft: bool
    changed: bool


class StreamOut(BaseModel):
    id: int
    keitaro_id: int
    name: str
    position: int
    has_offers: bool
    is_dirty: bool
    problem: str | None
    synced_at: datetime | None
    offers: list[LinkOut]


class CampaignOut(BaseModel):
    id: int
    keitaro_id: int
    name: str
    geo: str | None
    synced_at: datetime | None
    keitaro_url: str
    streams: list[StreamOut]


class SyncOut(BaseModel):
    campaign: CampaignOut
    streams_total: int
    skipped_dirty: list[str]
    deleted_streams: list[str]
    offers_added: int
    offers_marked_removed: int


def _utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; values are always stored in UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def stream_out(stream: Stream) -> StreamOut:
    return StreamOut(
        id=stream.id,
        keitaro_id=stream.keitaro_id,
        name=stream.name,
        position=stream.position,
        has_offers=stream.has_offers,
        is_dirty=stream.is_dirty,
        problem=stream_problem(stream),
        synced_at=_utc(stream.synced_at),
        offers=[
            LinkOut(
                id=link.id,
                offer_id=link.offer.keitaro_id,
                name=link.offer.name or f"Offer {link.offer.keitaro_id}",
                share=link.share,
                pinned=link.is_pinned,
                status=link.status.value,
                published_share=link.published_share,
                published_status=link.published_status.value,
                added_in_draft=link.added_in_draft,
                changed=link.is_changed,
            )
            for link in ordered(stream)
        ]
        if stream.has_offers
        else [],
    )


def campaign_out(campaign: Campaign, keitaro_url: str) -> CampaignOut:
    return CampaignOut(
        id=campaign.id,
        keitaro_id=campaign.keitaro_id,
        name=campaign.name,
        geo=campaign.geo,
        synced_at=_utc(campaign.synced_at),
        keitaro_url=keitaro_url,
        streams=[stream_out(s) for s in sorted(campaign.streams, key=lambda s: (s.position, s.keitaro_id))],
    )
