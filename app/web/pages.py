from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.config import get_settings

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter(include_in_schema=False)


@router.get("/")
async def new_campaign(request: Request):
    return templates.TemplateResponse(
        request, "new_campaign.html", {"page": "new", "prefix": get_settings().campaign_prefix}
    )


@router.get("/campaigns")
async def campaigns(request: Request):
    return templates.TemplateResponse(request, "editor.html", {"page": "edit", "campaign_id": None, "prefix": get_settings().campaign_prefix})


@router.get("/campaigns/{keitaro_id}")
async def edit_campaign(request: Request, keitaro_id: int):
    return templates.TemplateResponse(request, "editor.html", {"page": "edit", "campaign_id": keitaro_id, "prefix": get_settings().campaign_prefix})
