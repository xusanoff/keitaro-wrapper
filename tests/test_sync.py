from sqlalchemy import func, select

from app.models import Offer, Stream, StreamOffer
from app.services.sync import load_campaign, sync_campaign


def offers_of(campaign):
    stream = next(s for s in campaign.streams if s.has_offers)
    return stream, {link.offer.keitaro_id: (link.status.value, link.share) for link in stream.links}


async def test_fetch_stores_streams(session, keitaro, fake):
    cid = fake.add_campaign(offers=((18000, 70), (18001, 30)))
    report = await sync_campaign(session, keitaro, cid)
    assert report.streams_total == 2
    campaign = await load_campaign(session, cid)
    geo, offers = sorted(campaign.streams, key=lambda s: s.position)
    assert not geo.has_offers and geo.links == [] and geo.name == "MX → Google"
    assert offers.has_offers
    # Keitaro weights are the truth for clean streams (no recalculation)
    assert offers_of(campaign)[1] == {18000: ("active", 70), 18001: ("active", 30)}
    assert not offers.is_dirty


async def test_offer_less_stream_has_no_details(session, keitaro, fake):
    cid = fake.add_campaign()
    await sync_campaign(session, keitaro, cid)
    geo = await session.scalar(select(Stream).where(Stream.has_offers.is_(False)))
    assert set(Stream.__table__.columns.keys()) >= {"name", "position"}
    assert not hasattr(geo, "filters") and not hasattr(geo, "action_payload")
    assert await session.scalar(select(func.count(StreamOffer.id)).where(StreamOffer.stream_id == geo.id)) == 0


async def test_offer_deleted_in_keitaro_becomes_removed(session, keitaro, fake):
    cid = fake.add_campaign(offers=((18000, 34), (18001, 33), (18002, 33)))
    await sync_campaign(session, keitaro, cid)

    fake.offer_stream(cid)["offers"] = [{"offer_id": 18000, "share": 100, "state": "active"}]
    report = await sync_campaign(session, keitaro, cid)

    assert report.offers_marked_removed == 2
    _, offers = offers_of(await load_campaign(session, cid))
    assert offers == {18000: ("active", 100), 18001: ("removed", 0), 18002: ("removed", 0)}
    assert await session.scalar(select(func.count(Offer.id))) == 3  # nothing deleted


async def test_new_offer_in_keitaro_is_added(session, keitaro, fake):
    cid = fake.add_campaign(offers=((18000, 100),))
    await sync_campaign(session, keitaro, cid)
    fake.offer_stream(cid)["offers"] = [
        {"offer_id": 18000, "share": 60, "state": "active"},
        {"offer_id": 18005, "share": 40, "state": "active"},
    ]
    report = await sync_campaign(session, keitaro, cid)
    assert report.offers_added == 1
    stream, offers = offers_of(await load_campaign(session, cid))
    assert offers == {18000: ("active", 60), 18005: ("active", 40)}
    new = next(link for link in stream.links if link.offer.keitaro_id == 18005)
    assert new.offer.name == "Offer Foxtrot"


async def test_removed_offer_readded_in_keitaro_becomes_active(session, keitaro, fake):
    cid = fake.add_campaign(offers=((18000, 50), (18001, 50)))
    await sync_campaign(session, keitaro, cid)
    fake.offer_stream(cid)["offers"] = [{"offer_id": 18000, "share": 100, "state": "active"}]
    await sync_campaign(session, keitaro, cid)
    fake.offer_stream(cid)["offers"].append({"offer_id": 18001, "share": 0, "state": "active"})
    fake.offer_stream(cid)["offers"][0]["share"] = 100
    await sync_campaign(session, keitaro, cid)
    _, offers = offers_of(await load_campaign(session, cid))
    assert offers[18001] == ("active", 0)


async def test_dirty_stream_is_not_overwritten(api, fake):
    cid = fake.add_campaign(offers=((18000, 100),))
    await api.post(f"/api/campaigns/{cid}/fetch")
    camp = (await api.get(f"/api/campaigns/{cid}")).json()
    sid = next(s["id"] for s in camp["streams"] if s["has_offers"])
    await api.post(f"/api/streams/{sid}/offers", json={"offer_id": 18001})

    fake.offer_stream(cid)["offers"] = []  # external change
    r = (await api.post(f"/api/campaigns/{cid}/fetch")).json()
    assert r["skipped_dirty"] == ["Offers"]
    stream = next(s for s in r["campaign"]["streams"] if s["id"] == sid)
    assert stream["is_dirty"]
    assert [(o["offer_id"], o["share"], o["status"]) for o in stream["offers"]] == [
        (18000, 50, "active"), (18001, 50, "active")
    ]


async def test_stream_deleted_in_keitaro_is_deleted_locally(session, keitaro, fake):
    cid = fake.add_campaign()
    await sync_campaign(session, keitaro, cid)
    geo_id = next(s for s in fake.streams.values() if s["campaign_id"] == cid and s["schema"] == "redirect")["id"]
    del fake.streams[geo_id]
    report = await sync_campaign(session, keitaro, cid)
    assert report.deleted_streams == ["MX → Google"]
    assert len((await load_campaign(session, cid)).streams) == 1


async def test_fetch_unknown_campaign_404(api, fake):
    r = await api.post("/api/campaigns/999999/fetch")
    assert r.status_code == 404
