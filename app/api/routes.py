"""JSON API. Routes only translate HTTP <-> services; business logic lives in app/services."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.keitaro.client import KeitaroClient, get_keitaro
from app.schemas import (
    CampaignCreate,
    CampaignCreated,
    CampaignOut,
    CatalogItem,
    OfferAdd,
    PinUpdate,
    PushRequest,
    StreamOut,
    SyncOut,
    campaign_out,
    stream_out,
)
from app.services import editor
from app.services import offers as offer_svc
from app.services.campaign_creator import CreateCampaignInput, create_campaign
from app.services.errors import NotFound
from app.services.sync import load_campaign, sync_campaign

router = APIRouter(prefix="/api")

Session = Annotated[AsyncSession, Depends(get_session)]
Keitaro = Annotated[KeitaroClient, Depends(get_keitaro)]
Cfg = Annotated[Settings, Depends(get_settings)]


def _items(raw: list[dict]) -> list[CatalogItem]:
    return [CatalogItem(id=int(x["id"]), name=str(x.get("name") or x["id"])) for x in raw]


@router.get("/offers", response_model=list[CatalogItem])
async def search_offers(keitaro: Keitaro, q: str = Query("", max_length=100), limit: int = Query(20, le=50)):
    return offer_svc.search(await offer_svc.catalog(keitaro), q, limit)


@router.get("/catalog")
async def catalog(keitaro: Keitaro, cfg: Cfg):
    return {
        "domains": _items(await keitaro.list_domains()),
        "groups": _items(await keitaro.list_groups()),
        "sources": _items(await keitaro.list_traffic_sources()),
        "defaults": {
            "domain_id": cfg.default_domain_id,
            "group_id": cfg.default_group_id,
            "source_id": cfg.default_source_id,
        },
        "prefix": cfg.campaign_prefix,
    }


@router.get("/campaigns")
async def list_campaigns(keitaro: Keitaro, cfg: Cfg, all: bool = False):
    rows = await keitaro.list_campaigns()
    if not all:
        rows = [c for c in rows if str(c.get("name", "")).startswith(cfg.campaign_prefix)]
    return [{"id": c["id"], "name": c.get("name", ""), "state": c.get("state")} for c in rows]


@router.post("/campaigns", response_model=CampaignCreated, status_code=201)
async def create(body: CampaignCreate, session: Session, keitaro: Keitaro, cfg: Cfg):
    campaign = await create_campaign(session, keitaro, CreateCampaignInput(**body.model_dump()))
    return CampaignCreated(
        id=campaign.id,
        keitaro_id=campaign.keitaro_id,
        name=campaign.name,
        editor_url=f"/campaigns/{campaign.keitaro_id}",
        keitaro_url=cfg.keitaro_campaign_link(campaign.keitaro_id),
    )


@router.get("/campaigns/{keitaro_id}", response_model=CampaignOut)
async def get_campaign(keitaro_id: int, session: Session, cfg: Cfg):
    campaign = await load_campaign(session, keitaro_id)
    if campaign is None:
        raise NotFound("This campaign has not been fetched yet. Press Fetch streams.")
    return campaign_out(campaign, cfg.keitaro_campaign_link(keitaro_id))


@router.post("/campaigns/{keitaro_id}/fetch", response_model=SyncOut)
async def fetch_streams(keitaro_id: int, session: Session, keitaro: Keitaro, cfg: Cfg):
    report = await sync_campaign(session, keitaro, keitaro_id)
    campaign = await load_campaign(session, keitaro_id)
    return SyncOut(campaign=campaign_out(campaign, cfg.keitaro_campaign_link(keitaro_id)), **report.__dict__)


@router.post("/streams/{stream_id}/offers", response_model=StreamOut)
async def add_offer(stream_id: int, body: OfferAdd, session: Session, keitaro: Keitaro):
    return stream_out(await editor.add_offer(session, keitaro, stream_id, body.offer_id))


@router.post("/streams/{stream_id}/offers/{link_id}/remove", response_model=StreamOut)
async def remove_offer(stream_id: int, link_id: int, session: Session):
    return stream_out(await editor.remove_offer(session, stream_id, link_id))


@router.post("/streams/{stream_id}/offers/{link_id}/restore", response_model=StreamOut)
async def bring_back(stream_id: int, link_id: int, session: Session):
    return stream_out(await editor.bring_back(session, stream_id, link_id))


@router.put("/streams/{stream_id}/offers/{link_id}/pin", response_model=StreamOut)
async def pin(stream_id: int, link_id: int, body: PinUpdate, session: Session):
    return stream_out(await editor.set_pin(session, stream_id, link_id, body.pinned, body.share))


@router.post("/streams/{stream_id}/cancel", response_model=StreamOut)
async def cancel(stream_id: int, session: Session):
    return stream_out(await editor.cancel(session, stream_id))


@router.post("/streams/{stream_id}/push", response_model=StreamOut)
async def push(stream_id: int, session: Session, keitaro: Keitaro, body: PushRequest | None = None):
    return stream_out(await editor.push(session, keitaro, stream_id, force=bool(body and body.force)))
