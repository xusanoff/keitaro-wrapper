import pytest

from tests.fake_keitaro import FakeKeitaro


async def setup(api, fake: FakeKeitaro, offers=((18000, 34), (18001, 33), (18002, 33))):
    cid = fake.add_campaign(offers=offers)
    r = await api.post(f"/api/campaigns/{cid}/fetch")
    assert r.status_code == 200, r.text
    stream = next(s for s in r.json()["campaign"]["streams"] if s["has_offers"])
    return cid, stream


def view(stream):
    return [(o["offer_id"], o["status"], o["share"]) for o in stream["offers"]]


def link_id(stream, offer_id):
    return next(o["id"] for o in stream["offers"] if o["offer_id"] == offer_id)


async def test_add_recalculates_and_marks_dirty_without_touching_keitaro(api, fake):
    cid, s = await setup(api, fake)
    s = (await api.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 18003})).json()
    assert view(s) == [(18000, "active", 25), (18001, "active", 25), (18002, "active", 25), (18003, "active", 25)]
    assert s["is_dirty"]
    assert fake.shares(cid) == {18000: 34, 18001: 33, 18002: 33}
    assert fake.calls("PUT", r"/streams/\d+") == []


async def test_add_then_cancel_is_clean_again(api, fake):
    cid, s = await setup(api, fake)
    sid = s["id"]
    await api.post(f"/api/streams/{sid}/offers", json={"offer_id": 18003})
    s = (await api.post(f"/api/streams/{sid}/cancel")).json()
    assert not s["is_dirty"]
    assert view(s) == [(18000, "active", 34), (18001, "active", 33), (18002, "active", 33)]


async def test_add_duplicate_is_error(api, fake):
    _, s = await setup(api, fake)
    r = await api.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 18000})
    assert r.status_code == 400
    assert "already" in r.json()["detail"]


async def test_add_push_matches_keitaro(api, fake):
    cid, s = await setup(api, fake)
    sid = s["id"]
    await api.post(f"/api/streams/{sid}/offers", json={"offer_id": 18003})
    s = (await api.post(f"/api/streams/{sid}/push")).json()
    assert not s["is_dirty"]
    assert fake.shares(cid) == {18000: 25, 18001: 25, 18002: 25, 18003: 25}


async def test_remove_push_archives_offer(api, fake):
    cid, s = await setup(api, fake)
    sid = s["id"]
    s = (await api.post(f"/api/streams/{sid}/offers/{link_id(s, 18001)}/remove")).json()
    assert view(s) == [(18000, "active", 50), (18001, "removed", 0), (18002, "active", 50)]
    assert s["is_dirty"]
    s = (await api.post(f"/api/streams/{sid}/push")).json()
    assert fake.shares(cid) == {18000: 50, 18002: 50}  # gone from Keitaro
    assert (18001, "removed", 0) in view(s)  # kept in our DB as archived
    assert not s["is_dirty"]

    # Fetch keeps it archived
    r = (await api.post(f"/api/campaigns/{cid}/fetch")).json()
    st = next(x for x in r["campaign"]["streams"] if x["id"] == sid)
    assert (18001, "removed", 0) in view(st)


async def test_bring_back_push_restores_offer(api, fake):
    cid, s = await setup(api, fake)
    sid = s["id"]
    await api.post(f"/api/streams/{sid}/offers/{link_id(s, 18001)}/remove")
    s = (await api.post(f"/api/streams/{sid}/push")).json()
    s = (await api.post(f"/api/streams/{sid}/offers/{link_id(s, 18001)}/restore")).json()
    assert s["is_dirty"]
    assert view(s) == [(18000, "active", 34), (18001, "active", 33), (18002, "active", 33)]
    await api.post(f"/api/streams/{sid}/push")
    assert fake.shares(cid) == {18000: 34, 18001: 33, 18002: 33}


async def test_remove_then_cancel_restores(api, fake):
    _, s = await setup(api, fake)
    sid = s["id"]
    await api.post(f"/api/streams/{sid}/offers/{link_id(s, 18000)}/remove")
    s = (await api.post(f"/api/streams/{sid}/cancel")).json()
    assert view(s) == [(18000, "active", 34), (18001, "active", 33), (18002, "active", 33)]
    assert not s["is_dirty"]


async def test_pinned_weight_video_scenario(api, fake):
    """Pin one offer at 25 %, bring back another: the other two share 75 % evenly."""
    cid, s = await setup(api, fake)
    sid = s["id"]
    await api.post(f"/api/streams/{sid}/offers/{link_id(s, 18002)}/remove")
    s = (await api.post(f"/api/streams/{sid}/push")).json()
    assert fake.shares(cid) == {18000: 50, 18001: 50}

    s = (await api.put(f"/api/streams/{sid}/offers/{link_id(s, 18000)}/pin", json={"pinned": True, "share": 25})).json()
    assert view(s)[:2] == [(18000, "active", 25), (18001, "active", 75)]
    s = (await api.post(f"/api/streams/{sid}/offers/{link_id(s, 18002)}/restore")).json()
    assert view(s) == [(18000, "active", 25), (18001, "active", 38), (18002, "active", 37)]
    assert next(o for o in s["offers"] if o["offer_id"] == 18000)["pinned"]

    s = (await api.post(f"/api/streams/{sid}/push")).json()
    assert fake.shares(cid) == {18000: 25, 18001: 38, 18002: 37}
    assert sum(fake.shares(cid).values()) == 100


