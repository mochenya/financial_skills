# /// script
# requires-python = ">=3.10,<3.15"
# dependencies = ["eltdx==3.3.2", "psycopg[binary]==3.2.13", "yfinance==1.7.0"]
# ///
import argparse, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import psycopg
from psycopg.rows import dict_row

FIELDS = 'market, code, name, alias, concepts, note, is_followed, created_at, updated_at'
def identity(market, code):
    patterns = {'sh': r'[0-9]{6}', 'sz': r'[0-9]{6}', 'bj': r'[0-9]{6}',
                'hk': r'[0-9]{5}', 'us': r'[A-Z0-9]+(?:-[A-Z0-9]+)*',
                'jp': r'[A-Z0-9]{4}\.T', 'kr': r'[0-9]{6}\.(?:KS|KQ)'}
    if market not in patterns or not re.fullmatch(patterns[market], code):
        raise ValueError('invalid market or code format')

def yahoo(code):
    import yfinance as yf
    d = yf.Ticker(code).info
    if d.get('symbol') != code or d.get('quoteType') != 'EQUITY':
        raise ValueError('Yahoo identity or security type not confirmed')
    name = d.get('longName') or d.get('shortName')
    if not isinstance(name, str) or not name.strip(): raise ValueError('Yahoo name missing')
    industry = d.get('industry')
    return name, [industry] if isinstance(industry, str) and industry.strip() else None

def hk_symbol(code):
    identity('hk', code)
    return code.lstrip('0').zfill(4) + '.HK'

def fetch_us(codes):
    from yfinance.exceptions import YFRateLimitError
    out, pending = {}, {}
    iterator = iter(dict.fromkeys(codes))
    stopped = False
    with ThreadPoolExecutor(max_workers=8) as executor:
        def fill():
            while len(pending) < 8:
                code = next(iterator, None)
                if code is None: break
                pending[executor.submit(yahoo, code)] = code
        fill()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                code = pending.pop(future)
                try: out[code] = future.result()
                except YFRateLimitError:
                    out[code] = ValueError('Yahoo rate limited'); stopped = True
                except Exception:
                    out[code] = ValueError('Yahoo lookup failed or identity not confirmed')
            if not stopped: fill()
    return out

def a_share_topics(market, code):
    from eltdx.mac import MacClient
    from eltdx.mac.enums import BoardType
    with MacClient(timeout=5) as client:
        categories = []
        for kind in (BoardType.HY, BoardType.HY2, BoardType.GN):
            rows = client.get_board_list(kind)
            if not rows: raise RuntimeError('empty classified board list')
            categories.append({(r.market, r.code) for r in rows})
        rows = client.get_belong_board({'sz':0, 'sh':1, 'bj':2}[market], code)
        if not rows: raise RuntimeError('empty stock board list')
        names = []
        for group in categories[:2]:
            for row in rows:
                if (row.market, row.board_code) in group and row.board_name and row.board_name not in names:
                    names.append(row.board_name)
        if not names:
            for row in rows:
                if (row.market, row.board_code) in categories[2] and row.board_name:
                    names.append(row.board_name)
                    break
        if not names: raise RuntimeError('no classified industry or concept found')
        return names

def name_for(market, code, cache):
    if market not in cache:
        if market == 'hk':
            from eltdx.ex import MacExClient
            with MacExClient(timeout=5) as c:
                rows, start = [], 0
                while True:
                    page = c.instruments(31, start=start, count=600)
                    rows.extend(page)
                    if len(page) < 600: break
                    start += len(page)
        else:
            from eltdx import TdxClient
            with TdxClient(timeout=5) as c: rows = c.codes.a_shares(market)
        if not rows: raise RuntimeError('upstream returned an empty securities list')
        cache[market] = {r.code: r.name for r in rows}
    if code not in cache[market]: raise ValueError('code not found in upstream list')
    return cache[market][code]
