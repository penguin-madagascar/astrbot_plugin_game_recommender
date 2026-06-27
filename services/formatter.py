from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

try:
    from astrbot.api import logger
except ModuleNotFoundError:  # Allows formatter-only unit tests outside AstrBot.
    logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.star import Context

from ..storage.models import GameCandidate, GamePreference, GamePriceSummary, RankedGame

DISCLAIMER = (
    "以下推荐基于当前可查询到的数据，价格和平台信息可能因地区变化。"
)


def format_recommendations(
    preference: GamePreference,
    ranked_games: list[RankedGame],
    limit: int | None = None,
) -> str:
    return "\n".join(format_recommendation_messages(preference, ranked_games, limit=limit))


def format_recommendation_messages(
    preference: GamePreference,
    ranked_games: list[RankedGame],
    limit: int | None = None,
) -> list[str]:
    count = min(limit or preference.result_count or 5, len(ranked_games))
    if not ranked_games:
        return [(
            "一句话结论：暂时没有找到满足这些硬条件的游戏。\n"
            f"{DISCLAIMER}\n"
            "可以尝试放宽平台、排除标签或多人条件后再查一次。"
        )]

    lines = [
        (
            f"一句话结论：优先看前 {count} 款，"
            "它们和你的平台、类型、游玩人数与参考游戏偏好最接近。"
        ),
        DISCLAIMER,
    ]
    if preference.parse_warnings:
        lines.append("偏好解析提示：" + "；".join(preference.parse_warnings))

    lines.append("推荐列表将分条发送。")
    messages = ["\n".join(lines)]
    for index, game in enumerate(ranked_games[:count], start=1):
        messages.append("\n".join(format_game_block(index, game)))
    return messages


async def format_recommendations_with_llm(
    context: "Context",
    event: "AstrMessageEvent",
    provider_id: str,
    preference: GamePreference,
    ranked_games: list[RankedGame],
    limit: int | None = None,
) -> str:
    return "\n".join(
        await format_recommendation_messages_with_llm(
            context,
            event,
            provider_id,
            preference,
            ranked_games,
            limit=limit,
        )
    )


async def format_recommendation_messages_with_llm(
    context: "Context",
    event: "AstrMessageEvent",
    provider_id: str,
    preference: GamePreference,
    ranked_games: list[RankedGame],
    limit: int | None = None,
) -> list[str]:
    fallback = format_recommendation_messages(preference, ranked_games, limit=limit)
    if not ranked_games:
        return fallback

    resolved_provider = await resolve_provider_id(context, event, provider_id)
    if not resolved_provider:
        return fallback

    messages = [fallback[0]]
    games = ranked_games[: limit or preference.result_count or 5]
    for index, game in enumerate(games, start=1):
        fallback_block = fallback[index]
        payload = {
            "preference": dump_model(preference),
            "game": dump_model(game),
            "fallback_block": fallback_block,
            "rules": [
                "只能润色这一款游戏的说明，不能新增或删除游戏。",
                "第一行必须保持同一个序号和同一个游戏名。",
                "只能基于 game 字段写事实，不要编造价格、平台、中文支持。",
                "推荐理由和可能不适合的点都要具体。",
                "字段为空时写待确认，不要写暂未发现明显不适合点。",
            ],
        }
        prompt = (
            "请用中文润色单款游戏推荐块，保持固定字段结构："
            "名称、平台、推荐理由、可能不适合的点、购买/价格、数据来源/不确定项。"
            "只返回这一款游戏的文本块。\n"
            f"数据 JSON：{json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            response = await context.llm_generate(
                chat_provider_id=resolved_provider,
                prompt=prompt,
                system_prompt=(
                    "你只能改写给定 JSON 中的事实，不得补充外部知识或猜测。"
                ),
            )
            text = str(getattr(response, "completion_text", "") or "").strip()
        except Exception as exc:
            logger.warning(f"游戏推荐条目 LLM 格式化失败，使用规则 formatter：{exc}")
            text = ""
        messages.append(
            text if valid_game_message(text, index, game.title) else fallback_block
        )
    return messages


