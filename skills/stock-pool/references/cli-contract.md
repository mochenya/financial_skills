# CLI 与数据契约

以下命令以 `uv run "${SKILL}/scripts/stock_pool.py"` 为前缀。依赖声明在脚本中，要求 Python >=3.10 且 <3.15，固定 eltdx 3.3.2、psycopg[binary] 3.2.13 和 yfinance 1.7.0。使用 `STOCK_POOL_DATABASE_URL`；脚本不自动创建库表。

## 导入格式

`import --file stocks.json` 接收 UTF-8 JSON 数组；每项是对象，必须含 `market`、`code` 字符串，可含 `alias`、`concepts`、`note`，其他字段不接受。

```json
[
  {"market": "sh", "code": "600452", "concepts": ["电力", "节能环保"]},
  {"market": "hk", "code": "00175", "alias": "吉利", "note": null},
  {"market": "bj", "code": "920799", "concepts": []}
]
```

`market` 可为 `sh/sz/bj/hk/us/jp/kr`；沪深北代码为 6 位数字、港股为 5 位数字，美股使用 Yahoo ticker。`alias` 和 `note` 可为字符串或 null，`concepts` 可为字符串数组或 null，数组元素不得为空白字符串。省略的可选字段为 null。`name` 由上游获取，不接受作为输入；同样不能指定 `is_followed`、时间字段。代码未列在上游时应先核查，不据名称推断代码。

逐条独立事务：已有 `(market, code)` 返回 `skipped`，不更新；新记录经上游确认后返回 `created`；格式或接口等失败返回 `failed`，不影响其他项。返回示例：

```json
{"status":"partial","total":3,"created":1,"skipped":1,"failed":1,"results":[
  {"market":"sh","code":"600452","status":"created"},
  {"market":"hk","code":"00175","status":"skipped","reason":"already_exists"},
  {"market":"bj","code":"bad","status":"failed","reason":"invalid market or code format"}
]}
```

失败项存在时退出 1，即使其他项已提交；全部成功或跳过时 `status` 为 `ok`、退出 0。上游或数据库异常的逐项 `reason` 为通用错误，不包含连接凭据。

## 命令

| 命令 | 行为 |
| --- | --- |
| `add --market MARKET --code CODE [--alias TEXT] [--concept TEXT ...] [--note TEXT]` | 上游确认后创建；输出 `created` 和完整 `stock`，或 `skipped` 和原因。 |
| `import --file FILE` | 批量导入并返回逐条结果。 |
| `list [--market MARKET] [--code CODE] [--followed true\|false] [--keyword TEXT]` | 条件取交集；关键词对代码、名称、别名和备注做大小写不敏感的 SQL 模式匹配，`%` 和 `_` 为通配符；按市场、代码排序。 |
| `update --market MARKET --code CODE [--alias TEXT\|--clear-alias] [--note TEXT\|--clear-note] [--concept TEXT ...\|--clear-concepts] [--followed true\|false]` | 未指定的字段不变；重复 `--concept` 替换整个数组，清除设为 null；至少提供一个修改项。返回 `updated` 或 `unchanged` 及完整记录。 |
| `delete --market MARKET --code CODE` | 物理删除，返回 `deleted`、市场和代码；不存在时报错。 |

`list` 返回 `{ "count": 1, "stocks": [...] }`；完整记录如下，时间为带时区偏移的字符串，日期与时间之间可为空格：

```json
{"market":"hk","code":"00175","name":"吉利汽车","alias":null,"concepts":["汽车"],"note":null,"is_followed":true,"created_at":"2026-11-01 08:30:00+00:00","updated_at":"2026-11-01 08:30:00+00:00"}
```

正常结果输出到标准输出；argparse 参数错误输出到标准错误并退出 2；其他整体错误输出标准错误 JSON 并退出 1。未找到记录也是错误。关键词不搜索概念字段。

## 美股扩展

`us` 代码为 Yahoo ticker，例如 `NVDA`、`BRK-B`、`LKNCY`。美股自动取 Yahoo 行业写入 concepts；不应提供 concepts 输入。`refresh-industry [--code CODE]` 显式刷新已有美股的 Yahoo 行业，缺失或查询失败保留原值并返回失败，改变时更新 updated_at。批量最多 8 并发；限流停止提交后续查询。详见 [Yahoo 契约](yahoo-contract.md)。

A 股新建且未提供 concepts 时，从通达信获取一级、二级行业，两级行业均未命中时取一个概念兜底；手工提供时保留手工值。`refresh-industry --market sh|sz|bj [--code CODE]` 显式刷新，失败保留原值；不指定 market 默认 us。

港股名称使用通达信，行业使用 Yahoo；本地五位代码转换为 Yahoo 至少四位加 .HK，例如 00175 → 0175.HK。港股禁止手工 concepts；`refresh-industry --market hk [--code CODE]` 显式刷新，失败或行业缺失不覆盖。

## 日本和韩国

`jp` 使用完整 Yahoo ticker（例如 `285A.T`），`kr` 使用六位数字及 `.KS` 或 `.KQ`（例如 `005930.KS`、`247540.KQ`）。名称及 concepts 按美股规则获取，禁止手工 concepts。`refresh-industry --market jp|kr [--code CODE]` 刷新行业。
