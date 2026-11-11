#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["tvscreener==0.8.1", "eltdx==3.3.5", "openpyxl>=3.1,<4", "requests>=2.31,<3"]
# ///
import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from tvscreener import Market, Preset, StockScreener
from tvscreener.core.base import REQUEST_HEADERS
from eltdx.ex import MacExClient

MARKETS = {
    'china': (Market.CHINA, 'A股', 'CNY', 5_000_000_000),
    'hongkong': (Market.HONGKONG, '港股', 'HKD', 10_000_000_000),
    'america': (Market.AMERICA, '美股', 'USD', 10_000_000_000),
}
FIELDS = [
    ('市场', None), ('代码', 'symbol'), ('名称', 'description'), ('总市值', 'market_cap_basic'),
    ('币种', 'currency'), ('涨跌幅(%)', 'change'), ('最新价', 'close'), ('当日最高价', 'high'),
    ('历史最高价', 'High.All'), ('成交量', 'volume'), ('成交额候选', 'Value.Traded'), ('换手率估算(%)', None),
    ('市盈率TTM', 'price_earnings_ttm'), ('板块', 'sector.tr'), ('行业', 'industry.tr'),
    ('板块原文', 'sector'), ('行业原文', 'industry'),
    ('开盘价', 'open'), ('最低价', 'low'), ('10日平均成交量', 'average_volume_10d_calc'),
    ('相对成交量', 'relative_volume_10d_calc'), ('流通股数', 'float_shares_outstanding'),
    ('市净率MRQ', 'price_book_fq'), ('另一历史高点字段', 'all_time_high'),
    ('另一历史高点日期原值', 'all_time_high_day'), ('行情更新时间UTC', None), ('行情更新时间原值', 'last-price-update-time'),
    ('K线更新时间原值', 'last_bar_update_time'), ('K线时间原值', 'time'), ('交易所', 'exchange'),
    ('证券类型', 'type'), ('证券子类型', 'typespecs'), ('采集时间UTC', None),
]
COLUMNS = list(dict.fromkeys(key for _, key in FIELDS if key and key != 'symbol'))
XLSX_FIELDS = [
    ('市场', '市场'), ('代码', '代码'), ('名称', '名称'), ('板块', '板块'), ('总市值(亿)', '总市值'),
    ('涨跌幅(%)', '涨跌幅(%)'), ('最新价', '最新价'), ('当日最高价', '当日最高价'),
    ('历史最高价', '历史最高价'), ('相对成交量', '相对成交量'),
    ('换手率(%)', '换手率估算(%)'),
    ('市盈率', '市盈率TTM'), ('行业', '行业'),
    ('开盘价', '开盘价'), ('最低价', '最低价'), ('市净率MRQ', '市净率MRQ'),
    ('行情更新时间', '行情更新时间UTC'), ('采集时间', '采集时间UTC'),
]

def is_a_share(row):
    exchange = row.get('exchange')
    code = row['symbol'].split(':', 1)[-1]
    prefixes = {'SSE': ('600', '601', '603', '605', '688', '689'),
                'SZSE': ('000', '001', '002', '003', '300', '301'),
                'BSE': ('4', '8', '92'), 'BJSE': ('4', '8', '92')}
    return len(code) == 6 and code.isdigit() and code.startswith(prefixes.get(exchange, ()))

def fetch_market(key):
    market, _, _, _ = MARKETS[key]
    screener = StockScreener().set_markets(market).set_preset(Preset.ALL_TIME_HIGH)
    screener.options['lang'] = 'zh'
    rows, start, total = [], 0, None
    while True:
        screener.set_range(start, start + 5000)
        payload = screener._build_payload(COLUMNS)
        response = requests.post(screener._request_url(), json=payload, headers=REQUEST_HEADERS, timeout=30)
        response.raise_for_status()
        body = response.json()
        batch = body['data']
        if total is None:
            total = body['totalCount']
        for item in batch:
            if len(item['d']) != len(COLUMNS):
                raise ValueError(f'{key}: 返回字段数量与请求不一致')
            rows.append({'symbol': item['s'], **dict(zip(COLUMNS, item['d']))})
        start += len(batch)
        if start >= total:
            break
        if not batch:
            raise ValueError(f'{key}: 只返回 {start}/{total} 条，分页不完整')
    return rows, total

def convert(key, row, collected):
    result = {title: row.get(field) if field else None for title, field in FIELDS}
    result['市场'] = MARKETS[key][1]
    result['采集时间UTC'] = collected
    result['板块'] = row.get('sector.tr') or row.get('sector')
    result['行业'] = row.get('industry.tr') or row.get('industry')
    timestamp = row.get('last-price-update-time')
    if isinstance(timestamp, (int, float)) and math.isfinite(timestamp):
        try:
            result['行情更新时间UTC'] = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    volume, shares = row.get('volume'), row.get('float_shares_outstanding')
    if isinstance(volume, (int, float)) and isinstance(shares, (int, float)) and shares > 0:
        result['换手率估算(%)'] = volume / shares * 100
    return result

