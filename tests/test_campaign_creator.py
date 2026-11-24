import pytest
from sqlalchemy import func, select

from app.models import Campaign, StreamOffer
from app.services.campaign_creator import CreateCampaignInput, create_campaign, enforce_prefix
from app.services.errors import ServiceError
from app.keitaro.client import KeitaroError


def data(**kw):
    base = dict(name="promo1", geo="mx", offer_id=18002, domain_id=1813, group_id=10332, source_id=836)
    base.update(kw)
    return CreateCampaignInput(**base)


def test_prefix_enforced():
    assert enforce_prefix("camp") == "test_tadjibayev_camp"
    assert enforce_prefix("test_tadjibayev_camp") == "test_tadjibayev_camp"
    assert enforce_prefix("  camp ") == "test_tadjibayev_camp"
    with pytest.raises(ServiceError):
        enforce_prefix("test_tadjibayev_")


async def test_creates_campaign_and_two_streams_in_order(session, keitaro, fake):
    campaign = await create_campaign(session, keitaro, data())

    (c_body,) = fake.calls("POST", "/campaigns")
    assert c_body["name"] == "test_tadjibayev_promo1"
    assert c_body["domain_id"] == 1813
    assert c_body["group_id"] == 10332
    assert c_body["traffic_source_id"] == 836

    s1, s2 = fake.calls("POST", "/streams")
    assert s1["campaign_id"] == s2["campaign_id"] == campaign.keitaro_id
    assert s1["position"] == 1 and s2["position"] == 2
    assert s1["schema"] == "redirect"
    assert s1["action_type"] == "http"
    assert s1["action_payload"] == "https://google.com"
    assert s1["filters"] == [{"name": "country", "mode": "accept", "payload": ["MX"]}]
    assert s2["schema"] == "landings"
    assert s2["type"] == "default"
    assert s2["filters"] == []
    assert s2["offers"] == [{"offer_id": 18002, "share": 100, "state": "active"}]

    assert campaign.name == "test_tadjibayev_promo1"
    assert campaign.geo == "MX"
    assert await session.scalar(select(func.count(StreamOffer.id))) == 1


async def test_invalid_geo_sends_nothing(session, keitaro, fake):
    with pytest.raises(ServiceError, match="ISO-2"):
        await create_campaign(session, keitaro, data(geo="XX"))
    assert fake.calls("POST", "/campaigns") == []


async def test_unknown_offer_rejected(session, keitaro, fake):
    with pytest.raises(ServiceError, match="does not exist"):
        await create_campaign(session, keitaro, data(offer_id=1))
    assert fake.calls("POST", "/campaigns") == []


async def test_stream_failure_rolls_back_campaign(session, keitaro, fake):
    fake.fail_next["stream"] = 1
    with pytest.raises(KeitaroError):
        await create_campaign(session, keitaro, data())
    assert fake.campaigns == {}
    assert len(fake.calls("DELETE", r"/campaigns/\d+")) == 1
    assert await session.scalar(select(func.count(Campaign.id))) == 0


async def test_api_create_and_error_message(api, fake):
    r = await api.post("/api/campaigns", json=dict(name="api1", geo="AU", offer_id=18000,
                                                    domain_id=1813, group_id=10332, source_id=836))
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "test_tadjibayev_api1"
    assert r.json()["editor_url"].startswith("/campaigns/")

    fake.fail_next["campaign"] = 1
    r = await api.post("/api/campaigns", json=dict(name="api2", geo="AU", offer_id=18000,
                                                    domain_id=1813, group_id=10332, source_id=836))
    assert r.status_code == 422
    assert "campaign rejected" in r.json()["detail"]
