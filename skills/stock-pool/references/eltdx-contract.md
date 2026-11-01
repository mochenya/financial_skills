# eltdx 数据源契约

数据源为通达信协议客户端 [eltdx](https://github.com/electkismet/eltdx)。本契约依据 `eltdx==3.3.2`，实测时间为 2026-10-31 至 2026-11-01；服务端返回会随日期、服务器和版本变化。数据库与 CLI 的契约分别见 [数据库契约](database-contract.md) 和 [CLI 契约](cli-contract.md)。

## 证券代码和名称

| 本地市场 | 实际调用 | 结果及取值 |
| --- | --- | --- |
| `sh` / `sz` / `bj` | `TdxClient.codes.a_shares(market)` | `list[SecurityCode]`，取 `exchange`、`code`、`name`。`code` 为六位字符串。 |
| `hk` | `MacExClient.instruments(31, start, count)` | `list[ExInstrumentInfo]`，取 `market`、`code`、`name`。按 600 条分页，最后一页不足 600 条时结束；`code` 为五位字符串。 |

A 股 `market_id` 的 0、1、2 分别对应深、沪、北；港股 `31` 是扩展行情协议的市场号，不与其他协议编号混用。A 股代码表的 `category` 和 `board` 是库的本地派生分类；`board` 如 `bse_listed_stock`、科创板、主板等是交易板块，不是行业或概念。

此前测试沪深 40 只和港股 14 只均按代码匹配；北交所代码表返回 355 条。例如 `bj920799` 返回名称 `艾融软件`，港股 `00175` 返回 `吉利汽车`。`sh688409` 返回 `XD富创精`，与输入清单中的“富创精密”不同。名称直接保存上游值，别名由用户单独维护；不自动删除 `XD` 等标记。

脚本以当前代码表核对，空表、连接错误、证券不在返回列表都无法证明证券不存在或退市。失败不创建记录，也不因上游暂时缺失删除已有记录。首次添加才取上游名称；已存在记录跳过，不刷新名称和个人字段。

## 个股题材与所属板块

`client.helpers.stock_topics(code)` 返回 `StockTopics`：`code`、`count`、`topics`。每个 `StockTopic` 包含字符串 `topic_id`、`topic_name`，以及可能为空的 `relation_level`、`selected_date`、`topic_date`、`reason`、`detail_id`、`category_raw`、`source`、`raw`。`topic_id` 不一定是数字；`category_raw` 是原始服务端类别标记，未确认完整映射。

涪陵电力 `sh600452` 实测的部分结果：

```json
{"code":"sh600452","count":8,"topics":[
  {"topic_id":"622","topic_name":"节能环保","category_raw":2,"relation_level":3.0},
  {"topic_id":"1037","topic_name":"近期新低","category_raw":4,"relation_level":4.0},
  {"topic_id":"X620101001","topic_name":"水电","category_raw":null,"relation_level":null}
]}
```

`MacClient.get_belong_board(market, code)` 返回 `list[BelongBoardInfo]`；字段为 `board_type`、`market`、`board_code`、`board_name`、`close`、`pre_close`。例如沪市 `600452` 实测包含：

```json
{"board_type":4,"market":1,"board_code":"880558","board_name":"节能环保","close":2917.43,"pre_close":3005.39}
```

这里的 `market` 是返回板块的市场，不能用作输入股票市场。文档中 `BoardType` 的 `0=行业一级、1=行业二级、3=概念` 是查询枚举；实测返回 `board_type` 与之不匹配，不能直接映射。北交所 `920799` 的题材和板块已返回；港股个股所属板块尚未验证成功。两种接口的覆盖和分类口径不同，空结果不能单独解释为没有板块。A 股导入使用下述所属板块和分类名单匹配，不直接导入全部个股题材。

参考：[代码表](https://github.com/electkismet/eltdx/blob/main/docs/methods/7709-%E4%BB%A3%E7%A0%81%E8%A1%A8.md)、[个股概念](https://github.com/electkismet/eltdx/blob/main/docs/helpers/%E4%B8%AA%E8%82%A1%E6%A6%82%E5%BF%B5%E6%9D%BF%E5%9D%97.md)、[所属板块](https://electkismet.github.io/eltdx/extended/mac-get_belong_board/)、[扩展行情](https://electkismet.github.io/eltdx/EXTENDED_MARKET/)。

## A 股行业和概念分类

A 股使用 `MacClient.get_belong_board` 查询个股所属板块，再按 `(market, board_code)` 与 `get_board_list(BoardType.HY/HY2/GN)` 三份分类名单关联；依次保存命中的一级和二级行业名称并去重。两级行业均未命中时，取所属板块返回顺序中的第一个概念兜底，该顺序不代表重要性。不依赖返回的 `board_type` 直接映射。分类名单或所属板块为空、匹配为空、接口失败均视为失败，不能证明股票没有行业概念。上游名单覆盖及分类可能变动。

2026-11-01 实测：涪陵电力匹配 `电力`、`电能综合服务` 和概念 `节能环保`；按当前规则只保存两个行业。A 股新建且未指定 concepts 时自动获取；可手工提供 concepts。`refresh-industry --market sh|sz|bj [--code CODE]` 显式刷新，失败不覆盖现有值。重复导入跳过已有记录。
