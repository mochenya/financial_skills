"""把 latest.json 变成中文夜报骨架（数据全中文，异动原因留待检索后补写）。

用法：python3 scripts/brief.py --work ./work [--out 夜报_YYYY-MM-DD.md]
产出：中文 Markdown；同时打印到 stdout。原因一栏由模型按 SKILL.md 的检索协议补写。
"""
import argparse, csv, json, os, statistics as st
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

IND_ZH = {
    "Semiconductors": "半导体", "Electronic Production Equipment": "半导体设备",
    "Electronic Equipment/Instruments": "电子仪器设备", "Electronic Components": "电子元器件",
    "Computer Peripherals": "存储与电脑外设", "Computer Processing Hardware": "算力硬件",
    "Telecommunications Equipment": "通信设备", "Packaged Software": "软件（应用）",
    "Internet Software/Services": "互联网平台", "Information Technology Services": "IT 服务",
    "Data Processing Services": "数据中心服务", "Precious Metals": "黄金白银",
    "Other Metals/Minerals": "其他金属矿产", "Integrated Oil": "综合石油",
    "Oil & Gas Production": "油气开采", "Oil & Gas Pipelines": "油气管道",
    "Electric Utilities": "电力公用", "Hotels/Resorts/Cruise lines": "酒店旅游邮轮",
    "Restaurants": "餐饮", "Food: Specialty/Candy": "食品", "Beverages: Non-Alcoholic": "饮料",
    "Chemicals: Specialty": "特种化工", "Chemicals: Agricultural": "农化",
    "Industrial Machinery": "工业机械", "Industrial Specialties": "工业特材",
    "Trucks/Construction/Farm Machinery": "工程机械", "Auto Parts: OEM": "汽车零部件",
    "Motor Vehicles": "汽车", "Aerospace & Defense": "航空航天与国防",
    "Investment Banks/Brokers": "投行券商", "Finance/Rental/Leasing": "支付与租赁",
    "Major Banks": "大型银行", "Regional Banks": "区域银行", "Investment Managers": "资管",
    "Financial Publishing/Services": "金融信息服务", "Property/Casualty Insurance": "财险",
    "Life/Health Insurance": "寿险健康险", "Specialty Stores": "专业零售",
    "Food Retail": "食品零售", "Apparel/Footwear Retail": "服饰零售", "Tobacco": "烟草",
    "Advertising/Marketing": "广告传媒", "Other Consumer Services": "消费服务",
    "Other Transportation": "交通出行", "Medical Specialties": "医疗器械",
    "Medical Instruments": "医疗器械", "Homebuilding": "住宅建筑", "Electrical Products": "电气设备",
    "Metal Fabrication": "金属加工", "Steel": "钢铁", "Aluminum": "铝", "Coal": "煤炭",
    "Uranium": "铀", "Packaging/Containers": "包装", "Wholesale Distributors": "批发分销",
    "Miscellaneous Commercial Services": "商业服务", "Air Freight/Couriers": "航空货运",
    "Real Estate Development": "地产开发", "Industrial Conglomerates": "综合工业",
}


def load_names(work, metrics):
    zh = {}
    p = os.path.join(HERE, "names_zh.json")
    if os.path.exists(p):
        zh.update({k: v for k, v in json.load(open(p)).items() if not k.startswith("_")})
    import re
    for t, m in metrics.items():
        a = m.get("alias") or ""
        if re.search(r"[\u4e00-\u9fff]", a):
            # alias 自带中文优先；截到第一个括号为止，兼容 "伯克希尔(BERKSHIRE)-B" 这种尾巴
            zh[t] = re.split(r"[(（]", a)[0].strip()
    return zh


