---
name: cls-telegraph
description: 获取财联社电报最近 N 条或从指定时间到现在的电报，按时间、阅读量或平均阅读速度排序并输出 JSON；适用于查询财联社快讯，不用于查询个股行情。
---

# 财联社电报

使用 Node.js 24 或支持原生 TypeScript 类型剥离的较新版本运行脚本；不需要安装依赖。将 `${SKILL_DIR}` 替换为本 Skill 目录的绝对路径。

```bash
node "${SKILL_DIR}/scripts/telegraph.ts" --limit 20
node "${SKILL_DIR}/scripts/telegraph.ts" --limit 100 --sort reads
node "${SKILL_DIR}/scripts/telegraph.ts" --since 2h --sort reads-per-minute
node "${SKILL_DIR}/scripts/telegraph.ts" --since "2026-11-16 09:30:00"
```

`--limit` 和 `--since` 必须且只能指定一个；`--since` 支持正整数分钟、小时、天（如 `30m`、`2h`、`1d`），或者 `YYYY-MM-DD HH:mm:ss` 格式的北京时间，截止到运行时刻。`--sort` 可选 `time`、`reads`、`reads-per-minute`，默认时间降序；所有排序均为降序。先确定最近 N 条或时间范围，再对选中结果排序。

成功时标准输出为 JSON，包含 `fetched_at`、`sort`、`count`、`items`。每条电报包含 `id`、`type`、`title`、`content`、`published_at`（UTC+8）、`published_timestamp`（Unix 秒）、`reads`、`reads_per_minute`。`id` 可直接拼成详情页 `https://www.cls.cn/detail/{id}`，用于逐条回链。空标题为 `null`；平均阅读速度为阅读量除以从发布时间到本次查询基准时间的分钟数，保留两位小数；时间差不为正时为 `null`。提示和错误写入标准错误，失败时退出码非零，不输出部分结果。`fetched_at` 是查询开始时间，阅读量是各页获取时的快照，不是历史时刻的阅读量；新发布内容的平均速度容易偏高。上游列表可能混有研报等非电报条目（普通电报 `type` 为 `-1`，研报为 `20021`），脚本按上游列表原样返回，未按类型过滤，需要时由调用方按 `type` 自行筛选。

数据来自财联社网页使用的非公开列表接口，可能变更或受限。脚本校验所需字段、重叠分页并按上游 ID 去重；若分页无法前进，会报错而不声称结果完整。上游删除、延迟和过滤的内容无法由脚本保证完整。运行失败时报告实际错误，不要把失败当作空结果。

需要开发、调整接口适配或排查上游变化时，阅读 [接口研究](references/api.md)，其中记录请求参数、签名、响应和分页边界。