def create(conn, item, cache):
    if not isinstance(item, dict) or set(item)-{'market','code','alias','concepts','note'}: raise ValueError('invalid import fields')
    m, c = item.get('market'), item.get('code')
    if not isinstance(m,str) or not isinstance(c,str): raise ValueError('market and code must be strings')
    identity(m,c)
    if m in ('us','hk','jp','kr') and item.get('concepts') is not None: raise ValueError('industry is maintained by Yahoo')
    for k in ('alias','note'):
        if item.get(k) is not None and not isinstance(item[k],str): raise ValueError(k+' must be a string or null')
    if item.get('concepts') is not None and (not isinstance(item['concepts'],list) or any(not isinstance(x,str) or not x.strip() for x in item['concepts'])): raise ValueError('concepts must be an array of nonempty strings or null')
    with conn.cursor() as cur:
        cur.execute('SELECT 1 FROM stock_pool.stocks WHERE market=%s AND code=%s',(m,c))
        if cur.fetchone(): return 'skipped', None
    if m in ('us','jp','kr'):
        result = cache.get((m,c))
        if result is None: raise ValueError('Yahoo lookup not completed')
        if isinstance(result, Exception): raise result
        name, industry = result
        item = dict(item, concepts=industry)
    else:
        name = name_for(m,c,cache)
        if m in ('sh','sz','bj') and item.get('concepts') is None:
            item = dict(item, concepts=a_share_topics(m,c))
        elif m == 'hk':
            _, industry = yahoo(hk_symbol(c))
            item = dict(item, concepts=industry)
    if not name or not name.strip(): raise ValueError('upstream name is empty')
    with conn.cursor() as cur:
        cur.execute('INSERT INTO stock_pool.stocks (market,code,name,alias,concepts,note) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING '+FIELDS,(m,c,name,item.get('alias'),item.get('concepts'),item.get('note')))
        row=cur.fetchone()
    return ('created',row) if row else ('skipped',None)
def parser():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
    def ident(q): q.add_argument('--market',required=True,choices=['sh','sz','bj','hk','us','jp','kr']); q.add_argument('--code',required=True)
    a=sub.add_parser('add'); ident(a); a.add_argument('--alias'); a.add_argument('--concept',action='append'); a.add_argument('--note')
    i=sub.add_parser('import'); i.add_argument('--file',required=True)
    l=sub.add_parser('list'); l.add_argument('--market',choices=['sh','sz','bj','hk','us','jp','kr']); l.add_argument('--code'); l.add_argument('--followed',choices=['true','false']); l.add_argument('--keyword')
    u=sub.add_parser('update'); ident(u)
    for x in ('alias','note','concepts'):
        g=u.add_mutually_exclusive_group(); g.add_argument('--concept' if x=='concepts' else '--'+x,action='append' if x=='concepts' else 'store'); g.add_argument('--clear-'+x,action='store_true')
    u.add_argument('--followed',choices=['true','false'])
    r=sub.add_parser('refresh-industry'); r.add_argument('--market', choices=['us','hk','sh','sz','bj','jp','kr'], default='us'); r.add_argument('--code')
    d=sub.add_parser('delete'); ident(d)
    return p