def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def s(v, fmt="+.1f", suf="%"):
    return format(v, fmt) + suf if isinstance(v, (int, float)) else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="./work")
    ap.add_argument("--out")
    a = ap.parse_args()
    D = json.load(open(os.path.join(a.work, "latest.json")))
    M, B = D["metrics"], D["bench"]
    rows = [m for m in M.values() if not m.get("thin")]
    thin = [m["ticker"] for m in M.values() if m.get("thin")]
    zh = load_names(a.work, M)

    def name(t):
        """中文名优先；无中文名时回落公司英文简称，绝不重复显示代码。"""
        if t in zh:
            return zh[t]
        d = (M[t].get("desc") or "").split(",")[0].strip()
        for suf in (" Inc.", " Inc", " Corporation", " Corp.", " Corp", " plc", " Ltd."):
            d = d.replace(suf, "")
        return d or t
    ind = lambda k: IND_ZH.get(k, k)

    asof = max(m["last_date"] for m in rows)
    adv = sum(1 for m in rows if (m["r1"] or 0) > 0)
    up50 = sum(1 for m in rows if (m["vs50"] or 0) > 0)
    up200 = sum(1 for m in rows if (m["vs200"] or 0) > 0)
    beta_med = med([m["r1"] for m in rows])

    # 广度变化：用日线重算近 6 个交易日 "站上 MA50 家数"
    hist = {}
    hd = os.path.join(a.work, "history")
    for t in [m["ticker"] for m in rows]:
        p = os.path.join(hd, t.lower().replace("-", ".") + ".csv")
        if os.path.exists(p):
            hist[t] = sorted([(r["date"], float(r["adj"] or r["close"]))
                              for r in csv.DictReader(open(p))], key=lambda x: x[0])

    def breadth(k):
        cnt = tot = 0
        for t, h in hist.items():
            i = len(h) - 1 - k
            if i < 50:
                continue
            v = [x[1] for x in h]
            tot += 1
            cnt += 1 if v[i] > sum(v[i - 49:i + 1]) / 50 else 0
        return cnt, tot

    b_now, tot = breadth(0)
    b_prev, _ = breadth(1)
    b_5, _ = breadth(5)

    sec = {}
    for m in rows:
        sec.setdefault(m["industry"], []).append(m)
    rot = [(k, len(v), med([x["r20"] for x in v]), sum(1 for x in v if (x["vs50"] or 0) > 0))
           for k, v in sec.items() if len(v) >= 3]
    rot.sort(key=lambda x: -(x[2] or -99))
    spy20 = B.get("SPY", {}).get("r20") or 0

    L = []
    A = L.append
    A(f"# 美股关注池 · 夜报复盘\n")
    A(f"**统计日 {asof} 收盘**｜池内 {len(M) + len(D.get('unresolved', []))} 只，有效 {len(rows)} 只"
      + (f"｜历史不足 {thin}" if thin else "") + "\n")
    A("## 一、整体结果\n")
    A(f"- 上涨 **{adv}** / 下跌 **{len(rows) - adv}**，中位 **{s(beta_med, '+.2f')}**")
    if "SPY" in B:
        A(f"- 对照：标普500 {s(B['SPY']['r1'], '+.2f')}｜纳指100 {s(B['QQQ']['r1'], '+.2f')}"
          f"｜半导体指数 {s(B['SMH']['r1'], '+.2f')}｜黄金ETF {s(B['GLD']['r1'], '+.2f')}"
          f"｜能源 {s(B['XLE']['r1'], '+.2f')}｜公用 {s(B['XLU']['r1'], '+.2f')}")
        A(f"- 相对标普超额 **{s(beta_med - B['SPY']['r1'], '+.2f')}**；"
          f"中位距 52 周高 **{s(med([m['off_hi'] for m in rows]), '+.1f')}**")
    A(f"- 站上 50 日线 **{up50}**（{up50 / len(rows) * 100:.0f}%，日变 {b_now - b_prev:+d}、5日 {b_now - b_5:+d}）"
      f"｜站上 200 日线 {up200}（{up200 / len(rows) * 100:.0f}%）")
    A(f"- 中位涨跌：1日 {s(beta_med, '+.2f')}｜5日 {s(med([m['r5'] for m in rows]), '+.2f')}"
      f"｜20日 {s(med([m['r20'] for m in rows]), '+.2f')}｜当日创新高 {sum(1 for m in rows if m['new_hi'])} 只\n")

    A("## 二、行业分化\n")
    A("**抗跌 / 上涨**\n")
    A("| 行业 | 只数 | 当日 | 20日 | 站上50日线 |")
    A("|---|---|---|---|---|")
    for k, n, r20, ab in [r for r in rot if (r[2] or 0) > spy20][:6]:
        a1 = med([m["r1"] for m in sec[k]])
        A(f"| {ind(k)} | {n} | {s(a1, '+.2f')} | {s(r20, '+.2f')} | {ab}/{n} |")
    A("\n**重灾区**\n")
    A("| 行业 | 只数 | 当日 | 20日 | 站上50日线 |")
    A("|---|---|---|---|---|")
    for k, n, r20, ab in [r for r in rot if (r[2] or 0) <= spy20][-6:][::-1]:
        a1 = med([m["r1"] for m in sec[k]])
        A(f"| {ind(k)} | {n} | {s(a1, '+.2f')} | {s(r20, '+.2f')} | {ab}/{n} |")
    A("")

    def movers(title, items, note=""):
        A(f"**{title}**{note}\n")
        A("| 公司 | 代码 | 行业 | 收盘 | 当日 | 波动倍数 | 量比 | RSI | 距高 |")
        A("|---|---|---|---|---|---|---|---|---|")
        for m in items:
            A(f"| {name(m['ticker'])} | {m['ticker']} | {ind(m['industry'])} | {m['close']:.2f} "
              f"| {s(m['r1'], '+.2f')} | {s(abs(m['sigma'] or 0), '.1f', '倍')} | {s(m['volratio'], '.1f', 'x')} "
              f"| {s(m['rsi'], '.0f', '')} | {s(m['off_hi'], '+.1f')} |")
        A("")

    A("## 三、异动个股\n")
    by_chg = sorted(rows, key=lambda m: -(m["r1"] or 0))
    movers("涨幅前 8", by_chg[:8])
    movers("跌幅前 8", by_chg[-8:][::-1])

    shock = sorted([m for m in rows if abs(m["sigma"] or 0) >= 2 or (m["volratio"] or 0) >= 2.5],
                   key=lambda m: -abs(m["sigma"] or 0))[:8]
    A("## 四、待归因清单（须检索原因，按优先级）\n")
    for m in shock:
        A(f"- **{name(m['ticker'])}（{m['ticker']}）** {s(m['r1'], '+.2f')}，"
          f"波动 {s(abs(m['sigma'] or 0), '.1f', '倍')}、量比 {s(m['volratio'], '.1f', 'x')}，"
          f"距高 {s(m['off_hi'], '+.1f')}，PE {s(m['pe'], '.0f', '')}，"
          f"下一财报 {'待定' if not m.get('next_earn') else datetime.fromtimestamp(m['next_earn']).strftime('%m-%d')}")
    A("")

    now = datetime.strptime(asof, "%Y-%m-%d").timestamp()
    cal = sorted([m for m in rows if m.get("next_earn") and 0 <= m["next_earn"] - now <= 7 * 86400],
                 key=lambda m: m["next_earn"])
    A("## 五、未来 7 天财报\n")
    if cal:
        A("| 日期 | 公司 | 代码 | 市值(十亿$) | PE | 距高 |")
        A("|---|---|---|---|---|---|")
        for m in cal:
            A(f"| {datetime.fromtimestamp(m['next_earn']).strftime('%m-%d')} | {name(m['ticker'])} "
              f"| {m['ticker']} | {m['mcap_bn']:.0f} | {s(m['pe'], '.0f', '')} | {s(m['off_hi'], '+.1f')} |")
    A("")
    A("## 六、创 52 周新高\n")
    for m in sorted([x for x in rows if x["new_hi"]], key=lambda m: -(m["mcap_bn"] or 0))[:10]:
        A(f"- {name(m['ticker'])}（{m['ticker']}）{m['close']:.2f} {s(m['r1'], '+.2f')}，"
          f"{ind(m['industry'])}，RSI {s(m['rsi'], '.0f', '')}")

    md = "\n".join(L)
    out = a.out or os.path.join(a.work, f"夜报骨架_{asof}.md")
    open(out, "w").write(md)
    print(md)
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    main()
