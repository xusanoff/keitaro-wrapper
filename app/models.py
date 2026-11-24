from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class OfferStatus(str, enum.Enum):
    active = "active"
    removed = "removed"


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    geo: Mapped[str | None] = mapped_column(String(2))
    domain_id: Mapped[int | None]
    group_id: Mapped[int | None]
    source_id: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    streams: Mapped[list[Stream]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", order_by="Stream.position"
    )


class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=0)
    has_offers: Mapped[bool] = mapped_column(Boolean, default=False)
    is_dirty: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[Campaign] = relationship(back_populates="streams")
    links: Mapped[list[StreamOffer]] = relationship(
        back_populates="stream", cascade="all, delete-orphan", order_by="StreamOffer.position"
    )


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")


class StreamOffer(Base):
    """Offer inside a stream.

    ``share``/``status`` is the working (draft) state shown in the UI,
    ``published_share``/``published_status`` is the last state pushed to or fetched
    from Keitaro. ``added_in_draft`` marks links that Keitaro has never seen.
    """

    __tablename__ = "stream_offers"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id", name="uq_stream_offer"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="RESTRICT"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    share: Mapped[int] = mapped_column(Integer, default=0)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[OfferStatus] = mapped_column(
        Enum(OfferStatus, name="offer_status", native_enum=False, length=16), default=OfferStatus.active
    )

    published_share: Mapped[int] = mapped_column(Integer, default=0)
    published_status: Mapped[OfferStatus] = mapped_column(
        Enum(OfferStatus, name="offer_status", native_enum=False, length=16), default=OfferStatus.removed
    )
    added_in_draft: Mapped[bool] = mapped_column(Boolean, default=False)

    stream: Mapped[Stream] = relationship(back_populates="links")
    offer: Mapped[Offer] = relationship(lazy="joined")

    @property
    def is_changed(self) -> bool:
        return (
            self.added_in_draft
            or self.share != self.published_share
            or self.status != self.published_status
        )