async def test_pin_over_100_rejected_and_nothing_saved(api, fake):
    cid, s = await setup(api, fake)
    sid = s["id"]
    await api.put(f"/api/streams/{sid}/offers/{link_id(s, 18000)}/pin", json={"pinned": True, "share": 60})
    r = await api.put(f"/api/streams/{sid}/offers/{link_id(s, 18001)}/pin", json={"pinned": True, "share": 50})
    assert r.status_code == 422
    assert "more than 100" in r.json()["detail"]
    s = (await api.get(f"/api/campaigns/{cid}")).json()
    st = next(x for x in s["streams"] if x["id"] == sid)
    assert [o["pinned"] for o in st["offers"]] == [True, False, False]


async def test_all_pinned_not_100_blocks_push(api, fake):
    _, s = await setup(api, fake, offers=((18000, 50), (18001, 50)))
    sid = s["id"]
    await api.put(f"/api/streams/{sid}/offers/{link_id(s, 18000)}/pin", json={"pinned": True, "share": 60})
    s = (await api.put(f"/api/streams/{sid}/offers/{link_id(s, 18001)}/pin", json={"pinned": True, "share": 30})).json()
    assert s["problem"] and "100" in s["problem"]
    r = await api.post(f"/api/streams/{sid}/push")
    assert r.status_code == 422
    assert fake.calls("PUT", r"/streams/\d+") == []


async def test_removed_offer_cannot_be_pinned_and_is_unpinned(api, fake):
    _, s = await setup(api, fake)
    sid = s["id"]
    lid = link_id(s, 18000)
    await api.put(f"/api/streams/{sid}/offers/{lid}/pin", json={"pinned": True, "share": 10})
    s = (await api.post(f"/api/streams/{sid}/offers/{lid}/remove")).json()
    assert next(o for o in s["offers"] if o["id"] == lid)["pinned"] is False
    r = await api.put(f"/api/streams/{sid}/offers/{lid}/pin", json={"pinned": True, "share": 10})
    assert r.status_code == 400


async def test_zero_active_offers_blocks_push(api, fake):
    _, s = await setup(api, fake, offers=((18000, 100),))
    sid = s["id"]
    s = (await api.post(f"/api/streams/{sid}/offers/{link_id(s, 18000)}/remove")).json()
    assert s["problem"] and "no active offers" in s["problem"]
    r = await api.post(f"/api/streams/{sid}/push")
    assert r.status_code == 422


async def test_rejected_push_keeps_stream_dirty(api, fake):
    cid, s = await setup(api, fake)
    sid = s["id"]
    await api.post(f"/api/streams/{sid}/offers", json={"offer_id": 18003})
    fake.fail_next["update"] = 1
    r = await api.post(f"/api/streams/{sid}/push")
    assert r.status_code == 422
    assert "update rejected" in r.json()["detail"]
    camp = (await api.get(f"/api/campaigns/{cid}")).json()
    assert next(x for x in camp["streams"] if x["id"] == sid)["is_dirty"]


async def test_push_detects_external_change(api, fake):
    cid, s = await setup(api, fake)
    sid = s["id"]
    await api.post(f"/api/streams/{sid}/offers", json={"offer_id": 18003})
    fake.offer_stream(cid)["offers"].pop()  # someone edited Keitaro meanwhile
    r = await api.post(f"/api/streams/{sid}/push")
    assert r.status_code == 409
    r = await api.post(f"/api/streams/{sid}/push", json={"force": True})
    assert r.status_code == 200
    assert fake.shares(cid) == {18000: 25, 18001: 25, 18002: 25, 18003: 25}


async def test_pin_only_change_is_not_dirty(api, fake):
    _, s = await setup(api, fake, offers=((18000, 50), (18001, 50)))
    s = (await api.put(f"/api/streams/{s['id']}/offers/{link_id(s, 18000)}/pin", json={"pinned": True})).json()
    assert not s["is_dirty"]
    assert view(s) == [(18000, "active", 50), (18001, "active", 50)]


@pytest.mark.parametrize("n_extra", [1, 2, 5])
async def test_numbers_match_keitaro_after_push_and_fetch(api, fake, n_extra):
    cid, s = await setup(api, fake)
    sid = s["id"]
    for i in range(n_extra):
        s = (await api.post(f"/api/streams/{sid}/offers", json={"offer_id": 18003 + i})).json()
    s = (await api.post(f"/api/streams/{sid}/push")).json()
    ours = {o["offer_id"]: o["share"] for o in s["offers"] if o["status"] == "active"}
    assert ours == fake.shares(cid)
    assert sum(ours.values()) == 100
    r = (await api.post(f"/api/campaigns/{cid}/fetch")).json()
    st = next(x for x in r["campaign"]["streams"] if x["id"] == sid)
    assert {o["offer_id"]: o["share"] for o in st["offers"] if o["status"] == "active"} == ours