def format_game_block(index: int, game: RankedGame) -> list[str]:
    platforms = "、".join(game.platforms) if game.platforms else "不确定"
    reasons = (
        "；".join(game.reasons[:4])
        if game.reasons
        else "RAWG 数据与偏好有一定匹配"
    )
    warnings = (
        "；".join(game.warnings[:4])
        if game.warnings
        else "仍需以商店页面确认平台版本、中文支持和实时价格"
    )
    stores = "、".join(game.stores[:4]) if game.stores else "不确定"
    uncertain = uncertain_fields(game)
    lines = [
        f"{index}. 《{game.title}》",
        f"   平台：{platforms}",
        f"   推荐理由：{reasons}",
        f"   可能不适合的点：{warnings}",
    ]
    if game.price_summary:
        lines.append(f"   价格：{format_price_summary(game.price_summary)}")
        links = format_price_links(game.price_summary)
        if links:
            lines.append(f"   购买链接：{links}")
    else:
        lines.append(
            f"   购买 / 平台建议：RAWG 记录的商店为 {stores}；"
            "具体价格请以对应商店页面为准。"
        )
    if game.raw_url:
        lines.append(f"   数据来源：{game.raw_url}")
    if uncertain:
        lines.append(f"   数据不确定：{uncertain}")
    return lines


def valid_game_message(text: str, index: int, title: str) -> bool:
    if not text:
        return False
    first_line = text.splitlines()[0] if text.splitlines() else ""
    return first_line.startswith(f"{index}.") and title.lower() in text.lower()


def format_game_detail(game: GameCandidate, price_summary: GamePriceSummary | None = None) -> str:
    lines = [
        f"《{game.title}》",
        f"平台：{'、'.join(game.platforms) if game.platforms else '不确定'}",
        f"类型：{'、'.join(game.genres) if game.genres else '不确定'}",
        f"标签：{'、'.join(game.tags[:10]) if game.tags else '不确定'}",
        f"RAWG 评分：{game.rating if game.rating is not None else '不确定'}",
        f"Metacritic：{game.metacritic if game.metacritic is not None else '不确定'}",
        f"发售日：{game.released or '不确定'}",
        (
            "平均游玩时长："
            f"{str(game.playtime) + ' 小时' if game.playtime is not None else '不确定'}"
        ),
        f"商店：{'、'.join(game.stores) if game.stores else '不确定'}",
    ]
    if price_summary:
        lines.append(f"Steam 价格：{format_price_summary(price_summary)}")
        links = format_price_links(price_summary)
        if links:
            lines.append(f"购买链接：{links}")
        lines.append("中文支持：RAWG 数据可能缺失，请以商店页面为准。")
    else:
        lines.append(
            "价格 / 中文支持：RAWG 不提供可靠实时地区价格，"
            "中文支持也可能缺失，请以商店页面为准。"
        )
    if game.raw_url:
        lines.append(f"数据来源：{game.raw_url}")
    return "\n".join(lines)


def uncertain_fields(game: RankedGame) -> str:
    fields = []
    if not game.stores:
        fields.append("购买渠道")
    if not game.price_summary:
        fields.append("实时价格")
    if not any("中文" in reason or "chinese" in reason.lower() for reason in game.reasons):
        fields.append("中文支持")
    return "、".join(fields)


def format_price_summary(summary: GamePriceSummary) -> str:
    parts: list[str] = []
    if summary.current_price:
        parts.append(f"Steam 当前价 {summary.current_price}")
    if summary.lowest_price:
        lowest = f"史低 {summary.lowest_price}"
        annotations = []
        if summary.lowest_date:
            annotations.append(summary.lowest_date)
        if summary.lowest_discount:
            annotations.append(f"-{summary.lowest_discount}%")
        if annotations:
            lowest += f"（{'，'.join(annotations)}）"
        parts.append(lowest)
    if summary.sale_status:
        parts.append(summary.sale_status)
    if summary.region_summary:
        parts.append(summary.region_summary)
    return "；".join(parts) if parts else "暂时不可用"


def format_price_links(summary: GamePriceSummary) -> str:
    links = []
    if summary.store_url:
        links.append(f"Steam：{summary.store_url}")
    if summary.heybox_url:
        links.append(f"小黑盒：{summary.heybox_url}")
    return "；".join(links)


def dump_model(model: Any) -> dict[str, Any]:
    dumper = getattr(model, "model_dump", None)
    return dumper() if dumper else model.dict()


async def resolve_provider_id(
    context: "Context",
    event: "AstrMessageEvent",
    provider_id: str,
) -> str:
    if provider_id:
        return provider_id
    getter = getattr(context, "get_current_chat_provider_id", None)
    if not getter:
        return ""
    try:
        return str(await getter(umo=event.unified_msg_origin) or "")
    except Exception as exc:
        logger.debug(f"获取当前 LLM provider 失败：{exc}")
        return ""
