from __future__ import annotations

import unittest

from astrbot_plugin_game_recommender.services.preference_rules import (
    infer_preference_from_text,
    merge_text_preference,
)
from astrbot_plugin_game_recommender.storage.models import GamePreference


class PreferenceRulesTest(unittest.TestCase):
    def test_infers_high_confidence_preferences_from_user_text(self) -> None:
        preference = infer_preference_from_text(
            "推荐几个适合 Switch 和 Steam 的双人游戏，不要恐怖，"
            "最好支持中文，预算 100 以内，类似双人成行但别太难。"
        )

        self.assertIn("nintendo switch", preference.platforms)
        self.assertIn("steam", preference.platforms)
        self.assertEqual(preference.players, 2)
        self.assertEqual(preference.budget, 100)
        self.assertEqual(preference.language, "中文")
        self.assertEqual(preference.difficulty, "easy")
        self.assertIn("horror", preference.genres_dislike)
        self.assertIn("it takes two", preference.reference_games_like)
        for term in ("co-op", "local co-op", "puzzle", "adventure", "casual", "platformer"):
            self.assertIn(term, preference.genres_like)

    def test_merges_keyword_rules_into_empty_llm_preference(self) -> None:
        llm_preference = GamePreference(
            platforms=[],
            genres_like=[],
            genres_dislike=[],
            reference_games_like=[],
            players=None,
            budget=None,
            language=None,
            difficulty=None,
            result_count=5,
        )

        merged = merge_text_preference(
            llm_preference,
            "推荐几个适合 Switch 和 Steam 的双人游戏，不要恐怖，"
            "最好支持中文，预算 100 以内，类似双人成行但别太难。",
        )

        self.assertIn("nintendo switch", merged.platforms)
        self.assertIn("steam", merged.platforms)
        self.assertEqual(merged.players, 2)
        self.assertEqual(merged.budget, 100)
        self.assertEqual(merged.language, "中文")
        self.assertEqual(merged.difficulty, "easy")
        self.assertIn("horror", merged.genres_dislike)
        self.assertIn("it takes two", merged.reference_games_like)


if __name__ == "__main__":
    unittest.main()