def run(args,conn):
    if args.cmd=='import':
        with open(args.file,encoding='utf-8') as f: items=json.load(f)
        if not isinstance(items,list): raise ValueError('import input must be an array')
        results=[]; cache={}
        candidates = []
        for market in ('us', 'jp', 'kr'):
            codes = []
            for item in items:
                if isinstance(item, dict) and item.get('market') == market and isinstance(item.get('code'), str):
                    try: identity(market, item['code']); codes.append(item['code'])
                    except ValueError: pass
            with conn.cursor() as cur:
                cur.execute("SELECT code FROM stock_pool.stocks WHERE market=%s AND code = ANY(%s)", (market, codes))
                existing = {row['code'] for row in cur.fetchall()}
            candidates.extend((market, c) for c in codes if c not in existing)
        fetched = fetch_us([c for _, c in candidates])
        cache.update({(m, c): fetched[c] for m, c in candidates if c in fetched})
        for item in items:
            try:
                with conn.transaction(): status,_=create(conn,item,cache)
                results.append({'market':item['market'],'code':item['code'],'status':status,**({'reason':'already_exists'} if status=='skipped' else {})})
            except Exception as e:
                results.append({'market':item.get('market') if isinstance(item,dict) else None,'code':item.get('code') if isinstance(item,dict) else None,'status':'failed','reason':str(e) if isinstance(e,ValueError) else 'upstream or database error'})
        counts={s:sum(x['status']==s for x in results) for s in ('created','skipped','failed')}
        return {'status':'partial' if counts['failed'] else 'ok','total':len(items),**counts,'results':results}, 1 if counts['failed'] else 0
    if args.cmd=='add':
        identity(args.market,args.code)
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM stock_pool.stocks WHERE market=%s AND code=%s',(args.market,args.code))
            if cur.fetchone(): return {'status':'skipped','reason':'already_exists'},0
        cache = {(args.market,args.code):v for v in [yahoo(args.code)]} if args.market in ('us','jp','kr') else {}
        with conn.transaction(): status,row=create(conn,{'market':args.market,'code':args.code,'alias':args.alias,'concepts':args.concept,'note':args.note},cache)
        return {'status':status,**({'stock':row} if row else {'reason':'already_exists'})},0
    if args.cmd=='list':
        clauses=[]; values=[]
        for col,val in [('market',args.market),('code',args.code),('is_followed',None if args.followed is None else args.followed=='true')]:
            if val is not None: clauses.append(col+'=%s');values.append(val)
        if args.keyword is not None:
            clauses.append("(code ILIKE %s OR name ILIKE %s OR alias ILIKE %s OR note ILIKE %s)");values.extend(['%'+args.keyword+'%']*4)
        with conn.cursor() as cur:
            cur.execute('SELECT '+FIELDS+' FROM stock_pool.stocks'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY market,code',values);rows=cur.fetchall()
        return {'count':len(rows),'stocks':rows},0
    if args.cmd=='refresh-industry':
        with conn.cursor() as cur:
            cur.execute('SELECT code FROM stock_pool.stocks WHERE market=%s'+(' AND code=%s' if args.code else '')+' ORDER BY code', (args.market,args.code) if args.code else (args.market,))
            codes=[r['code'] for r in cur.fetchall()]
        if args.market in ('us','jp','kr'): fetched=fetch_us(codes)
        elif args.market == 'hk':
            fetched={}
            from yfinance.exceptions import YFRateLimitError
            for code in codes:
                try: fetched[code]=yahoo(hk_symbol(code))
                except YFRateLimitError:
                    fetched[code]=ValueError('Yahoo rate limited'); break
                except Exception: fetched[code]=ValueError('Yahoo lookup failed')
        else:
            fetched={}
            for code in codes:
                try: fetched[code]=(None,a_share_topics(args.market,code))
                except Exception: fetched[code]=ValueError('upstream lookup failed')
        results=[]
        for code in codes:
            result=fetched.get(code)
            if result is None or isinstance(result,Exception) or result[1] is None:
                results.append({'code':code,'status':'failed','reason':'lookup failed, stopped, or industry missing'}); continue
            with conn.transaction(), conn.cursor() as cur:
                cur.execute('UPDATE stock_pool.stocks SET concepts=%s, updated_at=now() WHERE market=%s AND code=%s AND concepts IS DISTINCT FROM %s RETURNING code',(result[1],args.market,code,result[1]))
                results.append({'code':code,'status':'updated' if cur.fetchone() else 'unchanged'})
        return {'results':results}, 1 if any(r['status']=='failed' for r in results) else 0
    identity(args.market,args.code)
    with conn.transaction(), conn.cursor() as cur:
        if args.cmd=='delete':
            cur.execute('DELETE FROM stock_pool.stocks WHERE market=%s AND code=%s RETURNING market,code',(args.market,args.code)); row=cur.fetchone()
            if not row: raise ValueError('stock not found')
            return {'status':'deleted',**row},0
        if args.market in ('us','hk','jp','kr') and (args.concept is not None or args.clear_concepts): raise ValueError('industry is maintained by Yahoo; use refresh-industry')
        changes={}
        for field in ('alias','note','concepts'):
            value=getattr(args,'concept' if field=='concepts' else field)
            if getattr(args,'clear_'+field): changes[field]=None
            elif value is not None:
                if field=='concepts' and any(not x.strip() for x in value): raise ValueError('concept cannot be blank')
                changes[field]=value
        if args.followed is not None: changes['is_followed']=args.followed=='true'
        if not changes: raise ValueError('no changes specified')
        cur.execute('SELECT '+FIELDS+' FROM stock_pool.stocks WHERE market=%s AND code=%s FOR UPDATE',(args.market,args.code));row=cur.fetchone()
        if not row: raise ValueError('stock not found')
        changed={k:v for k,v in changes.items() if row[k]!=v}
        if changed:
            cur.execute('UPDATE stock_pool.stocks SET '+', '.join(k+'=%s' for k in changed)+', updated_at=now() WHERE market=%s AND code=%s RETURNING '+FIELDS,(*changed.values(),args.market,args.code)); row=cur.fetchone()
        return {'status':'updated' if changed else 'unchanged','stock':row},0

def main():
    args=parser().parse_args()
    try:
        url=os.environ.get('STOCK_POOL_DATABASE_URL')
        if not url: raise ValueError('STOCK_POOL_DATABASE_URL is not set')
        with psycopg.connect(url,autocommit=True,row_factory=dict_row) as conn: result,code=run(args,conn)
        print(json.dumps(result,ensure_ascii=False,default=str));return code
    except Exception as e:
        print(json.dumps({'error':str(e) if isinstance(e,(ValueError,FileNotFoundError,json.JSONDecodeError)) else 'operation failed; check database and upstream availability'},ensure_ascii=False),file=sys.stderr);return 1
if __name__=='__main__': sys.exit(main())
