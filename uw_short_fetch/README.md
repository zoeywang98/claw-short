# uw_short_fetch

按 [SHORT_ENGINE.md](https://github.com/zoeywang98/fable5-short-learnings/blob/claude/awesome-gauss-7amf0x/SHORT_ENGINE.md) 从 Unusual Whales API 拉取做空分析需要的全部数据。
这个工具只负责拉数据、整理数据、输出逐层运行日志（§8），不做交易判断：挤仓否决、熔断、重心迁移、动机指纹、决策表这些判定留到第二步。

只用 Python 标准库（3.9+），不需要安装任何包。

## 用法

```bash
cd uw_short_fetch
python3 fetch.py --tickers NBIS,AXTI                  # 默认取最近一个交易日
python3 fetch.py --tickers NBIS --date 2026-09-24     # 历史日期（只提供实时数据的端点会记 FAIL）
python3 fetch.py --tickers NBIS,AXTI --date 2026-09-24 --asof 09:35   # 时间点快照：只用截至 9:35 ET 已经能拿到的数据
python3 fetch.py --tickers-file list.txt --universe-file breaker35.txt
python3 -m unittest discover -s tests                # 离线测试，不调用 API
```

API token 先读环境变量 `UW_API_TOKEN`，没有的话再读 `~/.openclaw/.env`。token 不会写进日志、raw 文件或缓存。

退出码：0 表示每个票的核心层都是 8/8；1 表示有核心层 FAIL；2 表示参数错误。

## 时间点模式（`--asof HH:MM`）

输出目录是 `data/<D>_<HHMM>/`。每一层只保留截止时刻已经能拿到的数据，规则如下：

- **带时间戳的数据，只保留截止前的部分**：暗池和场内大单、现价（最后一笔暗池成交的 NBBO 中点）、当日累计成交量、multi-leg、net-prem-ticks、flow-alerts、spot-gex、short-data（借券）、5 分钟 K 线
- **开盘前就已经算好的数据，用 D 当天的**：oi-change、oi-per-strike、greek-exposure（包括 /strike），以及熔断池的 net gamma。熔断池的成员按 K（前一交易日）的市值选
- **收盘后才出的数据，用 K（前一交易日）的**：darkpool-levels、gex-levels、short-volume、options-volume、interpolated-iv、option-sentiment、rr-skew、offlit-levels、screener、相关性、ETF 申赎、合约历史、日线
- **做不到时间点的，记 FAIL**：
  - option-trades：历史日期拿不到
  - option-contracts 和 unusualness：只提供实时数据
  - options-pulse：按 10 分钟分段，第一段 9:40 才结束
- flow-per-strike 里 D 当天截止前的部分单独放在 `d_partial` 下。UW 的逐分钟接口只覆盖当天成交最多的几个 strike，是子集；完整的逐分钟合计看 net-prem-ticks

## 输出

```
data/<D>/run_log.txt          逐层 ✅ RAN / ❌ FAIL + as-of + 行数，核心覆盖率 N/8，补充数据覆盖率，UW 当日用量
data/<D>/run_summary.json     同上，机器可读
data/<D>/universe_gamma.json  熔断输入：池子里每个名字的 net gamma，以及负 gamma 的个数
data/<D>/market.json          日历标记、候选之间的相关性、板块 SPDR ETF 的申赎流
data/<D>/<T>/snapshot.json    整理后的各层数据（每层带 as_of）+ derived（现价、大单参与度、墙的交叉核对）
data/<D>/<T>/raw/*.json       每次请求的原始响应，附 URL、状态码、抓取时间、UW 用量响应头
cache/<T>/*.json              历史日期的响应，再跑时直接复用。文件名按完整请求（路径 + 参数）哈希生成，不同日期不会混用
```

## 核心 8 层

| 层 | 端点 | 说明 |
|---|---|---|
| darkpool-levels | `/api/darkpool/{t}/price-levels?date=` | 22 个交易日逐日拉取；每档 DP% = dark/(dark+regular)；给出 1D/1W/1M 三个窗口的累计值，以及 D、D-5、D-21 三个单日快照；top8 按 dark 量排序，重心按 dark 量加权 |
| darkpool | `/api/darkpool/{t}` | 大单定义为 ≥1 万股或 ≥$20 万，剔除竞价成交；现价取 DP NBBO 中点（盘后的话另外记录最后一笔 RTH 中点） |
| option-trades | `/api/option-trades?ticker_symbol=` | 只提供最近一个交易日；只拉 premium ≥ $5 万的成交；按 ask/bid 净额汇总；strike 用 OCC 代码解析的值 |
| gex-levels | `/api/stock/{t}/gex-levels` | 6 个交易日 × vol/oi 两种口径；记录墙的日间变化 |
| greek-exposure | `/api/stock/{t}/greek-exposure` | 取 date == D 那一行，net = call + put |
| short-interest | `/api/shorts/{t}/interest-float/v2` | 记录滞后天数 |
| short-volume | `/api/shorts/{t}/volume-and-ratio` | 数据在 `si` 键下 |
| short-data | `/api/shorts/{t}/data` | 取最新时间戳，另附每日序列 |

## 补充数据

lit-blocks、ohlc-daily、ohlc-5m、oi-change、option-contracts（仅实时）、oi-per-strike、options-volume、interpolated-iv、option-sentiment（AVAR，作为上行尾部的替代指标）、unusualness（活跃度，仅实时）、options-pulse（开仓买入笔数）、multi-leg（领口 / roll 的形状）、flow-per-strike 和 net-prem-ticks（历史 flow）、flow-alerts（UW 按规则触发的期权告警，可以查历史，也可以截到分钟）、spot-gex（逐分钟的 spot gamma/charm/vanna）、greek-exposure-strike、offlit-levels（DP 的第二视角）、contract-history（关键合约的 OI 历史）、rr-skew（25Δ）、screener。

数据源本身的限制：UW 的暗池和场内逐笔接口只收 premium ≥ $10 万的成交，是大单子集，不是完整的逐笔成交。所以逐价位的 DP% 只能用 price-levels（全天汇总）来算。
市场层面的数据：交易日历（SPY）、熔断池（screener 一次拉完）、相关性、板块 ETF 申赎。

## 默认参数（都可以调）

`--block-shares 10000 --block-premium 200000 --flow-min-premium 50000 --multileg-min-size 50 --dp-days 22 --gex-days 6 --flow-days 5 --universe-size 35 --concurrency 4`

熔断池：传了 `--universe-file` 就用文件里的名单；不传的话，取每个候选所在板块市值前 35 的名字。

## 已经处理的数据坑

- greek-exposure、SI、short-volume、short-data 都按日期取 max(date) ≤ D 的那一行，不按位置取第一行或最后一行
- ohlc/1d 实际返回是新的在前（spec 写的是旧的在前），而且每天 3 行（pr/r/po），只保留 r
- darkpool price-levels 的数字字段是字符串；档位网格是每美元 X.00 和 X.75 两档，每天一致
- darkpool 和 lit-flow 一旦带上 `older_than`，就会忽略 `date` 参数，所以翻页时按纽约日期过滤，跨到前一天就停
- flow-per-strike 直接返回数组；option-contract historic 的数据在 `chains` 键下；gex-levels 的 `data` 是字典
- option-contracts 单次最多 500 行，超过时按到期日拆开拉
- screener 的 `short_int` 返回 0，跟 interest-float/v2 对不上，所以不用
- short_screener 的 `tickers` 过滤不生效，不用
- 期权 flow 的 strike 会跟 OCC 代码对一遍（SHORT_ENGINE §7.1），画墙只用 gex-levels
- 场内的开盘/收盘竞价（nasdaq_official_*、cross_trade、opening/closing_print）不算大单，单独列在 `auction` 下
