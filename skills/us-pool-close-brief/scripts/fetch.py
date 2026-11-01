"""取美股关注池数据：快照 + 复权日线 + 指标 + 基准。

用法（在 skill 目录或任意 cwd 运行均可）：
    uv run --with nothing scripts/fetch.py --pool pool_us.json --work ./work
    # 或让脚本自己调 stock_pool.py 取池（需设 STOCK_POOL_SKILL）
    python3 scripts/fetch.py --work ./work

产出 work/latest.json：{"metrics": {...}, "bench": {...}, "missing": [...], "unresolved": [...]}
"""
import argparse, csv, json, os, statistics as st, subprocess, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
TV_COLS = ["name", "description", "close", "change", "volume", "relative_volume_10d_calc",
           "average_volume_30d_calc", "market_cap_basic", "price_earnings_ttm", "price_book_ratio",
           "dividends_yield", "earnings_per_share_diluted_ttm", "total_revenue_yoy_growth_ttm",
           "earnings_per_share_diluted_yoy_growth_ttm", "RSI", "Perf.W", "Perf.1M", "Perf.3M",
           "Perf.YTD", "price_52_week_high", "price_52_week_low", "beta_1_year",
           "price_target_average", "recommendation_mark", "earnings_release_next_date",
           "sector", "industry", "gap"]
BENCH = {"SPY": "标普500", "QQQ": "纳指100", "SMH": "半导体", "GLD": "黄金ETF",
         "TLT": "长债", "XLE": "能源", "XLU": "公用", "IWM": "小盘"}


