# 美股批量取数端点（实测）

实测环境：本机出口 IP 为香港；2026-11-01 复核。

## 1. 池子（唯一真相）

```bash
uv run <stock-pool skill>/scripts/stock_pool.py list --market us > pool_us.json
```

返回 `{"count": N, "stocks": [{"market","code","alias","concepts","is_followed",...}]}`。
代码是 **Yahoo 口径**：`NVDA`、`BRK-B`、`LKNCY`。只读本接口，不回写。

## 2. TradingView scanner（快照，宽度）

```bash
POST https://scanner.tradingview.com/america/scan
Content-Type: application/json
User-Agent: <浏览器 UA>

{"symbols":{"tickers":["NASDAQ:NVDA","NYSE:BRK.B"]},"columns":["close","change",...]}
```

- 单次 150–200 个标的，约 0.3 秒，免鉴权，未遇到限流。
- 交易所前缀用 `NASDAQ` / `NYSE` / `AMEX` / `OTC` 各批量探测一次；未命中的标的**不会报错**，必须显式记录。
- 符号用点号：`NYSE:BRK.B`（池内是 `BRK-B`）。

常用列：

| 列名 | 含义 |
|---|---|
| `close` `change` `volume` | 收盘、当日涨跌%、成交量 |
| `relative_volume_10d_calc` `average_volume_30d_calc` | 相对量、30 日均量 |
| `market_cap_basic` | 市值（美元） |
| `price_earnings_ttm` `price_book_ratio` `dividends_yield` | 估值 |
| `earnings_per_share_diluted_ttm` | TTM 摊薄 EPS |
| `total_revenue_yoy_growth_ttm` `earnings_per_share_diluted_yoy_growth_ttm` | TTM 同比增速 |
| `RSI` | 14 日 RSI |
| `SMA20` `SMA50` `SMA200`（也可用 `Perf.W/1M/3M/YTD`） | 均线与区间收益 |
| `price_52_week_high` `price_52_week_low` | 52 周高低 |
| `price_target_average` | 卖方一致目标价（约 1/4 标的为空） |
| `recommendation_mark` | 1=强买 … 5=卖出 |
| `earnings_release_next_date` | 下次财报，unix 秒 |
| `sector` `industry` | 行业（英文，需自行映射中文） |
| `gap` | 当日跳空幅度 |

实测空值率（213 只池子，用 `price_target_average`）：约 1/4 标的为空；`price_earnings_ttm` 约 8% 空（亏损公司）。注意别误用名字相近的 `target_price_average`、`dividend_yield_recent`——这两个实测全空。

## 3. stockanalysis.com（复权日线，深度）

```
https://stockanalysis.com/api/symbol/s/<slug>/history?range=5Y&period=Day
```

- `slug` = 小写代码，连字符换成点：`brk-b` → `brk.b`。
- 返回 `{"status":200,"data":[{"t":"2026-10-30","o":..,"h":..,"l":..,"c":..,"a":..,"v":..}]}`，`a` 为复权收盘。
- 5–6 线程并发 200+ 只约 14 秒；突发过高会 403，需要 UA + 指数退避。
- 边界：OTC ADR（如 `lkncy`）返回 400；刚分拆/换代码的（如 `ctva`）即使 `range=5Y` 也只给 1 个月。这类标 `thin`。
- 基准同源取：`spy qqq smh gld tlt xle xlu iwm`。

## 4. 归一化校验

同一交易日，`history` 末根 `close` 与 TradingView `close` 偏差应 <0.5%。超了先查：是否未复权、是否 T+1 滞后、是否代码指向不同证券（ADR vs 本地股）。

## 5. 不可用

**Yahoo / yfinance**：`query1/query2.finance.yahoo.com` 直连与走代理均返回 429，crumb 也 429，重试不自愈。`yf.download` 批量全部失败。接口设计（`fast_info`/`info` 分层）可以借鉴，但不要作为数据源。

## 6. 归因用的检索入口

- 公司 IR / SEC EDGAR 8-K、10-Q：财报反应的第一手
- 路透、彭博、CNBC、WSJ：事件定性
- 交易所公告（重大事项、停牌、诉讼）
- 聚合成交/技术面站点只用于确认数据，不用于解释原因
