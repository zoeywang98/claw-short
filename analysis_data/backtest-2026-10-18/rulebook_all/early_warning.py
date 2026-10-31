#!/usr/bin/env python3
# ZZ 2026-10-30 "可做空rule是让你提前预警的": pre-break (close ≥ 2D) signals 7/22–10/26, closes extended to 10/29. Needs /private/tmp/bt_all/features.json (fetch_all.py + features.py rebuild it).
"""Early-warning test (ZZ 10/30 "可做空rule是让你提前预警的"): signals on names that have NOT broken yet (close ≥ 2D centroid),
outcome = what happens next. Features 7/22–10/26 (rulebook_all), closes extended to 10/29 from the 10/29 briefs."""
import json, math, statistics as st, collections
WS='/Users/yuwang/.openclaw/workspace-claw-short'
F=json.load(open('/private/tmp/bt_all/features.json'))
DAYS=list(F['days']); ROWS=F['rows']; WL=list(ROWS)
R={(T,r['date']):r for T in WL for r in ROWS[T]}
for T in WL:   # extend closes to 10/29
    for b in json.load(open(f'{WS}/analysis_data/2026-10-29/{T}.json'))['price']['last_22_bars']:
        if b[0]>DAYS[-1] or (T,b[0]) not in R:
            R.setdefault((T,b[0]),{'date':b[0],'close':b[4],'high':b[2],'low':b[3],'ext':True})
DAYS=sorted(set(DAYS)|{d for (_,d) in R}); IDX={d:i for i,d in enumerate(DAYS)}
LASTF=F['days'][-1]
def row(T,d,k=0):
    i=IDX.get(d)
    if i is None or not 0<=i+k<len(DAYS): return None
    return R.get((T,DAYS[i+k]))
def cl(T,d,k=0): r=row(T,d,k); return r and r.get('close')
def ret(T,d,k):
    a,b=cl(T,d,-k),cl(T,d); return b/a-1 if a and b else None
def fwd(T,d,k):
    a,b=cl(T,d),cl(T,d,k); return b/a-1 if a and b else None
AVG={}
for d in DAYS:
    for k in (1,3,5):
        v=[x for x in (fwd(T,d,k) for T in WL) if x is not None]
        AVG[(d,k)]=st.mean(v) if len(v)>=15 else None
def chg(T,d,key,k):
    a,b=row(T,d,-k),row(T,d)
    return b[key]-a[key] if a and b and a.get(key) is not None and b.get(key) is not None else None
def brk(T,d,n):   # closes below its own 2D centroid within the next n sessions (needs features)
    for j in range(1,n+1):
        r=row(T,d,j)
        if not r or r.get('ext') or r.get('c2D') is None: return None
        if r['close']<r['c2D']: return True
    return False
def dd(T,d,n,x):  # some close within n sessions ≤ -x from today
    c=cl(T,d); out=False
    for j in range(1,n+1):
        b=cl(T,d,j)
        if b is None: return None
        if b/c-1<=-x: out=True
    return out
