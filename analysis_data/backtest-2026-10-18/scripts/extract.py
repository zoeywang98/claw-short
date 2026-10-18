#!/usr/bin/env python3
"""Pull the triggered rules out of every post-close scan reply (logs/YYYY-MM-DD/<T>.reply.json) into JSON."""
import json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
LOGS = '/Users/yuwang/.openclaw/workspace-claw-short/daily_short/logs'
SANDBOX = '/Users/yuwang/.openclaw/workspace-claw-short/daily_short/sandbox'
OUT = '/tmp/bt/extracted.json'
prices = json.load(open('/tmp/bt/prices.json'))
SYSTEM = """你从做空分析报告里抽取"触发了哪些规则"，只照报告原文填，不自己判断。每份报告输出一个 JSON 对象，全部放进一个 JSON 数组，按输入顺序，只输出这个数组，不要别的文字、不要代码块。

字段（取值只能用列出的说法；报告没写的填 null）：
{"id": 输入给的 id,
 "tier": 结论行的档位，取 "✅低"|"✅中"|"✅高"|"👀"|"⚪"|"🧨"|"⛔",
 "squeeze": ① 的结论是不是 🧨（true/false）,
 "sq_c1": ① 第 1 条（SI≥10% 或 SVR 连日≥55%[+借券]）是否成立, "sq_c2": 第 2 条（DTC）是否成立, "sq_c3": 第 3 条（|spot−flip|≤3%）是否成立,
 "phase_late": 相位闸是否判了"偏晚/降级",
 "breaker": ② 是否熔断（true/false）,
 "volume": ③ 的结论 "足够"|"薄"|"未明确",
 "direction": ④ 的方向读数 "吸筹确认"|"派发确认"|"Trap warning"|"confirmed trap"|"不明"；🧨/⛔ 下只列事实时，如果报告写了形态指向（如"形态上指向派发确认"），填这个形态，否则填 "不明",
 "direction_adopted": ④ 的读数是否被采用进结论（🧨/⛔ 下只列事实、或说"不作空头读数"→ false）,
 "centroid_order": 1M→1W→2D 重心的顺序 "逐级下移"|"逐级上移"|"先升后降"|"先降后升"|"横移"|null,
 "fingerprint": ⑤ 报告选定或倾向的指纹 "派发"|"吸货"|"库存转移"|"Gamma hedge"|"对冲"|"Fund rebalance"|"无",
 "fingerprint_status": "已验证"|"假设"|"未定",
 "ivrv": ⑤ 里 IV×RV regime 的读数 "RV>IV空头行情"|"顶部机制"|"bounce相位"|"IV>RV高位回归"|"IV>RV两线相交"|"RV>IV低位多头"|"无命中"|null,
 "dealer_case": ⑥ 决策表命中 "Wall↑+Ask+OI↑"|"Wall↑+Bid+OI↑"|"Wall↓+Bid+OI↓"|"Wall↓+Ask+OI↓"|"无命中",
 "dealer_stock": ⑥ 推出的 dealer 对股票 "买"|"卖"|"未明确",
 "flow": flow 意图净额的结论 "偏空"|"偏多"|"conflict"|"中性"|null,
 "backlash": 是否标了"挤压反噬风险"（true/false）,
 "sector_veto": 是否因板块普涨/轧空相位 veto（true/false）,
 "thin": 是否 THIN 链（true/false/null）,
 "earnings_7d": 是否 7 天内有财报（true/false/null）}"""


def items():
    out = []
    for d in sorted(os.listdir(LOGS)):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) or not ('2026-09-25' <= d <= '2026-10-16'):
            continue
        for f in sorted(os.listdir(os.path.join(LOGS, d))):
            if not f.endswith('.reply.json') or f.startswith('_'):
                continue
            T = f[:-len('.reply.json')]
            if T not in prices:
                continue
            try:
                r = json.load(open(os.path.join(LOGS, d, f)))
            except ValueError:
                continue
            if r.get('is_error') or not r.get('result'):
                continue
            out.append({'id': f'{d}|{T}', 'text': re.sub(r'\*\*运行日志\*\*[\s\S]*$', '', r['result'])})
    return out


def run(batch):
    user = '\n\n'.join(f'=== id: {it["id"]} ===\n{it["text"]}' for it in batch)
    cmd = ['claude', '-p', '--model', 'claude-sonnet-5-5', '--effort', 'medium', '--system-prompt', SYSTEM,
           '--tools', '', '--strict-mcp-config', '--setting-sources', '', '--no-session-persistence', '--output-format', 'json']
    for attempt in range(3):
        p = subprocess.run(cmd, input=user, capture_output=True, text=True, cwd=SANDBOX, timeout=900)
        try:
            r = json.loads(p.stdout)
            txt = r.get('result') or ''
            txt = txt[txt.find('['): txt.rfind(']') + 1]
            arr = json.loads(txt)
            if len(arr) == len(batch):
                return arr, r.get('total_cost_usd') or 0
        except Exception as e:
            err = str(e)
    return [{'id': it['id'], 'error': 'extract failed'} for it in batch], 0


if __name__ == '__main__':
    its = items()
    print('replies', len(its), file=sys.stderr)
    batches = [its[i:i + 6] for i in range(0, len(its), 6)]
    lo, hi = int(sys.argv[1]), int(sys.argv[2])
    batches = batches[lo:hi]
    OUT = OUT.replace('.json', f'_{lo}_{hi}.json')
    res, cost = [], 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        for arr, c in ex.map(run, batches):
            res += arr
            cost += c
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=0)
    print('done', len(res), 'errors', sum(1 for x in res if x.get('error')), 'cost', round(cost, 2), file=sys.stderr)
