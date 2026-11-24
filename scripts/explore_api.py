"""Dump real responses of the Keitaro emulator into docs/api_samples/ (read-only calls).

    python -m scripts.explore_api            # catalog + your campaigns and their streams

Uses KEITARO_URL / KEITARO_API_KEY from .env. Offer catalog is truncated to 5 rows.
"""

import asyncio
import json
from pathlib import Path

from app.keitaro.client import KeitaroClient

OUT = Path(__file__).resolve().parent.parent / "docs" / "api_samples"


def dump(name: str, data) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"saved {name}.json")


async def main() -> None:
    async with KeitaroClient() as k:
        dump("offers", (await k.list_offers())[:5])
        dump("domains", await k.list_domains())
        dump("groups", await k.list_groups())
        dump("traffic_sources", await k.list_traffic_sources())
        campaigns = await k.list_campaigns()
        dump("campaigns", campaigns[:3])
        for c in campaigns[:1]:
            dump("campaign", await k.get_campaign(c["id"]))
            streams = await k.list_streams(c["id"])
            dump("campaign_streams", streams)
            if streams:
                dump("stream", await k.get_stream(streams[0]["id"]))


if __name__ == "__main__":
    asyncio.run(main())
