from __future__ import annotations

import unittest
from typing import Any

from astrbot_plugin_game_recommender.services.recommender import (
    GameRecommender,
    dedupe_candidates,
)
from astrbot_plugin_game_recommender.storage.models import GameCandidate, GamePreference


class RecommendationQualityTest(unittest.IsolatedAsyncioTestCase):
    async def test_it_takes_two_like_request_filters_bad_matches(self) -> None:
        source = FakeGameSource(
            [
                GameCandidate(
                    title="The Witcher 3: Wild Hunt - Blood and Wine",
                    platforms=["PC", "PlayStation 4"],
                    genres=["RPG"],
                    tags=["Horror", "Blood"],
                    rating=4.8,
                    stores=["Steam"],
                ),
                GameCandidate(
                    title="Persona 5 Royal",
                    platforms=["PC", "Nintendo Switch"],
                    genres=["RPG"],
                    tags=["Singleplayer", "JRPG"],
                    rating=4.8,
                    stores=["Steam", "Nintendo Store"],
                ),
                GameCandidate(
                    title="Warhammer 40,000: Dawn of War - Definitive Edition",
                    platforms=["PC"],
                    genres=["Strategy"],
                    tags=["Singleplayer", "Multiplayer", "Co-op"],
                    rating=4.8,
                    stores=["Steam"],
                ),
                GameCandidate(
                    title="It Takes Two",
                    platforms=["PC", "Nintendo Switch"],
                    genres=["Adventure", "Platformer"],
                    tags=["Co-op", "Local Co-op", "Split Screen", "Simplified Chinese"],
                    rating=4.5,
                    stores=["Steam", "Nintendo Store"],
                ),
                co_op_game("Unravel Two", rating=4.2),
                co_op_game("Overcooked! All You Can Eat", rating=4.1, tags=["Co-op", "Party"]),
                co_op_game("PHOGS!", rating=3.9, tags=["Co-op", "Puzzle", "Casual"]),
            ]
        )
        preference = GamePreference(
            platforms=["nintendo switch", "steam"],
            genres_like=[
                "co-op",
                "local co-op",
                "puzzle",
                "adventure",
                "casual",
                "platformer",
            ],
            genres_dislike=["horror"],
            reference_games_like=["it takes two"],
            players=2,
            language="中文",
            difficulty="easy",
            result_count=3,
        )

        ranked = await GameRecommender(source, max_results=3).recommend(
            preference,
            candidate_pool_size=8,
        )

        titles = [game.title for game in ranked[:3]]
        self.assertEqual(titles, ["Unravel Two", "Overcooked! All You Can Eat", "PHOGS!"])
        self.assertTrue(all("It Takes Two" not in title for title in titles))
        self.assertTrue(all("Witcher" not in title for title in titles))
        self.assertNotIn("Persona 5 Royal", titles)
        self.assertNotIn("Warhammer 40,000: Dawn of War - Definitive Edition", titles)

    async def test_explicit_preferences_do_not_fall_back_to_empty_rawg_query(self) -> None:
        source = FakeGameSource([co_op_game("Unravel Two")])
        preference = GamePreference(
            players=2,
            language="中文",
            budget=100,
            result_count=1,
        )

        await GameRecommender(source, max_results=1).recommend(preference)

        self.assertTrue(source.calls)
        self.assertTrue(
            all(
                call.get("search")
                or call.get("platforms")
                or call.get("genres")
                or call.get("tags")
                for call in source.calls
            )
        )


class CandidateDedupeTest(unittest.TestCase):
    def test_dedupe_prefers_complete_game_over_witcher_dlc_entries(self) -> None:
        deduped = dedupe_candidates(
            [
                GameCandidate(
                    title="The Witcher 3: Wild Hunt - Blood and Wine",
                    platforms=["PC"],
                    tags=["DLC"],
                    stores=["Steam"],
                ),
                GameCandidate(
                    title="The Witcher 3 Wild Hunt - Complete Edition",
                    platforms=["PC", "Nintendo Switch"],
                    stores=["Steam", "Nintendo Store"],
                ),
                GameCandidate(
                    title="The Witcher 3: Wild Hunt - Hearts of Stone",
                    platforms=["PC"],
                    tags=["Expansion"],
                    stores=["Steam"],
                ),
            ]
        )

        self.assertEqual(
            [game.title for game in deduped],
            ["The Witcher 3 Wild Hunt - Complete Edition"],
        )


def co_op_game(
    title: str,
    rating: float = 4.0,
    tags: list[str] | None = None,
) -> GameCandidate:
    return GameCandidate(
        title=title,
        platforms=["PC", "Nintendo Switch"],
        genres=["Adventure", "Puzzle"],
        tags=tags or ["Co-op", "Local Co-op", "Puzzle", "Casual", "Simplified Chinese"],
        rating=rating,
        stores=["Steam", "Nintendo Store"],
    )


class FakeGameSource:
    def __init__(self, games: list[GameCandidate]) -> None:
        self.games = games
        self.calls: list[dict[str, Any]] = []

    async def search_games(self, **kwargs: Any) -> list[GameCandidate]:
        self.calls.append(kwargs)
        return self.games


if __name__ == "__main__":
    unittest.main()
