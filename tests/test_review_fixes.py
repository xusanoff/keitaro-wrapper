"""Regression tests for issues found in the code review."""

import httpx

from app.services.sync import load_campaign, parse_offers, sync_campaign
from app.services.weights import WeightItem, push_problem
from tests.fake_keitaro import BASE
from tests.test_editor import link_id, setup, view


# ---- sync robustness -------------------------------------------------------------------
def test_parse_offers_rounds_and_merges_duplicates():
    assert parse_offers([
        {"offer_id": 1, "share": "33.5", "state": "active"},
        {"offer_id": 2, "share": 33.4, "state": "active"},
        {"offer_id": 1, "share": 33, "state": "active"},
        {"offer_id": 3, "share": 50, "state": "disabled"},
        {"share": 10},
    ]) == [(1, True, 67), (2, True, 33), (3, False, 0)]


async def test_string_and_duplicate_shares_do_not_break_fetch(session, keitaro, fake):
    cid = fake.add_campaign()
    fake.offer_stream(cid)["offers"] = [
        {"offer_id": 18000, "share": "50", "state": "active"},
        {"offer_id": 18000, "share": 25.0, "state": "active"},
        {"offer_id": 18001, "share": 25, "state": "active"},
    ]
    await sync_campaign(session, keitaro, cid)
    camp = await load_campaign(session, cid)
    stream = next(s for s in camp.streams if s.has_offers)
    assert sorted((x.offer.keitaro_id, x.share) for x in stream.links) == [(18000, 75), (18001, 25)]


async def test_offer_stream_detected_by_offers_not_only_schema(session, keitaro, fake):
    cid = fake.add_campaign()
    fake.offer_stream(cid)["schema"] = "offers"
    await sync_campaign(session, keitaro, cid)
    camp = await load_campaign(session, cid)
    assert [s.has_offers for s in sorted(camp.streams, key=lambda s: s.position)] == [False, True]


async def test_stream_losing_schema_keeps_archive(session, keitaro, fake):
    cid = fake.add_campaign()
    await sync_campaign(session, keitaro, cid)
    st = fake.offer_stream(cid)
    st["schema"], st["offers"] = "redirect", []
    await sync_campaign(session, keitaro, cid)
    camp = await load_campaign(session, cid)
    stream = next(s for s in camp.streams if s.keitaro_id == st["id"])
    assert not stream.has_offers and len(stream.links) == 2


async def test_foreign_campaign_cannot_be_fetched(api, fake):
    cid = fake.add_campaign(name="someone_else_campaign")
    r = await api.post(f"/api/campaigns/{cid}/fetch")
    assert r.status_code == 403
    assert "test_tadjibayev_" in r.json()["detail"]


async def test_campaign_list_only_shows_prefixed(api, fake):
    fake.add_campaign(name="someone_else")
    mine = fake.add_campaign(name="test_tadjibayev_mine")
    rows = (await api.get("/api/campaigns", params={"all": "true"})).json()
    assert [r["id"] for r in rows] == [mine]


# ---- push ------------------------------------------------------------------------------
async def test_disabled_offer_in_keitaro_survives_push(api, fake):
    cid, s = await setup(api, fake, offers=((18000, 100),))
    fake.offer_stream(cid)["offers"].append({"offer_id": 18001, "share": 40, "state": "disabled"})
    s = next(x for x in (await api.post(f"/api/campaigns/{cid}/fetch")).json()["campaign"]["streams"] if x["has_offers"])
    assert (18001, "removed", 0) in view(s)
    await api.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 18002})
    r = await api.post(f"/api/streams/{s['id']}/push")
    assert r.status_code == 200, r.text
    offers = {o["offer_id"]: (o["state"], o["share"]) for o in fake.offer_stream(cid)["offers"]}
    assert offers == {18000: ("active", 50), 18002: ("active", 50), 18001: ("disabled", 40)}