def http_json(url, body=None, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=body,
                                         headers={"User-Agent": UA, "Accept": "application/json",
                                                  "Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=40))
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(3 * (i + 1))
        except Exception:
            time.sleep(3 * (i + 1))
    return None


def tv_scan(tickers, cols):
    body = json.dumps({"symbols": {"tickers": tickers}, "columns": cols}).encode()
    js = http_json("https://scanner.tradingview.com/america/scan", body)
    return {r["s"]: dict(zip(cols, r["d"])) for r in (js or {}).get("data", [])}


def load_pool(path):
    if path and os.path.exists(path):
        return json.load(open(path))["stocks"]
    skill = os.environ.get("STOCK_POOL_SKILL")
    if not skill:
        sys.exit("需要 --pool pool_us.json，或设 STOCK_POOL_SKILL 指向 stock-pool skill 目录")
    out = subprocess.run(["uv", "run", os.path.join(skill, "scripts", "stock_pool.py"),
                          "list", "--market", "us"], capture_output=True, text=True, check=True).stdout
    return json.loads(out)["stocks"]


def resolve(codes):
    """池内代码是 Yahoo 口径（BRK-B），TradingView 用点号（NYSE:BRK.B）。"""
    mapping = {}
    for ex in ("NASDAQ", "NYSE", "AMEX", "OTC"):
        for full in tv_scan([f"{ex}:{c.replace('-', '.')}" for c in codes], ["name"]):
            mapping[full.split(":")[1].replace(".", "-")] = full
    return {c: mapping[c] for c in codes if c in mapping}


def sa_slug(t):
    return t.lower().replace("-", ".")


def fetch_history(ticker, hist_dir):
    p = os.path.join(hist_dir, sa_slug(ticker) + ".csv")
    if os.path.exists(p):
        rows = list(csv.DictReader(open(p)))
        # 缓存判定必须同时看日期和 bar 数：只有 20 根 bar 的"新鲜"缓存会让 MA200/52 周静默失真
        if rows and max(r["date"] for r in rows) >= (date.today() - timedelta(days=4)).isoformat() \
                and len(rows) >= 200:
            return ticker, "cached"
    for rng in ("5Y", "2Y", "1Y"):
        js = http_json(f"https://stockanalysis.com/api/symbol/s/{sa_slug(ticker)}/history?range={rng}&period=Day")
        if js and js.get("status") == 200 and js.get("data"):
            data = sorted(js["data"], key=lambda x: x["t"])
            with open(p, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "open", "high", "low", "close", "adj", "volume"])
                for r in data:
                    w.writerow([r["t"], r["o"], r["h"], r["l"], r["c"], r.get("a"), r["v"]])
            return ticker, "ok"
    return ticker, "fail"


def read_hist(ticker, hist_dir):
    p = os.path.join(hist_dir, sa_slug(ticker) + ".csv")
    if not os.path.exists(p):
        return []
    rows = []
    for r in csv.DictReader(open(p)):
        try:
            rows.append({"d": r["date"], "h": float(r["high"]), "l": float(r["low"]),
                         "c": float(r["close"]), "a": float(r["adj"] or r["close"]),
                         "v": float(r["volume"] or 0)})
        except Exception:
            pass
    return sorted(rows, key=lambda x: x["d"])


def rsi(cl, n=14):
    if len(cl) < n + 1:
        return None
    g = sum(max(cl[i] - cl[i - 1], 0) for i in range(-n, 0))
    l = sum(max(cl[i - 1] - cl[i], 0) for i in range(-n, 0))
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool")
    ap.add_argument("--work", default="./work")
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args()
    hist_dir = os.path.join(a.work, "history")
    os.makedirs(hist_dir, exist_ok=True)

    pool = load_pool(a.pool)
    codes = [x["code"] for x in pool]
    alias = {x["code"]: (x.get("alias") or "") for x in pool}
    sym = resolve(codes)
    unresolved = [c for c in codes if c not in sym]
    snap = {}
    syms = [sym[c] for c in codes if c in sym]
    for i in range(0, len(syms), 150):
        snap.update(tv_scan(syms[i:i + 150], TV_COLS))

    print(f"[fetch] 池 {len(codes)}，解析 {len(sym)}，历史抓取中 ...", flush=True)
    status = {}
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for t, s in ex.map(lambda t: fetch_history(t, hist_dir), codes):
            status[t] = s
    print(f"[fetch] 历史 ok={(sum(1 for v in status.values() if v != 'fail'))} "
          f"fail={[k for k, v in status.items() if v == 'fail']}")

    M = {}
    for c in codes:
        h = read_hist(c, hist_dir)
        if len(h) < 20:          # 少于 20 根的标 thin，不写 0
            continue
        a_ = [x["a"] for x in h]
        v = [x["v"] for x in h]
        last = a_[-1]
        ret = lambda k: (last / a_[-1 - k] - 1) * 100 if len(a_) > k else None
        win = a_[-253:]
        sma = lambda n: sum(a_[-n:]) / n if len(a_) >= n else None
        vol20 = sum(v[-20:]) / 20 if len(v) >= 20 and sum(v[-20:]) > 0 else None
        rets = [a_[i] / a_[i - 1] - 1 for i in range(max(1, len(a_) - 252), len(a_))]
        sd = st.pstdev(rets) if len(rets) > 20 else None
        s = snap.get(sym.get(c, ""), {})
        m = {"ticker": c, "alias": alias.get(c, ""), "last_date": h[-1]["d"], "close": last,
             "r1": ret(1), "r5": ret(5), "r20": ret(20), "r60": ret(60),
             "hi52": max(win), "lo52": min(win), "off_hi": (last / max(win) - 1) * 100,
             "sma20": sma(20), "sma50": sma(50), "sma200": sma(200), "rsi": rsi(a_),
             "volratio": (v[-1] / vol20) if vol20 else None,
             "sigma": (ret(1) / (sd * 100)) if (sd and ret(1) is not None) else None,
             "new_hi": h[-1]["h"] >= max(x["h"] for x in (h[-253:] if len(h) >= 253 else h)) - 1e-9,
             "n_hist": len(a_), "thin": len(a_) < 200,
             "desc": s.get("description") or ""}
        m["vs50"] = (last / m["sma50"] - 1) * 100 if m["sma50"] else None
        m["vs200"] = (last / m["sma200"] - 1) * 100 if m["sma200"] else None
        m["industry"] = s.get("industry") or "?"
        m["sector"] = s.get("sector") or "?"
        m["mcap_bn"] = (s.get("market_cap_basic") or 0) / 1e9
        m["pe"] = s.get("price_earnings_ttm")
        m["pb"] = s.get("price_book_ratio")
        m["divy"] = s.get("dividends_yield")
        m["target"] = s.get("price_target_average")
        m["rec"] = s.get("recommendation_mark")
        m["next_earn"] = s.get("earnings_release_next_date")
        m["rev_g"] = s.get("total_revenue_yoy_growth_ttm")
        m["eps_g"] = s.get("earnings_per_share_diluted_yoy_growth_ttm")
        m["beta"] = s.get("beta_1_year")
        m["upside"] = (m["target"] / last - 1) * 100 if m["target"] else None
        M[c] = m

    bench = {}
    for b in BENCH:
        js = http_json(f"https://stockanalysis.com/api/symbol/s/{b}/history?range=2Y&period=Day")
        if not js or js.get("status") != 200:
            continue
        d = sorted(js["data"], key=lambda x: x["t"])
        x = [i["a"] for i in d]
        bench[b] = {"name": BENCH[b], "date": d[-1]["t"],
                    "r1": (x[-1] / x[-2] - 1) * 100, "r5": (x[-1] / x[-6] - 1) * 100,
                    "r20": (x[-1] / x[-21] - 1) * 100, "r60": (x[-1] / x[-61] - 1) * 100}
        time.sleep(1)

    out = os.path.join(a.work, "latest.json")
    json.dump({"metrics": M, "bench": bench, "unresolved": unresolved, "status": status},
              open(out, "w"), ensure_ascii=False)
    print(f"[fetch] 有效 {len(M)}/{len(codes)} → {out}")


if __name__ == "__main__":
    main()
