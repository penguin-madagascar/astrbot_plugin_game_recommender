from __future__ import annotations

from typing import Protocol

from ..clients.rawg import RAWG_GENRE_SLUGS, RAWG_TAG_SLUGS
from ..storage.models import GameCandidate, GamePreference, RankedGame
from .ranker import (
    game_has_disliked_term,
    game_matches_any_platform,
    has_singleplayer_only_signal,
    score_game,
)

STEAM_FALLBACK_WARNING = (
    "未配置 RAWG API Key，当前使用 Steam 公开数据源，主要覆盖 Steam/PC；"
    "Switch/PlayStation/Xbox 覆盖有限。"
)
STEAM_SOURCE_PLATFORMS = {"steam", "pc"}


class GameSource(Protocol):
    async def search_games(
        self,
        search: str | None = None,
        platforms: list[str] | None = None,
        genres: list[str] | None = None,
        tags: list[str] | None = None,
        page_size: int = 20,
        ordering: str = "-rating",
    ) -> list[GameCandidate]:
        ...


class GameRecommender:
    def __init__(self, game_source: GameSource, max_results: int = 5) -> None:
        self.game_source = game_source
        self.max_results = min(max(max_results, 1), 10)

    async def recommend(
        self,
        preference: GamePreference,
        candidate_pool_size: int | None = None,
    ) -> list[RankedGame]:
        candidates = await self._recall_candidates(preference)
        filtered = self._filter_candidates(candidates, preference)
        ranked: list[RankedGame] = []
        for candidate in filtered:
            score, reasons, warnings = score_game(candidate, preference)
            ranked.append(RankedGame.from_candidate(candidate, score, reasons, warnings))
        ranked.sort(key=lambda item: item.score, reverse=True)
        limit = candidate_pool_size or preference.result_count or self.max_results
        return ranked[: min(max(limit, 1), 30)]

    async def _recall_candidates(self, preference: GamePreference) -> list[GameCandidate]:
        candidates: list[GameCandidate] = []
        page_size = max(self.max_results * 4, 20)

        genre_terms = [term for term in preference.genres_like if term in RAWG_GENRE_SLUGS]
        tag_terms = [term for term in preference.genres_like if term in RAWG_TAG_SLUGS]
        if preference.players and preference.players >= 2:
            tag_terms.extend(["co-op", "multiplayer"])
        if genre_terms or tag_terms:
            candidates.extend(
                await self.game_source.search_games(
                    platforms=preference.platforms,
                    genres=genre_terms[:3],
                    tags=tag_terms[:4],
                    page_size=page_size,
                    ordering="-rating",
                )
            )

        if not candidates:
            query = fallback_search_query(preference)
            candidates.extend(
                await self.game_source.search_games(
                    search=query,
                    platforms=preference.platforms,
                    page_size=page_size,
                    ordering="-rating",
                )
            )

        return dedupe_candidates(candidates)

    def _filter_candidates(
        self,
        candidates: list[GameCandidate],
        preference: GamePreference,
    ) -> list[GameCandidate]:
        filtered = []
        for candidate in candidates:
            if not candidate.title:
                continue
            if is_reference_game(candidate, preference.reference_games_like):
                continue
            if is_downloadable_content(candidate):
                continue
            if not game_matches_any_platform(candidate, preference.platforms):
                continue
            if game_has_disliked_term(candidate, preference.genres_dislike):
                continue
            if (
                preference.players
                and preference.players >= 2
                and has_singleplayer_only_signal(candidate)
            ):
                continue
            title = candidate.title.lower()
            if any(reference.lower() in title for reference in preference.reference_games_dislike):
                continue
            filtered.append(candidate)
        return filtered


def adapt_preference_for_steam_source(preference: GamePreference) -> None:
    if STEAM_FALLBACK_WARNING not in preference.parse_warnings:
        preference.parse_warnings.append(STEAM_FALLBACK_WARNING)

    if not preference.platforms:
        return

    steam_platforms = [
        platform for platform in preference.platforms if platform in STEAM_SOURCE_PLATFORMS
    ]
    preference.platforms = steam_platforms or ["steam"]


def dedupe_candidates(candidates: list[GameCandidate]) -> list[GameCandidate]:
    result: list[GameCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if is_downloadable_content(candidate):
            continue
        key = str(candidate.rawg_id or normalized_title_key(candidate.title))
        if key and key not in seen:
            result.append(candidate)
            seen.add(key)
    return result


def fallback_search_query(preference: GamePreference) -> str:
    if preference.players and preference.players >= 2:
        return "co-op multiplayer"
    if preference.genres_like:
        return " ".join(preference.genres_like[:2])
    if preference.mood:
        return preference.mood
    return "popular games"


def is_reference_game(candidate: GameCandidate, references: list[str]) -> bool:
    title_key = normalized_title_key(candidate.title)
    return any(
        title_key == normalized_title_key(reference)
        for reference in references
        if reference
    )


def is_downloadable_content(candidate: GameCandidate) -> bool:
    haystack = " | ".join(
        [candidate.title, *candidate.genres, *candidate.tags]
    ).lower()
    if any(
        term in haystack
        for term in (" dlc", "expansion", "expansion pack", "downloadable content")
    ):
        return True
    title = candidate.title.lower()
    return any(
        term in title
        for term in (
            "blood and wine",
            "hearts of stone",
            "episode ",
            "season pass",
            "soundtrack",
        )
    )


def normalized_title_key(title: str) -> str:
    lowered = title.lower().replace("–", "-").replace("—", "-")
    lowered = lowered.replace("game of the year", "").replace("complete edition", "")
    lowered = lowered.replace("definitive edition", "").replace("special edition", "")
    return "".join(ch for ch in lowered if ch.isalnum())
