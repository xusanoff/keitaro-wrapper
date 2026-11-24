import httpx
import pytest
import respx

from app.config import Settings
from app.keitaro.client import KeitaroClient, KeitaroError


def settings(**kw):
    return Settings(_env_file=None, keitaro_url="https://k.test/", keitaro_api_key="secret", **kw)


async def test_sends_api_key_and_parses_json():
    with respx.mock() as m:
        route = m.get("https://k.test/admin_api/v1/offers").respond(json=[{"id": 1, "name": "A"}])
        async with KeitaroClient(settings()) as c:
            assert await c.list_offers() == [{"id": 1, "name": "A"}]
        assert route.calls.last.request.headers["Api-Key"] == "secret"


async def test_retries_get_on_5xx():
    with respx.mock() as m:
        route = m.get("https://k.test/admin_api/v1/domains").mock(
            side_effect=[httpx.Response(502), httpx.Response(200, json=[])]
        )
        async with KeitaroClient(settings(keitaro_retries=2)) as c:
            assert await c.list_domains() == []
        assert route.call_count == 2


async def test_does_not_retry_post():
    with respx.mock() as m:
        route = m.post("https://k.test/admin_api/v1/campaigns").respond(503, json={"error": "down"})
        async with KeitaroClient(settings(keitaro_retries=2)) as c:
            with pytest.raises(KeitaroError) as e:
                await c.create_campaign({"name": "x"})
        assert route.call_count == 1
        assert e.value.status_code == 503


async def test_error_message_extracted():
    with respx.mock() as m:
        m.put("https://k.test/admin_api/v1/streams/5").respond(400, json={"error": "Bad share"})
        async with KeitaroClient(settings()) as c:
            with pytest.raises(KeitaroError, match="Bad share"):
                await c.update_stream(5, {})


async def test_missing_key():
    async with KeitaroClient(Settings(_env_file=None, keitaro_api_key="")) as c:
        with pytest.raises(KeitaroError, match="KEITARO_API_KEY"):
            await c.list_offers()
