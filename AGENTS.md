# AGENTS.md — claw-short

做空候选分析 bot。

- 规则唯一来源：`SHORT_ENGINE.md`（与其他文档冲突时以它为准）。v3（ZZ 2026-10-18）只剩回测里准的 4 条做空规则，都要求收盘跌破 2D 暗池重心；回测和旧版全文在 `analysis_data/backtest-2026-10-18/`。✅ 里跌破 2D 不到 2%、又是第一天跌破的标"浅"（ZZ 2026-10-18，回测弱一档；数据在 brief 的 `template_inputs.dark_pool.close_vs_2D` / `prev_session`）
- 数据工具：`uw_short_fetch/`（只取数、不判断；用法见其 README.md）
- 每日收盘扫描：`daily_short/run.sh`（17:00 ET 定时任务调用，每只票一个独立会话）
- 报告格式固定（ZZ 2026-10-17："不要每天编造你自己的语言"）：`daily_short/INSTRUCTIONS.md` 的 7 段（价格结构 / Dark Pool / Options Flow / Dealer Positioning / Delta Exposure / IV / 空头闸），每行句式和取数口径写死；所需数字由 `brief.py` 算好放在 brief 的 `template_inputs`。Dark Pool 段有两行当天量（ZZ 2026-11-12）：当天暗池几倍日均、最集中在哪、重心比开盘 / 最高低多少，以及"重心没跟上价格"这类判断（`dark_pool.day_flow`）。盘前确认（`CONFIRM.md`）用同一套标题和说法，只写有新数据的段落
- 空头闸的 SI 用 Finviz：run.sh 调 `workspace-claw-general/finviz/fv_short_interest.py`（读 DICloak 里登录着的 Finviz 窗口），存 `uw_short_fetch/finviz_si/<T>.json`；拉不到时报告写"Finviz：没拉到"，不影响别的。规则判定用 UW 的 SI / SVR / DTC
- 盘后每只票的分析前先发一张暗池重心迁移图（1M / 1W / 2D，加第四格"当天新增"＝当天的暗池量，ZZ 2026-11-12）：`daily_short/dp_chart.py`，用 analysis_data 里同一份 brief 画，只画数据不下结论；PNG 在 `media/dp_charts/<日期>/`（不进 git）
- 每次分析实际用的数据：`analysis_data/<日期>/`（market_brief.json + 每只票一个 json）；结果在 `daily_short/logs/<日期>/`
- 盘前确认：`daily_short/premarket.sh` → `confirm.py`（06:50 ET 定时任务，周一至周五；UW 的 OI 06:30 起逐个合约更新，06:45 左右更新完）：拿今早公布的次日 OI 复核上一次扫描的每一只票（不论档位）；输入在 `analysis_data/<日期>_premarket/`，结果在 `daily_short/logs/<日期>_premarket/`
- 盘中盯线：`daily_short/watch.sh` → `watch.py`（定时任务"claw-short 盘中盯线"，09:30–16:05 ET 每 5 分钟）。每份报告末尾的 ```watch 判决线在发帖时会被删掉，另存为 `logs/<run>/<T>.watch.json`。盯线拿 UW screener 一次请求取全部现价比对，破线在频道提醒，同一条线一天只报一次；状态在 `daily_short/logs/<日期>_watch/`
- 持有中（ZZ 2026-10-18）：`daily_short/holding.py` 从之前的收盘扫描里找这只票最近一次"✅ 做空 · 规则 n"，以开仓日 2D 重心为失效位，收盘站回或满 10 个交易日才结束；analyze.py 把它作为"持仓状态"传给模型，报告写"✅ 持有"而不是 ⚪
- 破线自动重跑：`daily_short/rerun.py T…`。盯线发现破线后在后台启动，现拉数据、用当天规则重读这只票，再贴一条简版（综合结构 / 结论 / 失效位 三行）。每只票每天最多重跑 1 次，全天最多 8 次，15:45 以后只提醒不重跑。数据标成 `<日期>_HHMM`，所以 17:00 扫描照常从干净的目录开始
- 暗池区间盯（Olivia 2026-11-11 设区间、"两小时统计一次"；ZZ："一直盯着"）：`daily_short/dpzone.sh` → `dpzone.py`（定时任务"claw-short 暗池区间盯"，09:30–16:00 ET 每 5 分钟）。区间写在 `daily_short/dpzone/zones.json`（票、显示名、价位、派发 dist / 吸筹 accum、开始日期、股数门槛；until 和收盘 stop 价可选，现在都不设 = 一直盯）。每次读区间内今天的暗池量（UW price-levels）和 5 分钟线：今天累计 ≥ 门槛、今天最高（派发）/ 最低（吸筹）已经 30 分钟没再刷新、价格没越过区间 → "符合：放量但涨不上去 / 跌不下去"，第一次符合就在频道单独提醒（每个区间一天一次）；11:30 / 13:30 / 15:30 另发一条统计（上次以来新增、今天累计、最高 / 最低、现价、判断）。每条帖子开头 @ZZ 和 Olivia（ZZ 2026-11-12："你这个要@我们"，dpzone.py 的 NOTIFY）。每条统计发出后，后台再跑 `dpzone_chart.py`，给每只票发一张盘中的 4 格暗池重心图（1M / 1W / 2D / 当天新增；ZZ 2026-11-12 "要"）。它现拉数据到 /tmp，不碰 runs/，用 `dp_chart.py --asof HH:MM` 画，日志在 `dpzone/chart_<日期>.log`。状态和日志在 `daily_short/dpzone/`
