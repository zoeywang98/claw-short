# uw_short_fetch

按 [SHORT_ENGINE.md](https://github.com/zoeywang98/fable5-short-learnings/blob/claude/awesome-gauss-7amf0x/SHORT_ENGINE.md) 从 Unusual Whales API 拉取做空分析需要的全部数据。
这个工具只负责拉数据、整理数据、输出逐层运行日志（§8），不做交易判断：挤仓否决、熔断、重心迁移、动机指纹、决策表这些判定留到第二步。

只用 Python 标准库（3.9+），不需要安装任何包。

## 用法

```bash
cd uw_short_fetch
python3 fetch.py                                      # 默认名单 24 个票，最近一个交易日
python3 fetch.py --group optics,ai_infra              # 只跑指定分组
python3 fetch.py --tickers NBIS,AXTI                  # 指定票（不用默认名单）
python3 fetch.py --tickers NBIS --date 2026-09-24     # 历史日期（只提供实时数据的端点会记 FAIL）
python3 fetch.py --tickers NBIS,AXTI --date 2026-09-24 --asof 09:35   # 时间点快照：只用截至 9:35 ET 已经能拿到的数据
python3 fetch.py --tickers-file list.txt
python3 -m unittest discover -s tests                # 离线测试，不调用 API
```

API token 先读环境变量 `UW_API_TOKEN`，没有的话再读 `~/.openclaw/.env`。token 不会写进日志、raw 文件或缓存。

退出码：0 表示每个票的核心层都是 8/8；1 表示有核心层 FAIL；2 表示参数错误。

## 默认名单（`uwsf/watchlist.py`）

- optics 光模块/光学：LITE COHR AAOI GLW AEHR
- ai_infra AI基建/电力：VRT NVT NBIS DELL FLEX AMD MU（AMD 2026-11-24 加，ZZ "amd加列表里"；MU 2026-11-25 加，ZZ "加上mu"）
- software 软件/企服：MSFT META IBM NOW DDOG MDB
- pharma 医药：MRK RVMD CRVS VKTX TEVA VTRS
- commodity_etf 商品ETF：SLV

每次运行都会按分组统计负 gamma 的名字数（取各票 greek-exposure 当天的 net gamma），写进 run_log 和 `group_gamma.json`。这只是数据，不做熔断判定。
熔断的"板"就是这份名单（SHORT_ENGINE §3，ZZ 2026-09-28），run_log 里有一行全名单合计。不再按板块拉市值前 35。

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
data/<D>/market.json          日历标记、候选之间的相关性、板块 SPDR ETF 的申赎流
data/<D>/<T>/snapshot.json    整理后的各层数据（每层带 as_of）+ derived（现价、大单参与度、墙的交叉核对）
data/<D>/<T>/raw/*.json       每次请求的原始响应，附 URL、状态码、抓取时间、UW 用量响应头
cache/<T>/*.json              历史日期的响应，再跑时直接复用。文件名按完整请求（路径 + 参数）哈希生成，不同日期不会混用
history/flow_iv/<T>.json      每个收完盘的交易日的 flow-IV（按 premium 加权的成交 IV），用来做日对日；盘中跑和时间点模式只读不写
```

## 核心 8 层

| 层 | 端点 | 说明 |
|---|---|---|
| darkpool-levels | `/api/darkpool/{t}/price-levels?date=` | 22 个交易日逐日拉取；每档 DP% = dark/(dark+regular)；给出 1D/3D/1W/1M 四个窗口的累计值，以及 D、D-5、D-21 三个单日快照；top8 按 dark 量排序，重心按 dark 量加权 |
| darkpool | `/api/darkpool/{t}` | 大单定义为 ≥1 万股或 ≥$20 万，剔除竞价成交；现价取 DP NBBO 中点（盘后的话另外记录最后一笔 RTH 中点） |
| option-trades | `/api/option-trades?ticker_symbol=` | 只提供最近一个交易日；只拉 premium ≥ $5 万的成交；按 ask/bid 净额汇总；strike 用 OCC 代码解析的值 |
| gex-levels | `/api/stock/{t}/gex-levels` | 6 个交易日 × vol/oi 两种口径；记录墙的日间变化 |
| greek-exposure | `/api/stock/{t}/greek-exposure` | 取 date == D 那一行，net = call + put |
| short-interest | `/api/shorts/{t}/interest-float/v2` | 记录滞后天数 |
| short-volume | `/api/shorts/{t}/volume-and-ratio` | 数据在 `si` 键下 |
| short-data | `/api/shorts/{t}/data` | 取最新时间戳，另附每日序列 |

### 暗池价位的第二来源：DICloak 里的 UW 网站（ZZ 2026-11-22）

ZZ："同时 fetch darkpool centroid from dicloak and uw api，比较是否一致，如果一致，优先返回 dicloak 的数据"；同一天又问"2D / 1W / 1M 的也可以用网页吗"。

- 网站上有两个接口：
  - large-trades 页的 Price Group：`https://phx.unusualwhales.com/api/flow/levels/{t}/volume-price-group`，只有最近一个交易日（带 date 也没用）。`stock_price_vol` 和 API 的 price-levels 是同一套格子、同一个数（2026-11-20 比了 10 只，逐档相同）
  - 个股 Dark Pool 页（`/stock/{t}/darkpool`）：`/api/flow/dark/price_levels/{t}?day_range=N`，最近 N+1 个交易日的合计：0 = 1D，1 = 2D，2 = 3D，4 = 1W，20 = 1M。和 API 每天的表加起来逐档相同（2026-11-22 比了 6 只）。永远截到最近一个交易日，指定日期无效
- 所以只有截到网站最近一天的窗口能取两份。取到窗口最后一天 D 时，网站的 5 个请求（1D 用 Price Group，2D / 3D / 1W / 1M 用 Dark Pool 页）由 DICloak 里登录着的 unusualwhales.com 标签页一起发出（`uwsf/uwweb.py`，走 `workspace-claw-general/dicloak_common/dicloak_browser.py`，凭据不出浏览器，页面显示不变），紧接着发 API 那份 D。网站的 1D 和 API 的 D 比，其余窗口和 API 每天的表在同样几天上的合计比，逐档比暗池量和 lit 量。哪个窗口完全相同，那个窗口就用网站那份；不同就用 API 那份。D 还是当天的话（17:00 扫描、盘中重跑、盘中图），盘后成交还在进来，最多成对重取 3 次，间隔 2 秒
- D 以前的每一天，用本地存下来的网站数（ZZ 2026-11-22："这个你只要每天跑，保存在本地，就可以了吧，不用依赖api"）：
  - 网站的窗口两两相减就是单日：day_range k 减 day_range k-1 = 往前第 k 个交易日（整数，精确）。`site_capture.py` 一次取 day_range 0..K，拆成 K+1 个单日，存进 `history/dp_levels_site/<T>.json`（`uwsf/sitestore.py`）。只在网站最新一天的盘后交易结束（20:00 ET）以后取，这样每个请求看到的是同一份成交；差值有负数的那天不存
  - 每个工作日 20:30 ET 跑一次（`daily_short/site_capture.sh`，定时任务"claw-short 暗池网站存档"，`--backfill 5` 重存最近 6 天，漏一晚会自己补上）。2026-11-22 回填了 25 只（名单 23 只 + dpzone 的 GOOGL、V）10/22–11/20 共 22 个交易日，550 天全部和 API 逐档相同
  - 存的每一天在存的时候和 API 那天的表比一次，取数（darkpool-levels 层）时再比一次：相同就用存的网站数（`per_day[d].source = dicloak`），不同就用 API 的并 @ZZ。run_log 那一行末尾的 `site_days=21/21` 是 D 以前用了网站数的天数。所以"前一天的 2D 重心"（`close_vs_2D.prev_session`）和 1M / 1W 里更早的天现在也是网站的数；`--asof` 时间点模式同样用存的数（窗口截到前一天，正好都存过）
  - 窗口的 `source`：用了网站自己的窗口表，或者窗口里每一天都是网站数，记 dicloak；否则记 api
- 网站那几份存在 `raw/darkpool_levels_dicloak_<D>.json`。用了哪份记在 snapshot 的 `darkpool-levels.data.source_check`、`windows[w].source` 和 `per_day[D].source`。run_log 那一行末尾是 `src=<D>:dicloak(=api:1D/2D/3D/1W/1M)`（全部一致），或者 `src=<D>:dicloak(...)+api(...)`、`src=<D>:api`，后两种另起 note 说原因：DICloak 不可用、网站最新一天不是 D，或者两份不一致（几档不同、暗池量差多少、两边重心）。brief 不带这些字段，给模型的输入不变
- 不一致时（两边都有数，成对重取后还是不同）在 #claw-short @ZZ（ZZ 2026-11-22："如果有不一致的，@我提醒"，`uwsf/dpalert.py`）。每次取数最多发一条，列出每只票哪个窗口、几档不同、暗池量差多少、两边重心、像不像时间差。同一只票同一天盘中、盘后各最多提醒一次，记在 `.dp_source_alerts.json`。DICloak 不可用、网站最新一天不是 D 这两种不提醒，只记在 run_log。`--no-alert` 关掉提醒；发帖失败只记在 run_log 开头的 note 里，不影响取数
- 需要 DICloak 里那个 UW 的 profile 开着、已登录，并且那个窗口打开了 View > Developer > Allow JavaScript from Apple Events。任何 unusualwhales.com 页面都能用（登录信息在 localStorage 里），有就直接用，先用轻的页面，large-trades 这种实时页面排在最后。一个都没有时，在 `.uwweb_state.json` 记住的 profile 里后台开一个 `robots.txt`（同一个网站下的纯文本页，几乎不占内存），取完就关；进程退出时也会关（ZZ 2026-11-24："large-trades 这种吃内存的你fetch好就关了，不要一直开着占用内存"）。人自己开的页面不关。11-24 实测：robots.txt 页取的 NVDA 1D / 2D 和 dashboard 页逐字节相同，开页 + 取数 4 秒。任何一步不行都只用 API，不影响别的层
- `--asof` 时间点模式不取网站（网站只有最新一天）；`--no-dicloak` 关掉这一步。单独看网站某只票当天的数：`python3 -m uwsf.uwweb NVDA`

## 补充数据

lit-blocks、ohlc-daily（含 HV20 序列）、ohlc-5m、oi-change、option-contracts（仅实时；含 chain_depth：全链有效合约的不同 strike 数 nstrk，THIN = nstrk < 45）、iv-rv（`/api/stock/{t}/volatility/realized`：IV30 日序列 + 按窗口末日重排的 21 日 RV）、oi-per-strike、options-volume、interpolated-iv、option-sentiment（AVAR，作为上行尾部的替代指标）、unusualness（活跃度，仅实时）、options-pulse（开仓买入笔数）、multi-leg（领口 / roll 的形状）、flow-per-strike 和 net-prem-ticks（历史 flow）、flow-alerts（UW 按规则触发的期权告警，可以查历史，也可以截到分钟）、spot-gex（逐分钟的 spot gamma/charm/vanna）、greek-exposure-strike、offlit-levels（DP 的第二视角）、contract-history（关键合约的 OI 历史）、rr-skew（25Δ）、screener。

数据源本身的限制：UW 的暗池和场内逐笔接口只收 premium ≥ $10 万的成交，是大单子集，不是完整的逐笔成交。所以逐价位的 DP% 只能用 price-levels（全天汇总）来算。
市场层面的数据：交易日历（SPY）、熔断池（screener 一次拉完）、相关性、板块 ETF 申赎。

## 默认参数（都可以调）

`--block-shares 10000 --block-premium 200000 --flow-min-premium 50000 --multileg-min-size 50 --dp-days 22 --gex-days 6 --flow-days 5 --concurrency 4`

option-trades 的聚合里另有 flow_iv：call/put 各自按 premium 加权的成交 IV（ask 侧 / 全部），剔除 0DTE、cross_trade、futures_floor。

`brief.py --date D --tickers A,B,... --cross-section <market_brief.json>`：把全名单截面（涨跌、SVR、DP 量对均值、大单参与度、net gamma）写进市场数据，daily_short/run.sh 在逐只分析前调用。

每份 brief 开头有 `template_inputs`（ZZ 2026-10-17 的固定 7 段报告用，只有数字、不下结论）：常规时段 4H K 线（近 10 个交易日，由 ohlc-5m 合成，09:30–13:30 / 13:30–16:00）、DP 成本区和去掉收盘参考价单后的 2D 主要节点、当天暗池量的分布（`dark_pool.day_flow`：去掉收盘参考价单后最集中的 1% 价格带和占比、当天重心比开盘 / 最高或最低、重心有没有跟上当天的涨跌，ZZ 2026-11-12）、期权 premium 按类型 × 期限 × ask/bid × 单腿/多腿拆分、逐 strike 的 GEX 和 DEX（greek-exposure-strike 现在带 call/put delta）、IV 期限（7 / 30 天）、空头数据（UW + `finviz_si/<T>.json` 里的 Finviz SI）。

## 已经处理的数据坑

- greek-exposure、SI、short-volume、short-data 都按日期取 max(date) ≤ D 的那一行，不按位置取第一行或最后一行
- ohlc/1d 实际返回是新的在前（spec 写的是旧的在前），而且每天 3 行（pr/r/po），只保留 r
- darkpool price-levels 的数字字段是字符串；档位网格是每美元 X.00 和 X.75 两档，每天一致（网站 Price Group 把每格写成 "$X–$X+0.25"，其实一格一直到下一个标签）
- darkpool 和 lit-flow 一旦带上 `older_than`，就会忽略 `date` 参数，所以翻页时按纽约日期过滤，跨到前一天就停
- flow-per-strike 直接返回数组；option-contract historic 的数据在 `chains` 键下；gex-levels 的 `data` 是字典
- option-contracts 单次最多 500 行，超过时按到期日拆开拉
- screener 的 `short_int` 返回 0，跟 interest-float/v2 对不上，所以不用
- short_screener 的 `tickers` 过滤不生效，不用
- 期权 flow 的 strike 会跟 OCC 代码对一遍（SHORT_ENGINE §7.1），画墙只用 gex-levels
- 场内的开盘/收盘竞价（nasdaq_official_*、cross_trade、opening/closing_print）不算大单，单独列在 `auction` 下
