import pytest
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.config import Settings, get_settings
from app.db import Base, get_session
from app.keitaro.client import KeitaroClient, get_keitaro
from app.main import app
from app.services import offers as offer_svc
from tests.fake_keitaro import FakeKeitaro

TEST_SETTINGS = Settings(
    _env_file=None,
    keitaro_url="https://keitaro.test",
    keitaro_api_key="test-key",
    keitaro_retries=0,
    database_url="sqlite+aiosqlite://",
)


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def session(session_factory):
    async with session_factory() as s:
        yield s


@pytest.fixture
def fake():
    offer_svc.clear_cache()
    with respx.mock(assert_all_called=False) as mock:
        yield FakeKeitaro(mock)


@pytest.fixture
async def keitaro(fake):
    client = KeitaroClient(TEST_SETTINGS)
    yield client
    await client.aclose()


@pytest.fixture
async def api(session_factory, fake):
    async def _session():
        async with session_factory() as s:
            yield s

    async def _keitaro():
        c = KeitaroClient(TEST_SETTINGS)
        try:
            yield c
        finally:
            await c.aclose()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_keitaro] = _keitaro
    app.dependency_overrides[get_settings] = lambda: TEST_SETTINGS
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://app") as client:
        yield client
    app.dependency_overrides.clear()
