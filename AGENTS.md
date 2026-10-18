# AGENTS.md — claw-short

做空候选分析 bot。

- 规则唯一来源：`SHORT_ENGINE.md`（与其他文档冲突时以它为准）。v3（ZZ 2026-10-18）只剩回测里准的 4 条做空规则，都要求收盘跌破 2D 暗池重心；回测和旧版全文在 `analysis_data/backtest-2026-10-18/`
- 数据工具：`uw_short_fetch/`（只取数、不判断；用法见其 README.md）
- 每日收盘扫描：`daily_short/run.sh`（17:00 ET 定时任务调用，每只票一个独立会话）
- 报告格式固定（ZZ 2026-10-17："不要每天编造你自己的语言"）：`daily_short/INSTRUCTIONS.md` 的 7 段（价格结构 / Dark Pool / Options Flow / Dealer Positioning / Delta Exposure / IV / 空头闸），每行句式和取数口径写死；所需数字由 `brief.py` 算好放在 brief 的 `template_inputs`。盘前确认（`CONFIRM.md`）用同一套标题和说法，只写有新数据的段落
- 空头闸的 SI 用 Finviz：run.sh 调 `workspace-claw-general/finviz/fv_short_interest.py`（读 DICloak 里登录着的 Finviz 窗口），存 `uw_short_fetch/finviz_si/<T>.json`；拉不到时报告写"Finviz：没拉到"，不影响别的。规则判定用 UW 的 SI / SVR / DTC
- 盘后每只票的分析前先发一张暗池重心迁移图（1M / 1W / 2D）：`daily_short/dp_chart.py`，用 analysis_data 里同一份 brief 画，只画数据不下结论；PNG 在 `media/dp_charts/<日期>/`（不进 git）
- 每次分析实际用的数据：`analysis_data/<日期>/`（market_brief.json + 每只票一个 json）；结果在 `daily_short/logs/<日期>/`
- 盘前确认：`daily_short/premarket.sh` → `confirm.py`（06:50 ET 定时任务，周一至周五；UW 的 OI 06:30 起逐个合约更新，06:45 左右更新完）：拿今早公布的次日 OI 复核上一次扫描的每一只票（不论档位）；输入在 `analysis_data/<日期>_premarket/`，结果在 `daily_short/logs/<日期>_premarket/`
- 盘中盯线：`daily_short/watch.sh` → `watch.py`（定时任务"claw-short 盘中盯线"，09:30–16:05 ET 每 5 分钟）。每份报告末尾的 ```watch 判决线在发帖时会被删掉，另存为 `logs/<run>/<T>.watch.json`。盯线拿 UW screener 一次请求取全部现价比对，破线在频道提醒，同一条线一天只报一次；状态在 `daily_short/logs/<日期>_watch/`
- 持有中（ZZ 2026-10-18）：`daily_short/holding.py` 从之前的收盘扫描里找这只票最近一次"✅ 做空 · 规则 n"，以开仓日 2D 重心为失效位，收盘站回或满 10 个交易日才结束；analyze.py 把它作为"持仓状态"传给模型，报告写"✅ 持有"而不是 ⚪
- 破线自动重跑：`daily_short/rerun.py T…`。盯线发现破线后在后台启动，现拉数据、用当天规则重读这只票，再贴一条简版（综合结构 / 结论 / 失效位 三行）。每只票每天最多重跑 1 次，全天最多 8 次，15:45 以后只提醒不重跑。数据标成 `<日期>_HHMM`，所以 17:00 扫描照常从干净的目录开始
