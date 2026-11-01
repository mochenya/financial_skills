---
name: stock-pool
description: 查询或维护 PostgreSQL 数据库中用户个人记录的股票池，例如查看关注了哪些股票、导入记录或更新关注状态；不用于查询个股行情、公司信息或投资分析。
---

# 个人股票池

维护个人关注的股票，不提供投资建议或行情分析。支持沪市 `sh`、深市 `sz`、北交所 `bj`、香港 `hk`、美国 `us`（含 OTC）、日本 `jp` 和韩国 `kr`。

使用 `STOCK_POOL_DATABASE_URL` 连接 `personal_data` 数据库，目标表为 `stock_pool.stocks`。脚本通过 `uv run` 运行，不自动建库或建表。以下命令中的 `${SKILL}` 为本 skill 的绝对目录。数据库写入遵守用户当前的审阅与授权要求。

## 导入股票

`import --file FILE` 接收 UTF-8 JSON 数组。每项只接受以下字段：

| 字段 | 要求 |
| --- | --- |
| `market` | 必填，字符串，使用下表的市场标识。 |
| `code` | 必填，字符串，使用下表对应格式；保留前导零。 |
| `alias`、`note` | 可省略，也可为字符串或 `null`，分别表示个人别名和备注。 |
| `concepts` | 可省略，也可为 `null`；仅 A 股可提供数组，元素须为非空白字符串，允许空数组。港、美、日、韩股不接受非 `null` 的手工值。 |

不接受其他字段，包括 `name`：名称由上游获取。`is_followed` 和时间字段也不能作为导入输入。

| 市场 | `code` 格式与示例 |
| --- | --- |
| `sh`、`sz`、`bj` | 6 位数字，如 `600452`、`920799`。 |
| `hk` | 5 位数字，如 `00175`。 |
| `us` | Yahoo ticker，如 `NVDA`、`BRK-B`、`LKNCY`。 |
| `jp` | 四位大写字母或数字加 `.T`，如 `285A.T`。 |
| `kr` | 六位数字加 `.KS` 或 `.KQ`，如 `005930.KS`、`247540.KQ`。 |

例如：

```json
[
  {"market": "sh", "code": "600452", "note": "关注电力业务"},
  {"market": "hk", "code": "00175", "alias": "吉利"},
  {"market": "jp", "code": "285A.T", "alias": "铠侠"}
]
```

```bash
uv run "${SKILL}/scripts/stock_pool.py" import --file stocks.json
```

A 股名称来自通达信；未指定 `concepts` 或指定为 `null` 时，自动获取一级、二级行业，两者都没有时取一个概念兜底。港股名称来自通达信、行业来自 Yahoo；美、日、韩股名称和行业来自 Yahoo，行业保存为英文 `concepts`。

导入逐条提交，可能部分成功：已有记录返回 `skipped`，不覆盖别名、概念、备注或关注状态；新建和失败分别返回 `created`、`failed`。有失败项时退出码为 1，已成功的记录保留。完整输入、输出和错误约定见 [CLI 契约](references/cli-contract.md)。

## 查询与维护

```bash
uv run "${SKILL}/scripts/stock_pool.py" list
uv run "${SKILL}/scripts/stock_pool.py" list --market hk --followed true
uv run "${SKILL}/scripts/stock_pool.py" list --keyword 黄金
```

查询默认包含已关注和未关注记录，多个筛选条件取交集，返回 `count` 和 `stocks`。单条添加、更新和删除的参数见 [CLI 契约](references/cli-contract.md)。取消关注应设为 `false` 以保留记录；`delete` 物理删除记录。

## 刷新行业

```bash
uv run "${SKILL}/scripts/stock_pool.py" refresh-industry --market jp --code 285A.T
uv run "${SKILL}/scripts/stock_pool.py" refresh-industry --market sh
```

`refresh-industry` 可指定 `sh`、`sz`、`bj`、`hk`、`us`、`jp` 或 `kr`；省略 `--market` 默认美股，省略 `--code` 刷新该市场的所有记录。查询失败或行业缺失时保留原值。美、日、韩股批量查询最多 8 并发，限流时停止提交新请求。Yahoo 的代码、证券类型和行业边界见 [Yahoo 契约](references/yahoo-contract.md)；通达信数据来源和边界见 [eltdx 契约](references/eltdx-contract.md)。数据库字段约束和设计见 [数据库契约](references/database-contract.md)。
