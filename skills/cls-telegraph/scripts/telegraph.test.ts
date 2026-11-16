import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { collect, fetchPage, parseSince } from './telegraph.ts';

const item = (id: number, ctime: number, reads = 100) => ({ id, ctime, title: '', content: `news ${id}`, reading_num: reads });

test('时间输入支持相对时长和北京时间，并拒绝无效日期', () => {
  const now = Date.parse('2026-11-16T17:00:00+08:00');
  assert.equal(parseSince('2h', now), Date.parse('2026-11-16T15:00:00+08:00'));
  assert.equal(parseSince('2026-11-16 09:30:00', now), Date.parse('2026-11-16T09:30:00+08:00'));
  assert.throws(() => parseSince('2026-02-30 09:30:00', now));
  assert.throws(() => parseSince('0h', now));
});

test('跨页重叠同秒并去重，先选最近条数再排序', async () => {
  const first = Array.from({length: 20}, (_, i) => item(i + 1, 1000 - i, i));
  const second = [item(20, 981, 19), item(21, 981, 999), item(22, 980, 1000)];
  const cursors: number[] = [];
  const result = await collect({nowMs: 1100_000, limit: 21, sort: 'reads'}, async cursor => { cursors.push(cursor); return cursors.length === 1 ? first : second; });
  assert.deepEqual(cursors, [1101, 982]);
  assert.equal(result.items.length, 21);
  assert.equal(result.items[0].content, 'news 21');
  assert.ok(!result.items.some(x => x.content === 'news 22'));
});

test('同秒满页无法推进时报告不完整', async () => {
  const page = Array.from({length: 20}, (_, i) => item(i + 1, 900));
  await assert.rejects(collect({nowMs: 1000_000, since: 800_000, sort: 'time'}, async () => page), /无法确认/);
});

test('正确签名并检查上游字段类型', async () => {
  const fake = mock.method(globalThis, 'fetch', async (url) => {
    assert.match(String(url), /sign=d52e26f813937bf362e5281bce0d827d/);
    return new Response(JSON.stringify({errno: 0, data: {roll_data: [{...item(1, 1794819201), reading_num: '123'}]}}));
  });
  try { await assert.rejects(fetchPage(1794819300), /reading_num/); } finally { fake.mock.restore(); }
});
