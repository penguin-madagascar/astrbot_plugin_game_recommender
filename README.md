# astrbot_plugin_game_recommender

基于 RAWG 数据源、规则过滤/排序和 AstrBot LLM 偏好解析的游戏推荐插件。安装 `astrbot_plugin_steam_price_heybox` 时，会额外补充 Steam 当前价、历史最低价、促销状态和小黑盒跨区价格摘要；未安装时仍保持 RAWG 推荐能力，不让 LLM 凭记忆编造事实。

## 功能

- `/gamerec <自然语言需求>`：根据平台、类型、排除项、人数、预算、语言、难度、氛围等偏好推荐游戏；兼容 alias：`/游戏推荐`。
- `/gamedesc <游戏名>`：查询 RAWG 中的游戏基础资料，并在可用时补充 Steam 价格；兼容 alias：`/游戏详情`。
- 使用 SQLite 缓存 RAWG 响应，减少重复请求。
- IGDB、IsThereAnyDeal client 已预留骨架，首版不调用。

## 安装

1. 将本目录放入 AstrBot 插件目录，或通过 AstrBot 插件管理安装。
2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 在 AstrBot WebUI 插件配置中填写 `rawg_api_key`。

## 配置

必填：

- `rawg_api_key`：RAWG API Key。未配置时插件会返回清晰错误提示。

可选：

- `llm_provider_id`：用于偏好解析和结果解释；留空时尝试当前会话模型，失败会自动降级。
- `max_results`：默认推荐数量，范围 1-10。
- `cache_ttl_hours`：RAWG 缓存有效期。
- `default_region`：默认地区代码。
- `enable_steam_price_enrichment`：是否启用 Steam 价格增强，默认开启。
- `steam_price_country`：Steam 价格查询地区，默认 `CN`。
- `steam_price_history_days`：小黑盒历史价格查询天数，默认 `720`。
- `steam_price_lookup_limit`：每次推荐最多补充价格的游戏数量，默认 `5`。
- `igdb_client_id`、`igdb_client_secret`、`itad_api_key`：预留字段，MVP 不调用。

## 示例

```text
/gamerec 推荐几个适合 Switch 和 Steam 的双人游戏，不要恐怖，最好支持中文，预算 100 以内，类似双人成行但别太难。
/gamedesc It Takes Two
```

## 限制说明

- 价格增强依赖可导入的 `astrbot_plugin_steam_price_heybox`；该插件未安装或查询失败时，只展示 RAWG 推荐结果。
- 预算会参与软排序：当前价在预算内会加分，超预算会提示，但不会直接过滤候选。
- RAWG 的中文支持数据不稳定；结果中未确认时会显示“不确定”或提醒以商店页面为准。
- 多人/合作、难度、氛围主要依据 RAWG 标签和规则推断，可能不完整。
- PlayStation、Nintendo Switch 的深度价格追踪留待后续接入官方/合规 API。

## 开发验证

```bash
uv python install 3.12
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt -r ../astrbot_plugin_steam_price_heybox/requirements.txt pyyaml
PYTHONPATH=/Users/jiangxingda/Projects/QQChatbot .venv/bin/python -m compileall -q .
PYTHONPATH=/Users/jiangxingda/Projects/QQChatbot .venv/bin/python -m unittest discover tests
```
