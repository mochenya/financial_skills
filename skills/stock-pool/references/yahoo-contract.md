# Yahoo Finance 数据源契约

美股（含 OTC）使用 yfinance 1.7.0，Yahoo ticker 为本地代码，例：NVDA、BRK-B、LKNCY。Ticker.info 必须返回匹配 symbol、EQUITY 和非空名称；优先 longName，次选 shortName。industry 原文作为单元素 concepts，缺失时为 null。EQUITY 不是严格的公司普通股证明，CQP 合伙权益按用户决定纳入，无法确认的特殊证券须核查；ETF、指数和债券不应纳入。


## 美股代码与证券类型边界

保存 Yahoo 原始 ticker，不添加国家或交易所后缀；不同数据源的代码写法不一定相同，不应机械替换标点。2026-11-01 使用 yfinance 1.7.0 实测 `NVDA`、`BRK-B`、`LKNCY` 均返回匹配的 symbol、EQUITY 和名称；`LKNCY` 为 OTC。`BRK.B` 当时只返回部分信息，缺少 longName、交易所、币种和行业，且当前代码格式不接受点号；伯克希尔 B 类股应核对后使用 Yahoo 的 `BRK-B`。见 [Yahoo 报价](https://finance.yahoo.com/quote/BRK-B/)。

`(market, code)` 识别证券而非公司：`GOOG`、`GOOGL` 均返回 Alphabet，不自动按公司合并。`EQUITY` 不能排除优先股：实测 `BAC-PL` 返回 EQUITY，而 [Yahoo 说明](https://help.yahoo.com/kb/SLN2340.html)将其列为优先股代码示例；需要只纳入普通股时须进一步核查，不能仅凭该字段确认。代码可能变更，Yahoo 也不完全覆盖 OTC、ADR 等证券，详见 [Yahoo 代码缺失说明](https://help.yahoo.com/kb/finance/learn-reasons-symbol-isnt-tknproductfinancename-sln2257.html)。上述抽查不保证未来结果或其他证券的覆盖。

批量美股查询最多 8 并发，不固定等待；429 停止提交新请求，等待在途结果，未查询和失败项报告失败。此策略不保证不会限流。空结果或异常不证明证券不存在或退市。2026-11-01 实测 213 只全部返回行业，8 并发耗时 21.08 秒；后续结果可能变化。Yahoo 数据由第三方库获取，使用受 Yahoo 条款约束。

美股首次添加取得行业；refresh-industry 显式刷新已有美股，行业缺失及失败保留原值。重复导入跳过已有记录。A 股维持 eltdx 契约，不自动回填。

港股名称使用通达信，行业使用 Yahoo；五位本地代码转换为至少四位 Yahoo 代码加 .HK，00175 → 0175.HK。港股概念不接受手工设置，行业缺失保存 null，查询失败不会覆盖已有行业。

## 日本和韩国

`jp` 保存四位大写字母或数字加 `.T`，如 `285A.T`；`kr` 保存六位数字加 `.KS` 或 `.KQ`，如 `005930.KS`、`247540.KQ`，保留前导零。名称、行业、证券类型检查、批量限流和刷新规则与美股一致；禁止手工 concepts。EQUITY 不保证为普通股，特殊证券需核查。2026-11-01 实测表格中 31 只日本及 10 只韩国证券均取得匹配 symbol、EQUITY、名称和行业；另实测 `247540.KQ`。这不保证其他代码或未来查询成功。