async def test_retry_after_keitaro_already_applied_is_not_a_conflict(api, fake):
    cid, s = await setup(api, fake, offers=((18000, 100),))
    await api.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 18001})
    # simulate: PUT reached Keitaro, but our side failed before saving
    fake.offer_stream(cid)["offers"] = [
        {"offer_id": 18000, "share": 50, "state": "active"},
        {"offer_id": 18001, "share": 50, "state": "active"},
    ]
    r = await api.post(f"/api/streams/{s['id']}/push")
    assert r.status_code == 200, r.text
    assert not r.json()["is_dirty"]
    assert fake.calls("PUT", r"/streams/\d+") == []


async def test_added_then_removed_in_one_draft_is_dropped_on_push(api, fake):
    cid, s = await setup(api, fake)
    sid = s["id"]
    s = (await api.post(f"/api/streams/{sid}/offers", json={"offer_id": 18003})).json()
    await api.post(f"/api/streams/{sid}/offers/{link_id(s, 18003)}/remove")
    await api.post(f"/api/streams/{sid}/offers/{link_id(s, 18000)}/remove")
    s = (await api.post(f"/api/streams/{sid}/push")).json()
    assert [o["offer_id"] for o in s["offers"]] == [18000, 18001, 18002]  # 18003 never reached Keitaro


async def test_put_without_offers_in_response_falls_back_to_get(api, fake):
    cid, s = await setup(api, fake)
    await api.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 18003})
    real = fake._update_stream

    def update_no_body(r, sid):
        real(r, sid)
        return httpx.Response(200, json={"success": True})

    fake.mock_router.put(url__regex=rf"{BASE}/streams/(?P<sid>\d+)$").mock(side_effect=update_no_body)
    r = await api.post(f"/api/streams/{s['id']}/push")
    assert r.status_code == 200, r.text
    assert fake.shares(cid) == {18000: 25, 18001: 25, 18002: 25, 18003: 25}


async def test_keitaro_returning_other_weights_is_reported(api, fake):
    cid, s = await setup(api, fake)
    await api.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 18003})

    def lying_update(r, sid):
        fake._log(r)
        return httpx.Response(200, json={"id": int(sid), "offers": [{"offer_id": 18000, "share": 100, "state": "active"}]})

    fake.mock_router.put(url__regex=rf"{BASE}/streams/(?P<sid>\d+)$").mock(side_effect=lying_update)
    r = await api.post(f"/api/streams/{s['id']}/push")
    assert r.status_code == 502
    assert "Fetch streams" in r.json()["detail"]


async def test_push_to_deleted_stream_is_conflict(api, fake):
    cid, s = await setup(api, fake)
    await api.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 18003})
    del fake.streams[fake.offer_stream(cid)["id"]]
    r = await api.post(f"/api/streams/{s['id']}/push")
    assert r.status_code == 409
    assert "deleted" in r.json()["detail"]


async def test_unpin_redistributes(api, fake):
    _, s = await setup(api, fake)
    sid = s["id"]
    s = (await api.put(f"/api/streams/{sid}/offers/{link_id(s, 18000)}/pin", json={"pinned": True, "share": 10})).json()
    assert view(s) == [(18000, "active", 10), (18001, "active", 45), (18002, "active", 45)]
    s = (await api.put(f"/api/streams/{sid}/offers/{link_id(s, 18000)}/pin", json={"pinned": False})).json()
    assert view(s) == [(18000, "active", 34), (18001, "active", 33), (18002, "active", 33)]
    assert not s["is_dirty"]


def test_active_offer_at_zero_blocks_push():
    items = [WeightItem("active", True, 100), WeightItem("active", False, 0)]
    assert "0%" in push_problem(items)


# ---- misc ------------------------------------------------------------------------------
async def test_new_offer_found_despite_cache(api, fake):
    cid, s = await setup(api, fake)
    await api.get("/api/offers")  # warm the cache
    fake.offers.append({"id": 19999, "name": "Brand new"})
    r = await api.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 19999})
    assert r.status_code == 200, r.text


async def test_bad_api_key_message(api, fake):
    fake.mock_router.get(f"{BASE}/offers").respond(401, json={"error": "Unauthorized"})
    r = await api.get("/api/offers")
    assert r.status_code == 502
    assert "API key" in r.json()["detail"]


async def test_offers_limit_validated(api, fake):
    r = await api.get("/api/offers", params={"limit": -1})
    assert r.status_code == 422
