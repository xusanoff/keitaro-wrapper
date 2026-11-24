"""In-memory Keitaro emulator mounted on respx, shaped like the real emulator responses."""

from __future__ import annotations

import json
import re
from itertools import count

import httpx
import respx

BASE = "https://keitaro.test/admin_api/v1"


class FakeKeitaro:
    def __init__(self, mock: respx.MockRouter):
        self.offers = [{"id": 18000 + i, "name": f"Offer {name}"} for i, name in enumerate(
            ["Alpha MX", "Bravo AU", "Charlie RO", "Delta MX", "Echo", "Foxtrot", "Golf"]
        )]
        self.campaigns: dict[int, dict] = {}
        self.streams: dict[int, dict] = {}
        self.requests: list[tuple[str, str, dict | None]] = []
        self.fail_next: dict[str, int] = {}
        self._ids = count(500)
        m = mock
        m.get(f"{BASE}/offers").mock(side_effect=lambda r: self._ok(r, self.offers))
        m.get(f"{BASE}/domains").mock(side_effect=lambda r: self._ok(r, [{"id": 1813, "name": "test.example"}]))
        m.get(f"{BASE}/groups").mock(side_effect=lambda r: self._ok(r, [{"id": 10332, "name": "FORTESTS"}]))
        m.get(f"{BASE}/traffic_sources").mock(side_effect=lambda r: self._ok(r, [{"id": 836, "name": "FORTESTS"}]))
        m.get(f"{BASE}/campaigns").mock(side_effect=lambda r: self._ok(r, list(self.campaigns.values())))
        m.post(f"{BASE}/campaigns").mock(side_effect=self._create_campaign)
        m.get(url__regex=rf"{BASE}/campaigns/(?P<cid>\d+)/streams$").mock(side_effect=self._list_streams)
        m.get(url__regex=rf"{BASE}/campaigns/(?P<cid>\d+)$").mock(side_effect=self._get_campaign)
        m.delete(url__regex=rf"{BASE}/campaigns/(?P<cid>\d+)$").mock(side_effect=self._delete_campaign)
        m.post(f"{BASE}/streams").mock(side_effect=self._create_stream)
        m.get(url__regex=rf"{BASE}/streams/(?P<sid>\d+)$").mock(side_effect=self._get_stream)
        m.put(url__regex=rf"{BASE}/streams/(?P<sid>\d+)$").mock(side_effect=self._update_stream)

    # helpers -------------------------------------------------------------------
    def _log(self, r: httpx.Request) -> dict | None:
        body = json.loads(r.content) if r.content else None
        self.requests.append((r.method, r.url.path.replace("/admin_api/v1", ""), body))
        return body

    def _ok(self, r, data, status=200):
        self._log(r)
        return httpx.Response(status, json=data)

    def _maybe_fail(self, key: str):
        if self.fail_next.get(key):
            self.fail_next[key] -= 1
            return httpx.Response(400, json={"error": f"{key} rejected"})
        return None

    def calls(self, method: str, path_re: str) -> list[dict | None]:
        return [b for m, p, b in self.requests if m == method and re.fullmatch(path_re, p)]

    # handlers ------------------------------------------------------------------
    def _create_campaign(self, r):
        body = self._log(r)
        if fail := self._maybe_fail("campaign"):
            return fail
        cid = next(self._ids)
        self.campaigns[cid] = {"id": cid, "alias": f"a{cid}", "state": "active", **body}
        return httpx.Response(200, json=self.campaigns[cid])

    def _get_campaign(self, r, cid):
        self._log(r)
        c = self.campaigns.get(int(cid))
        return httpx.Response(200, json=c) if c else httpx.Response(404, json={"error": "Not found"})

    def _delete_campaign(self, r, cid):
        self._log(r)
        self.campaigns.pop(int(cid), None)
        for sid in [s for s, v in self.streams.items() if v["campaign_id"] == int(cid)]:
            del self.streams[sid]
        return httpx.Response(200, json={"success": True})

    def _list_streams(self, r, cid):
        self._log(r)
        rows = [s for s in self.streams.values() if s["campaign_id"] == int(cid)]
        return httpx.Response(200, json=sorted(rows, key=lambda s: s["position"]))

    def _create_stream(self, r):
        body = self._log(r)
        if fail := self._maybe_fail("stream"):
            return fail
        sid = next(self._ids)
        stream = {"id": sid, "filters": [], "offers": [], "action_payload": None, **body}
        self.streams[sid] = stream
        return httpx.Response(200, json=stream)

    def _get_stream(self, r, sid):
        self._log(r)
        s = self.streams.get(int(sid))
        return httpx.Response(200, json=s) if s else httpx.Response(404, json={"error": "Not found"})

    def _update_stream(self, r, sid):
        body = self._log(r)
        if fail := self._maybe_fail("update"):
            return fail
        s = self.streams[int(sid)]
        s.update(body)
        return httpx.Response(200, json=s)

    # test setup helpers ------------------------------------------------------------
    def add_campaign(self, name="test_tadjibayev_x", offers=((18000, 50), (18001, 50))) -> int:
        cid = next(self._ids)
        self.campaigns[cid] = {"id": cid, "name": name, "state": "active", "domain_id": 1813,
                               "group_id": 10332, "traffic_source_id": 836}
        geo = next(self._ids)
        self.streams[geo] = {"id": geo, "campaign_id": cid, "name": "MX → Google", "type": "regular",
                             "position": 1, "schema": "redirect", "action_type": "http",
                             "action_payload": "https://google.com",
                             "filters": [{"name": "country", "mode": "accept", "payload": ["MX"]}], "offers": []}
        st = next(self._ids)
        self.streams[st] = {"id": st, "campaign_id": cid, "name": "Offers", "type": "default", "position": 2,
                            "schema": "landings", "action_type": "http", "action_payload": None, "filters": [],
                            "offers": [{"offer_id": o, "share": s, "state": "active"} for o, s in offers]}
        return cid

    def offer_stream(self, cid: int) -> dict:
        return next(s for s in self.streams.values() if s["campaign_id"] == cid and s["schema"] == "landings")

    def shares(self, cid: int) -> dict[int, int]:
        return {o["offer_id"]: o["share"] for o in self.offer_stream(cid)["offers"]}
