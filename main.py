from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.star.filter.command import GreedyStr

from .clients.steam import SteamApiError, SteamClient
from .services.formatter import (
    format_game_detail,
    format_recommendation_messages_with_llm,
)
from .services.message_delivery import build_forward_message_chain
from .services.preference_parser import PreferenceParser
from .services.recommendation_limits import effective_result_limit
from .services.steam_index import (
    STEAM_INDEX_FALLBACK_WARNING,
    has_supported_steam_platform,
    SteamGameIndexService,
    steam_only_scope_warning_for,
)
from .services.steam_price_bridge import SteamPriceBridge
from .storage.repository import SQLiteCacheRepository

PLUGIN_NAME = "astrbot_plugin_game_recommender"
PLUGIN_VERSION = "0.3.2"
PLUGIN_DESCRIPTION = (
    "基于 Steam/PC 公开数据、本地索引和标签相似度推荐游戏；"
    "当前版本暂不做跨平台候选召回。"
)


@register(
    PLUGIN_NAME,
    "jiangxingda",
    PLUGIN_DESCRIPTION,
    PLUGIN_VERSION,
)
class GameRecommenderPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict | None = None) -> None:
        super().__init__(context)
        self.context = context
        self.config = config or {}
        timeout = safe_int(self.config.get("timeout_seconds"), 15)
        self.max_results = min(max(safe_int(self.config.get("max_results"), 5), 1), 10)
        self.provider_id = str(self.config.get("llm_provider_id", "") or "").strip()

        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            headers={
                "User-Agent": f"{PLUGIN_NAME}/{PLUGIN_VERSION}",
                "Accept": "application/json",
            },
        )
        data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
        self.cache = SQLiteCacheRepository(data_dir / "steam_cache.sqlite3")
        self.steam_client = SteamClient(
            client=self.http_client,
            cache=self.cache,
            cache_ttl_hours=safe_int(self.config.get("cache_ttl_hours"), 24),
            default_country=str(self.config.get("default_region") or "CN"),
            language="schinese",
        )
        self.preference_parser = PreferenceParser(context, self.provider_id)
        self.steam_index = SteamGameIndexService(
            steam_client=self.steam_client,
            cache=self.cache,
            ttl_hours=safe_int(self.config.get("steam_index_ttl_hours"), 168),
            min_review_count=safe_int(self.config.get("steam_min_review_count"), 50),
            min_positive_ratio=safe_float(self.config.get("steam_min_positive_ratio"), 0.65),
        )
        self.price_bridge = SteamPriceBridge(self.http_client, self.config)
        if self.price_bridge.is_available():
            logger.info(
                "Detected astrbot_plugin_steam_price_heybox; Steam price enrichment enabled."
            )
        else:
            logger.info(
                "astrbot_plugin_steam_price_heybox is not available; "
                "game recommendations continue without price enrichment."
            )

    async def terminate(self) -> None:
        await self.http_client.aclose()
        logger.info("Game recommender plugin stopped.")

    @filter.command(
        "gamerec",
        alias={"游戏推荐"},
        desc="根据自然语言需求推荐游戏。",
    )
    async def recommend_games(self, event: AstrMessageEvent, query: GreedyStr):
        text = str(query).strip()
        if not text:
            yield event.plain_result(
                "请输入需求，例如：/gamerec Switch 和 Steam 双人合作，"
                "不要恐怖，预算 100 以内（当前仅推荐 Steam/PC 候选）"
            )
            return

        try:
            preference = await self.preference_parser.parse_preference(event, text)
            if warning := steam_only_scope_warning_for(preference):
                preference.parse_warnings.append(warning)
            if not has_supported_steam_platform(preference):
                yield event.plain_result(preference.parse_warnings[-1])
                return
            result_limit = effective_result_limit(self.max_results, preference.result_count)
            candidate_pool_size = (
                max(result_limit * 3, result_limit)
                if preference.budget is not None or self.price_bridge.is_available()
                else None
            )
            ranked_games = await self._recommend_with_steam_index(
                preference,
                limit=candidate_pool_size or result_limit,
            )
            ranked_games = await self.price_bridge.enrich_ranked_games(ranked_games, preference)
            messages = await format_recommendation_messages_with_llm(
                self.context,
                event,
                self.provider_id,
                preference,
                ranked_games,
                limit=result_limit,
            )
        except SteamApiError as exc:
            logger.warning(f"Steam game recommendation failed: {exc}")
            yield event.plain_result(f"Steam 查询失败：{exc}")
            return
        except Exception as exc:
            logger.exception("Game recommendation failed")
            yield event.plain_result(f"游戏推荐失败：{exc}")
            return

        forward_chain = build_forward_message_chain(messages)
        if forward_chain and hasattr(event, "chain_result"):
            yield event.chain_result(forward_chain)
        else:
            yield event.plain_result("\n\n".join(messages))

    @filter.command(
        "gamedesc",
        alias={"游戏详情"},
        desc="查询游戏基础资料和 Steam 价格。",
    )
    async def game_detail(self, event: AstrMessageEvent, query: GreedyStr):
        title = str(query).strip()
        if not title:
            yield event.plain_result("请输入游戏名，例如：/gamedesc It Takes Two")
            return

        try:
            candidates = await self.steam_client.search_games(search=title, page_size=1)
            if not candidates:
                yield event.plain_result(f"没有查询到游戏：{title}")
                return
            game = candidates[0]
            price_summary = await self.price_bridge.lookup(game.title)
        except SteamApiError as exc:
            logger.warning(f"Steam game detail failed: {exc}")
            yield event.plain_result(f"Steam 查询失败：{exc}")
            return
        except Exception as exc:
            logger.exception("Game detail lookup failed")
            yield event.plain_result(f"游戏详情查询失败：{exc}")
            return

        yield event.plain_result(format_game_detail(game, price_summary))

    async def _recommend_with_steam_index(
        self,
        preference,
        limit: int,
    ):
        ranked_games = await self.steam_index.recommend(preference, limit=limit)
        if ranked_games:
            return ranked_games
        if STEAM_INDEX_FALLBACK_WARNING not in preference.parse_warnings:
            preference.parse_warnings.append(STEAM_INDEX_FALLBACK_WARNING)
        return []


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
