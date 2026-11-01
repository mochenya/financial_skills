# 数据库契约与设计

## 范围与原则

连接变量为 `STOCK_POOL_DATABASE_URL`，数据库名 `personal_data`，schema 为 `stock_pool`，表为 `stocks`。URL 示例：`postgresql://用户:密码@主机:端口/personal_data`，凭据中的 URL 特殊字符需编码；不要在命令输出或文档中暴露真实凭据。schema 是数据库内的命名空间，并非独立数据库。

只维护个人股票池的一张表，不存行情、交易或板块字典。`(market, code)` 即股票身份，用联合主键阻止同一市场重复，无需额外 ID；同一代码不同市场允许各存一条。名称是导入时上游快照，个人信息独立维护，避免重复导入抹掉用户数据。未来扩展市场时先验证代码与接口，再调整约束；当前格式检查不证明证券真实存在或持续上市。

## 字段与约束

| 字段 | PostgreSQL 类型 | 约束与含义 |
| --- | --- | --- |
| `market` | `text` | 非空；只能是 `sh`、`sz`、`bj`、`hk`、`us`、`jp`、`kr`。是本地统一标识，不等于上游不同协议的数字市场号。 |
| `code` | `text` | 非空；沪深北六位数字、港股五位数字；美股为大写 Yahoo ticker，可包含类别股连字符。保留前导零，与 `market` 共同组成主键。 |
| `name` | `text` | 非空，`btrim(name) <> ''`；导入时获取的上游名称，可包含 `XD` 等前缀，不自动刷新或清洗。 |
| `alias` | `text` | 可空；用户自定义别名，可与上游名不同。 |
| `concepts` | `text[]` | 可空；沪深北保存通达信行业及概念或用户输入；港股、美股、日股与韩股保存 Yahoo 英文行业。`NULL` 为未填写或未取得，空数组为明确保存空列表；脚本要求数组元素为非空白字符串。 |
| `note` | `text` | 可空；个人备注。 |
| `is_followed` | `boolean` | 非空，默认 `true`；`false` 表示不再关注但保留记录及个人信息。 |
| `created_at` | `timestamptz` | 非空，默认 `now()`；首次创建时间，更新操作不修改。 |
| `updated_at` | `timestamptz` | 非空，默认 `now()`；脚本仅在字段实际变化时设为 `now()`，未变化时不动。 |

数据库约束与脚本校验不同：数据库不检查 `concepts` 内部元素，也不校验别名或备注的空字符串。`updated_at` 由脚本维护而非触发器，直接 SQL 更新须显式维护。`timestamptz` 保存时间点；输出的时区偏移由连接会话决定。

## 原建表定义（日韩扩展前）

以下是已采用的表结构；脚本不会自动执行建表。数据库 `personal_data` 使用专用账号 `personal_data_user`，该账号是数据库所有者；连接地址和密码仅通过环境变量配置。

```sql
CREATE SCHEMA stock_pool;
CREATE TABLE stock_pool.stocks (
    market text NOT NULL CHECK (market IN ('sh', 'sz', 'bj', 'hk', 'us')),
    code text NOT NULL,
    name text NOT NULL CHECK (btrim(name) <> ''),
    alias text,
    concepts text[],
    note text,
    is_followed boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (market, code),
    CHECK (
        (market IN ('sh', 'sz', 'bj') AND code ~ '^[0-9]{6}$')
        OR (market = 'hk' AND code ~ '^[0-9]{5}$')
        OR (market = 'us' AND code ~ '^[A-Z0-9]+(-[A-Z0-9]+)*$')
    )
);
```

主键自动提供唯一索引，当前规模无需额外索引。新增、导入、修改和物理删除均为数据库写操作；导入逐条事务提交，可能部分成功。

## 美股扩展

已增加 `us` 市场，代码为 Yahoo ticker；美股 concepts 保存 Yahoo 的 industry，A 股支持通达信行业和概念，港股使用 Yahoo 英文行业。实际数据库约束已完成迁移。

## 日本和韩国扩展

脚本支持 `jp` 的四位字母数字加 `.T`，以及 `kr` 的六位数字加 `.KS` 或 `.KQ`。实际数据库约束已迁移，允许写入日韩市场；上述原建表定义描述迁移前状态。名称和 concepts 按 Yahoo 美股规则获取。
