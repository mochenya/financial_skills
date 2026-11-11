---
name: stock-all-time-high
description: 基于 TradingView Scanner 筛选并导出 A 股、港股和美股最近交易日的历史新高股票快照；用于生成供人查看的 XLSX 表格或供程序读取的 JSON，不用于查询个人股票池或完整历史回测。
---

# 股票历史新高导出

使用 `{SKILL_DIR}/scripts/export_highs.py` 获取最近交易日的历史新高筛选快照。面向人工查看优先导出 XLSX，供程序处理导出 JSON。脚本通过 `uv` 管理依赖；在 Skill 目录下运行：

```bash
# 三个市场，供人查看；A 股和港股一张表，美股一张表
uv run {SKILL_DIR}/scripts/export_highs.py --format xlsx --output /tmp/股票历史新高.xlsx

# 只导出 A 股和港股，或只导出美股
uv run {SKILL_DIR}/scripts/export_highs.py --market ah --format xlsx --output /tmp/亚太新高.xlsx
uv run {SKILL_DIR}/scripts/export_highs.py --market america --format xlsx --output /tmp/美股新高.xlsx

# JSON 供程序读取
uv run {SKILL_DIR}/scripts/export_highs.py --format json --output /tmp/股票历史新高.json

# 不按市值过滤，仍保留证券类型过滤
uv run {SKILL_DIR}/scripts/export_highs.py --no-market-cap-filter --format xlsx --output /tmp/新高-不限市值.xlsx
```

`--market` 也支持 `china`、`hongkong`；不指定时为 `all`。`--output` 可换成用户指定的路径，现有同名文件会被覆盖。运行后根据输出统计报告导出文件、各市场条数及名称匹配情况；若有空结果或名称匹配失败，说明实际情况。

## 默认筛选与表格口径

- 默认市值门槛：A 股不低于 50 亿元人民币、港股不低于 100 亿港元、美股不低于 100 亿美元；市值为空或币种不符时排除。`--no-market-cap-filter` 关闭此门槛。
- 使用数据源的 `all_time_high` 预设，并按数据源的 `stock`、`common` 分类筛选；A 股另按交易所和代码前缀限定。分类和代码范围不保证完整或完全准确。盘中结果可能变化，不等于最终收盘结果。
- XLSX 按总市值降序、同市值按市场升序；A 股和港股在同一表中按各自本币的市值数值排序，不做汇率换算。表内行情时间、采集时间和顶部最新行情更新时间均使用北京时间。
- 高点展示使用 TradingView 的 `High.All`；相对成交量是当日成交量相对前 10 日平均成交量的比值，盘中数据尚未完整。换手率按成交量除以流通股数估算，不能保证与其他行情软件一致；市盈率为 TTM。字段缺失时保持空值。

## 数据源

- [TradingView Scanner](https://www.tradingview.com/) 提供筛选、行情和财务字段，通过非官方 Python 库 [tvscreener](https://github.com/deepentropy/tvscreener) 访问；接口和数据覆盖可能变化。TradingView 对自动采集和内部接口的使用有限制，参见其[使用条款](https://www.tradingview.com/policies/)。
- [eltdx](https://github.com/electkismet/eltdx) 使用通达信扩展行情，根据港股和美股代码补充中文证券简称；找不到中文名或请求失败时保留 TradingView 原名。它不是翻译服务，代码匹配和中文名覆盖并非完全可靠。JSON 对成功替换的名称保留 `名称原文`。

脚本提供的是获取时的筛选快照，不保证实时、完整或可回填过去每天的结果；输出中保留数据源的行情更新时间及采集时间。
