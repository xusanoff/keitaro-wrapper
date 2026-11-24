"""Tiny offline stand-in for the Keitaro emulator (dev/demo only).

    uvicorn scripts.mock_keitaro:app --port 9000
    KEITARO_URL=http://127.0.0.1:9000 KEITARO_API_KEY=dev uvicorn app.main:app

Implements just the endpoints the wrapper uses, with the emulator's field names.
"""

from itertools import count

from fastapi import FastAPI, Header, HTTPException

app = FastAPI(title="mock keitaro")
P = "/admin_api/v1"
_ids = count(1000)
OFFERS = [{"id": 18000 + i, "name": n} for i, n in enumerate(
    ["Keto Slim MX", "Vita Joint AU", "Cardio Balance RO", "Hondrox MX", "Night Lift ES", "Gluco Norm PL",
     "Prosta Fix IT", "Visio Plus FR", "Fungi Stop DE", "Hair Boost BR", "Detox Max PE", "Flex Pro CL"])]
CAMPAIGNS: dict[int, dict] = {}
STREAMS: dict[int, dict] = {}


def auth(key):
    if not key:
        raise HTTPException(401, "Unauthorized")


@app.get(P + "/offers")
def offers(api_key: str | None = Header(None, alias="Api-Key")):
    auth(api_key)
    return OFFERS


@app.get(P + "/domains")
def domains(api_key: str | None = Header(None, alias="Api-Key")):
    auth(api_key)
    return [{"id": 1813, "name": "fortests.example"}]


@app.get(P + "/groups")
def groups(api_key: str | None = Header(None, alias="Api-Key")):
    auth(api_key)
    return [{"id": 10332, "name": "FORTESTS"}]


@app.get(P + "/traffic_sources")
def sources(api_key: str | None = Header(None, alias="Api-Key")):
    auth(api_key)
    return [{"id": 836, "name": "FORTESTS"}]


@app.get(P + "/campaigns")
def campaigns(api_key: str | None = Header(None, alias="Api-Key")):
    auth(api_key)
    return sorted(CAMPAIGNS.values(), key=lambda c: -c["id"])


@app.post(P + "/campaigns")
def create_campaign(body: dict, api_key: str | None = Header(None, alias="Api-Key")):
    auth(api_key)
    if not body.get("name"):
        raise HTTPException(400, "name is required")
    cid = next(_ids)
    CAMPAIGNS[cid] = {"id": cid, "alias": f"c{cid}", "state": "active", **body}
    return CAMPAIGNS[cid]


@app.get(P + "/campaigns/{cid}")
def get_campaign(cid: int, api_key: str | None = Header(None, alias="Api-Key")):
    auth(api_key)
    if cid not in CAMPAIGNS:
        raise HTTPException(404, "Campaign not found")
    return CAMPAIGNS[cid]


@app.delete(P + "/campaigns/{cid}")
def delete_campaign(cid: int, api_key: str | None = Header(None, alias="Api-Key")):
    auth(api_key)
    CAMPAIGNS.pop(cid, None)
    for sid in [s for s, v in STREAMS.items() if v["campaign_id"] == cid]:
        del STREAMS[sid]
    return {"success": True}


@app.get(P + "/campaigns/{cid}/streams")
def list_streams(cid: int, api_key: str | None = Header(None, alias="Api-Key")):
    auth(api_key)
    return sorted((s for s in STREAMS.values() if s["campaign_id"] == cid), key=lambda s: s["position"])


@app.post(P + "/streams")
def create_stream(body: dict, api_key: str | None = Header(None, alias="Api-Key")):
    auth(api_key)
    sid = next(_ids)
    STREAMS[sid] = {"id": sid, "type": "regular", "state": "active", "filters": [], "offers": [], **body}
    return STREAMS[sid]


@app.get(P + "/streams/{sid}")
def get_stream(sid: int, api_key: str | None = Header(None, alias="Api-Key")):
    auth(api_key)
    if sid not in STREAMS:
        raise HTTPException(404, "Stream not found")
    return STREAMS[sid]


@app.put(P + "/streams/{sid}")
def update_stream(sid: int, body: dict, api_key: str | None = Header(None, alias="Api-Key")):
    auth(api_key)
    if sid not in STREAMS:
        raise HTTPException(404, "Stream not found")
    STREAMS[sid].update(body)
    return STREAMS[sid]