def enrich_names(rows):
    targets = {}
    for row in rows:
        market = row['市场']
        exchange, ticker = row['代码'].split(':', 1)
        if market == '港股' and exchange == 'HKEX' and ticker.isdigit() and len(ticker) <= 5:
            key = (31, ticker.zfill(5))
        elif market == '美股' and exchange in ('NYSE', 'NASDAQ', 'AMEX'):
            key = (74, ticker.upper())
        else:
            continue
        targets.setdefault(key, []).append(row)
    if not targets:
        return {'待匹配': 0, '中文名称匹配': 0, '保留原名': 0}
    matched = 0
    try:
        with MacExClient(timeout=5) as client:
            keys = list(targets)
            for offset in range(0, len(keys), 50):
                batch = keys[offset:offset + 50]
                for quote in client.goods_quotes(batch):
                    key = (quote.market, quote.code)
                    name = (quote.name or '').strip()
                    if key not in targets or not any('\u4e00' <= ch <= '\u9fff' for ch in name):
                        continue
                    for row in targets.pop(key):
                        row['名称原文'] = row['名称']
                        row['名称'] = name
                        matched += 1
    except Exception as exc:
        print(f'eltdx 中文名称查询失败，未匹配项保留原名：{exc}', file=sys.stderr)
    remaining = sum(len(items) for items in targets.values())
    return {'待匹配': matched + remaining, '中文名称匹配': matched, '保留原名': remaining}

def build_data(selected, no_filter):
    rows, stats = [], {}
    for key in selected:
        raw, total = fetch_market(key)
        collected = dt.datetime.now(dt.timezone.utc).isoformat()
        eligible, excluded_type, excluded_cap = [], 0, 0
        for row in raw:
            if row.get('type') != 'stock' or 'common' not in (row.get('typespecs') or []) or (key == 'china' and not is_a_share(row)):
                excluded_type += 1
                continue
            if not no_filter:
                cap = row.get('market_cap_basic')
                if row.get('currency') != MARKETS[key][2] or not isinstance(cap, (int, float)) or not math.isfinite(cap) or cap < MARKETS[key][3]:
                    excluded_cap += 1
                    continue
            eligible.append(convert(key, row, collected))
        rows.extend(eligible)
        stats[key] = {'接口总数': total, '类型排除数': excluded_type, '市值或币种排除数': excluded_cap, '导出数': len(eligible), '采集时间UTC': collected}
    names = enrich_names(rows)
    rows.sort(key=lambda row: (row['总市值'] is None, -(row['总市值'] or 0), row['市场']))
    return {'筛选': '不过滤市值' if no_filter else 'A股≥50亿元人民币；港股≥100亿港元；美股≥100亿美元', '统计': stats, '名称匹配': names, '数据': rows}

