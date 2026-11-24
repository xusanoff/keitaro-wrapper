from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    keitaro_url: str = "https://keitaro-for-tests.etolegko.com"
    keitaro_api_key: str = ""
    keitaro_timeout: float = 15.0
    keitaro_retries: int = 2

    default_domain_id: int | None = 1813
    default_group_id: int | None = 10332
    default_source_id: int | None = 836

    campaign_prefix: str = "test_tadjibayev_"
    database_url: str = "sqlite+aiosqlite:///./keitaro_wrapper.db"

    offers_cache_ttl: float = Field(default=60.0, description="Seconds to cache the Keitaro offer catalog")

    @field_validator("keitaro_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def keitaro_api_base(self) -> str:
        return f"{self.keitaro_url}/admin_api/v1"

    def keitaro_campaign_link(self, keitaro_id: int) -> str:
        return f"{self.keitaro_url}/admin/#!/campaign.editor/{keitaro_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
