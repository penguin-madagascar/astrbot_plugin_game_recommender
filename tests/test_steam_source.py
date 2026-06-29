from __future__ import annotations

import unittest
from typing import Any

from astrbot_plugin_game_recommender.clients.steam import SteamClient


class SteamClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_games_parses_steam_details_and_uses_cache(self) -> None:
        cache = MemoryCache()
        http_client = FakeHttpClient(
            {
                "https://store.steampowered.com/api/storesearch/": {
                    "items": [
                        {"id": 123, "name": "Co-op Test Game"},
                        {"appid": 456, "name": "Other Game"},
                    ]
                },
                "https://store.steampowered.com/api/appdetails": {
                    "123": {"success": True, "data": steam_detail_payload()},
                    "456": {
                        "success": True,
                        "data": {**steam_detail_payload(), "name": "Other Game"},
                    },
                },
            }
        )
        client = SteamClient(http_client, cache, cache_ttl_hours=24)

        games = await client.search_games(
            search="co-op",
            platforms=["steam"],
            genres=["action"],
            tags=["co-op"],
            page_size=2,
        )

        self.assertEqual([game.title for game in games], ["Co-op Test Game", "Other Game"])
        first = games[0]
        self.assertEqual(first.appid, 123)
        self.assertEqual(first.platforms, ["pc", "macos", "linux"])
        self.assertIn("action", first.genres)
        self.assertIn("co-op", first.tags)
        self.assertIn("simplified chinese", first.tags)
        self.assertEqual(first.metacritic, 88)
        self.assertEqual(first.released, "2026 年 1 月 1 日")
        self.assertEqual(first.release_date, "2026 年 1 月 1 日")
        self.assertEqual(first.raw_url, "https://store.steampowered.com/app/123/")
        self.assertIn("Steam description", first.description or "")
        self.assertTrue(cache.keys)
        self.assertTrue(all(key.startswith("steam:") for key in cache.keys))

        await client.search_games(search="co-op", page_size=2)

        self.assertEqual(http_client.call_count, 3)

    async def test_review_summary_parses_total_and_recent_positive_ratio(self) -> None:
        cache = MemoryCache()
        http_client = FakeHttpClient(
            {
                "https://store.steampowered.com/appreviews/123": {
                    "success": 1,
                    "query_summary": {
                        "total_reviews": 100,
                        "total_positive": 78,
                    },
                },
            }
        )
        client = SteamClient(http_client, cache, cache_ttl_hours=24)

        summary = await client.get_review_summary(123)

        self.assertEqual(summary.total_reviews, 100)
        self.assertEqual(summary.positive_ratio, 0.78)
        self.assertEqual(summary.recent_positive_ratio, 0.78)
        self.assertTrue(any(key.startswith("steam:") for key in cache.keys))


def steam_detail_payload() -> dict[str, Any]:
    return {
        "name": "Co-op Test Game",
        "short_description": "Steam description",
        "type": "game",
        "platforms": {"windows": True, "mac": True, "linux": True},
        "genres": [{"description": "Action"}, {"description": "Adventure"}],
        "categories": [{"description": "Co-op"}, {"description": "Online Co-op"}],
        "supported_languages": "English, Simplified Chinese, Japanese",
        "metacritic": {"score": 88},
        "release_date": {"date": "2026 年 1 月 1 日", "coming_soon": False},
    }


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeHttpClient:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.call_count = 0

    async def get(self, url: str, params: dict[str, Any]) -> FakeResponse:
        self.call_count += 1
        return FakeResponse(self.responses[url])


class MemoryCache:
    def __init__(self) -> None:
        self.payloads: dict[str, Any] = {}
        self.keys: list[str] = []

    async def get_json(self, key: str, _ttl_hours: int) -> Any | None:
        return self.payloads.get(key)

    async def set_json(self, key: str, payload: Any) -> None:
        self.keys.append(key)
        self.payloads[key] = payload


if __name__ == "__main__":
    unittest.main()