def write_xlsx(path, data, selected):
    wb = Workbook()
    wb.remove(wb.active)
    groups = [('A股港股', {'A股', '港股'}), ('美股', {'美股'})]
    selected_names = {MARKETS[k][1] for k in selected}
    for name, members in groups:
        if not members & selected_names:
            continue
        ws = wb.create_sheet(name)
        ws.sheet_view.showGridLines = False
        ws.sheet_view.zoomScale = 85
        last_col = get_column_letter(len(XLSX_FIELDS))
        for row_number in (1, 2, 3, 4):
            ws.merge_cells(f'A{row_number}:{last_col}{row_number}')
        ws['A1'] = f'{name} · 历史新高'
        ws['A1'].font = Font(name='思源宋体', size=18, bold=True, color='FFFFFF')
        ws['A1'].fill = PatternFill('solid', fgColor='193B57')
        ws['A1'].alignment = Alignment(vertical='center', indent=1)
        applicable = [k for k in selected if MARKETS[k][1] in members]
        if data['筛选'] == '不过滤市值':
            condition = '市值筛选：未启用'
        else:
            labels = {'china': 'A股 ≥ 50亿元', 'hongkong': '港股 ≥ 100亿港元', 'america': '美股 ≥ 100亿美元'}
            condition = '市值筛选：' + '    /    '.join(labels[k] for k in applicable)
        ws['A2'] = condition
        times = [dt.datetime.fromisoformat(row['行情更新时间UTC']) for row in data['数据']
                 if row['市场'] in members and row['行情更新时间UTC']]
        latest = max(times).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y年%m月%d日 %H:%M') if times else '暂无数据'
        ws['A3'] = f'最新行情更新时间（北京时间）：{latest}     |     市值单位：各市场本币 · 亿'
        ws['A4'] = '备注：相对成交量＝当日成交量 ÷ 前10日平均成交量；换手率为估算值；市盈率为TTM。'
        for row_number in (2, 3, 4):
            cell = ws.cell(row_number, 1)
            cell.font = Font(name='思源宋体', size=10, bold=row_number == 2, color='2A4B62' if row_number != 4 else '687B88')
            cell.fill = PatternFill('solid', fgColor='EAF1F4' if row_number != 4 else 'F5F8F9')
            cell.alignment = Alignment(vertical='center', indent=1)
        ws.append([])
        ws.append([title for title, _ in XLSX_FIELDS])
        for cell in ws[6]:
            cell.font = Font(name='思源宋体', size=10, bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='37677A')
            cell.alignment = Alignment(horizontal='center', vertical='center')
        for row in data['数据']:
            if row['市场'] in members:
                values = []
                for title, key in XLSX_FIELDS:
                    value = row[key] if key is not None else None
                    if value is not None and key == '总市值':
                        value /= 100_000_000
                    elif value and key in ('行情更新时间UTC', '采集时间UTC'):
                        value = dt.datetime.fromisoformat(value).astimezone(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None)
                    values.append(value)
                ws.append(values)
        ws.freeze_panes = 'E7'
        ws.auto_filter.ref = f'A6:{last_col}{max(ws.max_row, 6)}'
        border = Border(bottom=Side(style='hair', color='DEE7E9'))
        for row_number in range(7, ws.max_row + 1):
            ws.row_dimensions[row_number].height = 23
            for cell in ws[row_number]:
                cell.font = Font(name='思源宋体', size=10, color='223744')
                cell.fill = PatternFill('solid', fgColor='F1F6F7' if row_number % 2 == 0 else 'FFFFFF')
                cell.border = border
                cell.alignment = Alignment(vertical='center', horizontal='left' if cell.column <= 4 else 'center')
        for row_number, height in ((1, 38), (2, 25), (3, 23), (4, 23), (5, 5), (6, 28)):
            ws.row_dimensions[row_number].height = height
        ws.sheet_format.zeroHeight = True
        ws.column_dimensions.group(get_column_letter(len(XLSX_FIELDS) + 1), 'XFD', hidden=True)
        ws.print_options.horizontalCentered = True
        ws.print_title_rows = '1:6'
        ws.print_area = f'A1:{last_col}{max(ws.max_row, 6)}'
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.page_setup.orientation = 'landscape'
        for i, (title, key) in enumerate(XLSX_FIELDS, 1):
            widths = {'市场': 9, '代码': 17, '名称': 30, '板块': 15, '行业': 20,
                      '行情更新时间': 18, '采集时间': 18, '备注': 24}
            ws.column_dimensions[get_column_letter(i)].width = widths.get(title, 15)
            if title in ('总市值(亿)', '涨跌幅(%)', '换手率(%)', '相对成交量', '市盈率', '市净率MRQ'):
                for cells in ws.iter_cols(min_col=i, max_col=i, min_row=7):
                    for cell in cells:
                        cell.number_format = '0.00'
            elif key in ('行情更新时间UTC', '采集时间UTC'):
                for cells in ws.iter_cols(min_col=i, max_col=i, min_row=7):
                    for cell in cells:
                        cell.number_format = 'm"月"d"日" h"时"mm"分"'
    wb.save(path)

def main():
    parser = argparse.ArgumentParser(description='导出 A 股、港股、美股历史新高快照')
    parser.add_argument('--market', choices=['all', 'ah', 'china', 'hongkong', 'america'], default='all', help='all=三个市场，ah=A股和港股')
    parser.add_argument('--no-market-cap-filter', action='store_true', help='关闭市值门槛；不会关闭证券类型过滤')
    parser.add_argument('--format', choices=['json', 'xlsx'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    selected = {'all': ['china', 'hongkong', 'america'], 'ah': ['china', 'hongkong']}.get(args.market, [args.market])
    if args.output.suffix.lower() != '.' + args.format:
        parser.error('输出文件扩展名必须与 --format 一致')
    try:
        data = build_data(selected, args.no_market_cap_filter)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.format == 'json':
            args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        else:
            write_xlsx(args.output, data, selected)
        print(json.dumps({'文件': str(args.output), '统计': data['统计'], '名称匹配': data['名称匹配']}, ensure_ascii=False, indent=2))
    except (requests.RequestException, ValueError, KeyError, OSError) as exc:
        print(f'导出失败: {exc}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