def U(T,d,r): return r.get('c2D') is not None and r['close']>=r['c2D']
def hi5(T,d): return max((row(T,d,-j) or {}).get('high') or 0 for j in range(0,5))
S={
 '急涨 5日≥15%': lambda T,d,r: (ret(T,d,5) or 0)>=0.15,
 '急涨 5日≥10%': lambda T,d,r: (ret(T,d,5) or 0)>=0.10,
 '高于1W重心≥8%': lambda T,d,r: r.get('c1W') and r['close']>=r['c1W']*1.08,
 '高于1M重心≥15%': lambda T,d,r: r.get('c1M') and r['close']>=r['c1M']*1.15,
 '2D重心<1W重心(价在上)': lambda T,d,r: r.get('c1W') and r['c2D']<r['c1W'],
 '重心阶梯下移1M>1W>2D': lambda T,d,r: r.get('c1W') and r.get('c1M') and r['c1M']>r['c1W']>r['c2D'],
 '收盘<1D重心(还在2D上)': lambda T,d,r: r.get('c1D') and r['close']<r['c1D'],
 '离2D只差≤1%': lambda T,d,r: r['close']<=r['c2D']*1.01,
 '冲高回落 距5日高≥3%': lambda T,d,r: r['close']<=hi5(T,d)*0.97,
 'put净买入': lambda T,d,r: (r.get('net_put_premium') or 0)>0,
 'flow偏空(put ask>bid, call bid>ask)': lambda T,d,r: r.get('put_volume_ask_side',0)>r.get('put_volume_bid_side',0) and r.get('call_volume_bid_side',0)>r.get('call_volume_ask_side',0),
 '负gamma(还在2D上)': lambda T,d,r: r.get('net_gamma') is not None and r['net_gamma']<0,
 '拥挤 SI≥10%或SVR≥55%': lambda T,d,r: (r.get('si_float') or 0)>=0.10 or (r.get('svr') or 0)>=0.55,
 '暗池放量1.5x+5日涨': lambda T,d,r: r.get('dark1D') and r.get('dark_avg1M') and r['dark1D']>=1.5*r['dark_avg1M'] and (ret(T,d,5) or 0)>0,
 'call&put OI齐增+高于DP2%': lambda T,d,r: (chg(T,d,'call_open_interest',1) or 0)>0 and (chg(T,d,'put_open_interest',1) or 0)>0 and r.get('c1W') and r['close']>=1.02*max(r['c2D'],r['c1W']),
 '贴近gamma flip上方2%内': lambda T,d,r: r.get('flip') and 0<=r['close']/r['flip']-1<=0.02,
 'IV升+5日涨≥5%': lambda T,d,r: (chg(T,d,'iv30',5) or 0)>0 and (ret(T,d,5) or 0)>=0.05,
 'IV>RV且IV rank≥50': lambda T,d,r: r.get('iv30') and r.get('rv21') and r['iv30']>r['rv21'] and (r.get('iv_rank') or 0)>=0.5,
 '贴近call wall下方2%内': lambda T,d,r: r.get('call_wall') and 0<=1-r['close']/r['call_wall']<=0.02,
 '财报在3个交易日内': lambda T,d,r: r.get('next_earn') and d<r['next_earn']<=(DAYS[min(IDX[d]+3,len(DAYS)-1)]),
}
def ev(fn,lo,hi):
    out=[]
    for T in WL:
        for d in F['days']:
            if d<lo or d>hi: continue
            r=R.get((T,d))
            if not r or not U(T,d,r): continue
            try:
                if fn(T,d,r): out.append((T,d))
            except (TypeError,ZeroDivisionError,KeyError): pass
    return out
def stat(E):
    o={}
    for k in (3,5):
        v=[(d,fwd(T,d,k),fwd(T,d,k)-AVG[(d,k)]) for T,d in E if fwd(T,d,k) is not None and AVG.get((d,k)) is not None]
        if not v: o[k]=None; continue
        byd=collections.defaultdict(list)
        for d,f,x in v: byd[d].append(x)
        dm=[st.mean(y) for y in byd.values()]
        t=-(st.mean(dm)/(st.pstdev(dm)/math.sqrt(len(dm)))) if len(dm)>2 and st.pstdev(dm)>0 else float('nan')
        o[k]=dict(n=len(v),nd=len(byd),fell=sum(f<0 for _,f,_ in v)/len(v),lag=sum(x<0 for *_,x in v)/len(v),avg=st.mean(f for _,f,_ in v),t=t)
    b=[brk(T,d,3) for T,d in E]; b=[x for x in b if x is not None]
    o['brk3']=(sum(b)/len(b),len(b)) if b else None
    z=[dd(T,d,5,0.05) for T,d in E]; z=[x for x in z if x is not None]
    o['dd5']=(sum(z)/len(z),len(z)) if z else None
    return o
