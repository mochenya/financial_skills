import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';

const ENDPOINT = 'https://www.cls.cn/v1/roll/get_roll_list';
const USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
const PAGE_SIZE = 20;
const COMMON = { app: 'CailianpressWeb', os: 'web', sv: '8.7.9' };

type Sort = 'time' | 'reads' | 'reads-per-minute';
type RawItem = { id: number; ctime: number; title: string; content: string; reading_num: number; type?: number };
type Options = { limit?: number; since?: number; sort: Sort; nowMs: number };
type Item = { id: number; type: number | null; title: string | null; content: string; published_at: string; published_timestamp: number; reads: number; reads_per_minute: number | null };

function fail(message: string): never { throw new Error(message); }
function sign(params: Record<string, string>): string {
  const input = Object.keys(params).sort().map(key => `${key}=${params[key]}`).join('&');
  const sha1 = createHash('sha1').update(input).digest('hex');
  return createHash('md5').update(sha1).digest('hex');
}
function formatBeijing(ms: number): string {
  return new Date(ms + 8 * 3600_000).toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, '+08:00');
}
export function parseSince(value: string, nowMs: number): number {
  const relative = /^(\d+)(m|h|d)$/.exec(value);
  if (relative) {
    const amount = Number(relative[1]);
    const duration = amount * ({ m: 60_000, h: 3600_000, d: 86400_000 } as Record<string, number>)[relative[2]];
    if (!Number.isSafeInteger(duration) || duration <= 0 || !Number.isFinite(new Date(nowMs - duration).getTime())) fail('--since 的时长必须是有效的正数');
    return nowMs - duration;
  }
  const match = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/.exec(value);
  if (!match) fail('--since 请使用 30m、2h、1d 或 "YYYY-MM-DD HH:mm:ss"（北京时间）');
  const iso = `${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:${match[6]}+08:00`;
  const result = Date.parse(iso);
  if (!Number.isFinite(result) || formatBeijing(result) !== `${value}+08:00`) fail('--since 不是有效的北京时间');
  if (result > nowMs) fail('--since 不能晚于当前时间');
  return result;
}
function record(value: unknown, location: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) fail(`上游响应不符合预期：${location} 应为对象`);
  return value as Record<string, unknown>;
}
function validateItem(value: unknown, index: number): RawItem {
  const item = record(value, `roll_data[${index}]`);
  for (const field of ['id', 'ctime', 'reading_num']) {
    if (typeof item[field] !== 'number' || !Number.isSafeInteger(item[field]) || (item[field] as number) < (field === 'reading_num' ? 0 : 1)) {
      fail(`上游响应不符合预期：roll_data[${index}].${field} 应为${field === 'reading_num' ? '非负' : '正'}整数，实际为 ${item[field] === null ? 'null' : typeof item[field]}`);
    }
  }
  for (const field of ['title', 'content']) {
    if (typeof item[field] !== 'string') fail(`上游响应不符合预期：roll_data[${index}].${field} 应为字符串，实际为 ${item[field] === null ? 'null' : typeof item[field]}`);
  }
  if (!Number.isFinite(new Date((item.ctime as number) * 1000).getTime())) fail(`上游响应不符合预期：roll_data[${index}].ctime 超出日期范围`);
  return item as RawItem;
}
export async function fetchPage(lastTime: number): Promise<RawItem[]> {
  const params: Record<string, string> = { ...COMMON, last_time: String(lastTime), refresh_type: '1', rn: String(PAGE_SIZE) };
  const url = new URL(ENDPOINT);
  for (const key of Object.keys(params).sort()) url.searchParams.set(key, params[key]);
  url.searchParams.set('sign', sign(params));
  let response: Response;
  try {
    response = await fetch(url, { headers: { 'User-Agent': USER_AGENT, Referer: 'https://www.cls.cn/telegraph', Accept: 'application/json, text/plain, */*' }, signal: AbortSignal.timeout(15_000) });
  } catch (error) { fail(`请求财联社失败：${error instanceof Error ? error.message : String(error)}`); }
  if (!response.ok) fail(`财联社请求失败：HTTP ${response.status}`);
  let payload: unknown;
  try { payload = await response.json(); } catch { fail('上游响应不是有效的 JSON'); }
  const root = record(payload, '响应');
  if (root.errno !== 0) fail(`财联社接口错误：errno=${String(root.errno)}，msg=${String(root.msg ?? '')}`);
  const data = record(root.data, 'data');
  if (!Array.isArray(data.roll_data)) fail('上游响应不符合预期：data.roll_data 应为数组');
  const items = data.roll_data.map(validateItem);
  if (items.some(item => item.ctime >= lastTime)) fail('上游分页响应包含游标时间或更新的记录，无法确认完整性');
  return items;
}
export async function collect(options: Options, getPage: (cursor: number) => Promise<RawItem[]> = fetchPage): Promise<{ items: Item[]; warnings: string[] }> {
  const seen = new Map<number, RawItem>();
  const nowSeconds = Math.floor(options.nowMs / 1000);
  let cursor = nowSeconds + 1;
  let previousOldest: number | undefined;
  while (true) {
    const page = await getPage(cursor);
    if (!page.length) break;
    for (const item of page) if (item.ctime <= nowSeconds) seen.set(item.id, item);
    const oldest = Math.min(...page.map(item => item.ctime));
    if (options.since !== undefined && oldest * 1000 < options.since) break;
    if (options.limit !== undefined && seen.size >= options.limit) break;
    if (page.length < PAGE_SIZE) break;
    if (previousOldest !== undefined && oldest >= previousOldest) fail(`分页停在时间戳 ${oldest}，无法确认同一秒的电报是否完整`);
    previousOldest = oldest;
    cursor = oldest + 1;
  }
  let raw = [...seen.values()].sort((a, b) => b.ctime - a.ctime || b.id - a.id);
  if (options.since !== undefined) raw = raw.filter(item => item.ctime * 1000 >= options.since!);
  if (options.limit !== undefined) raw = raw.slice(0, options.limit);
  let invalidAge = 0;
  const items: Item[] = raw.map(item => {
    const ageMinutes = (options.nowMs - item.ctime * 1000) / 60_000;
    if (ageMinutes <= 0) invalidAge++;
    return { id: item.id, type: item.type ?? null, title: item.title || null, content: item.content, published_at: formatBeijing(item.ctime * 1000), published_timestamp: item.ctime, reads: item.reading_num, reads_per_minute: ageMinutes > 0 ? Math.round(item.reading_num / ageMinutes * 100) / 100 : null };
  });
  if (options.sort !== 'time') {
    const key = options.sort === 'reads' ? 'reads' : 'reads_per_minute';
    items.sort((a, b) => (b[key] ?? -1) - (a[key] ?? -1) || b.published_timestamp - a.published_timestamp);
  }
  return { items, warnings: invalidAge ? [`${invalidAge} 条电报的发布时间不早于查询基准时间，相对阅读量为 null`] : [] };
}
function parseArgs(args: string[], nowMs: number): Options {
  let limit: number | undefined, since: number | undefined;
  let sort: Sort = 'time';
  const seen = new Set<string>();
  for (let i = 0; i < args.length; i++) {
    const key = args[i];
    if (!['--limit', '--since', '--sort'].includes(key)) fail(`未知参数：${key}`);
    if (seen.has(key)) fail(`参数不能重复：${key}`);
    seen.add(key);
    const value = args[++i];
    if (!value || value.startsWith('--')) fail(`${key} 需要一个值`);
    if (key === '--limit') {
      if (!/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(Number(value))) fail('--limit 必须是正整数');
      limit = Number(value);
    } else if (key === '--since') since = parseSince(value, nowMs);
    else if (value === 'time' || value === 'reads' || value === 'reads-per-minute') sort = value;
    else fail('--sort 仅支持 time、reads、reads-per-minute');
  }
  if ((limit === undefined) === (since === undefined)) fail('--limit 和 --since 必须且只能指定一个');
  return { limit, since, sort, nowMs };
}
const HELP = `用法：node telegraph.ts (--limit N | --since VALUE) [--sort time|reads|reads-per-minute]\n\n--since 支持 30m、2h、1d 或 "YYYY-MM-DD HH:mm:ss"（北京时间）。\n默认按发布时间降序；阅读速度为阅读量除以发布以来的分钟数。`;
async function main(): Promise<void> {
  const args = process.argv.slice(2);
  if (args.length === 1 && (args[0] === '--help' || args[0] === '-h')) { process.stdout.write(`${HELP}\n`); return; }
  const nowMs = Date.now();
  const options = parseArgs(args, nowMs);
  const result = await collect(options);
  for (const warning of result.warnings) process.stderr.write(`提示：${warning}\n`);
  process.stdout.write(`${JSON.stringify({ fetched_at: new Date(nowMs + 8 * 3600_000).toISOString().replace('T', ' ').replace('Z', '+08:00'), sort: options.sort, count: result.items.length, items: result.items }, null, 2)}\n`);
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => { process.stderr.write(`错误：${error instanceof Error ? error.message : String(error)}\n`); process.exitCode = 1; });
}