def fmt(o):
    s=''
    for k in (3,5):
        x=o[k]; s+=f" {k}D " + ('-' if not x else f"跌{x['fell']*100:3.0f}% 输{x['lag']*100:3.0f}% n{x['n']:4d} t{x['t']:+.1f}")
    b3='-' if not o['brk3'] else '%3.0f%%' % (o['brk3'][0]*100)
    d5='-' if not o['dd5'] else '%3.0f%%' % (o['dd5'][0]*100)
    s+=f" | 3天内跌破2D {b3} | 5天内跌≥5% {d5}"
    return s
P=(('7/22-9/24','2026-07-22','2026-09-24'),('9/25-10/26','2026-09-25','2026-10-26'))
print('baseline = not broken yet (close ≥ 2D)')
for lab,lo,hi in P: print(f"  {lab:11s}"+fmt(stat(ev(lambda T,d,r: True,lo,hi))))
for name,fn in S.items():
    print(name)
    for lab,lo,hi in P: print(f"  {lab:11s}"+fmt(stat(ev(fn,lo,hi))))

print('\n== composites and robustness')
run=lambda T,d,r: (ret(T,d,5) or 0)>=0.10 or (r.get('c1W') and r['close']>=r['c1W']*1.08)
crowd=lambda T,d,r: (r.get('si_float') or 0)>=0.10 or (r.get('svr') or 0)>=0.55
for name,fn in (('急涨≥10% 或 高于1W≥8%',run),('上面 且 拥挤',lambda T,d,r: run(T,d,r) and crowd(T,d,r)),('上面 且 不拥挤',lambda T,d,r: run(T,d,r) and not crowd(T,d,r))):
    print(name)
    for lab,lo,hi in P: print(f"  {lab:11s}"+fmt(stat(ev(fn,lo,hi))))
E=ev(run,'2026-07-22','2026-10-26')
print('fires on', len(E), 'of', len(ev(lambda T,d,r: True,'2026-07-22','2026-10-26')), 'not-broken name-days; tickers', collections.Counter(T for T,_ in E).most_common(12))
for T in sorted({T for T,_ in E}):
    o=stat([x for x in E if x[0]!=T])
    print(f"  drop {T:5s}: 5D 跌 {o[5]['fell']*100:3.0f}% 输 {o[5]['lag']*100:3.0f}% n{o[5]['n']}")
# recall: next-day drop ≥5% / 3-day drop ≥8% — was the name flagged the day before?
print('\n== recall (all names, not only not-broken)')
for lab,lo,hi in P:
    for k,th in ((1,-0.05),(3,-0.08)):
        rows=[(T,d) for T in WL for d in F['days'] if lo<=d<=hi and R.get((T,d)) and fwd(T,d,k) is not None]
        big=[(T,d) for T,d in rows if fwd(T,d,k)<=th]
        sig=lambda T,d: (lambda r: r.get('c2D') is not None and r['close']>=r['c2D'] and bool(run(T,d,r)))(R[(T,d)])
        v3=lambda T,d: (lambda r: r.get('c2D') is not None and r['close']<r['c2D'])(R[(T,d)])
        ns=sum(sig(T,d) for T,d in rows); nb=len(big)
        print(f"  {lab} {k}D≤{th*100:.0f}%: 大跌 {nb}/{len(rows)} ({nb/len(rows)*100:.0f}%) | 预警(急涨/远离1W, 还没破) 前一天亮了 {sum(sig(T,d) for T,d in big)}/{nb}; 亮了之后大跌 {sum(1 for T,d in big if sig(T,d))}/{ns} = {sum(1 for T,d in big if sig(T,d))/max(1,ns)*100:.0f}% | 已跌破2D 亮了 {sum(v3(T,d) for T,d in big)}/{nb}, 之后大跌 {sum(1 for T,d in big if v3(T,d))/max(1,sum(v3(T,d) for T,d in rows))*100:.0f}%")
print('\n== flagged on the last feature day and on 10/27–10/29 (closes only: run-up part)')
for d in [x for x in DAYS if x>='2026-10-20']:
    names=[]
    for T in WL:
        r=R.get((T,d))
        if not r: continue
        r5=ret(T,d,5)
        if r5 is not None and r5>=0.10: names.append(f"{T}({r5*100:+.0f}%)")
    print(' ',d,' '.join(names))
