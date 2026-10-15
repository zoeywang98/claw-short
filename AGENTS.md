# AGENTS.md — claw-short

做空候选分析 bot。

- 规则唯一来源：`SHORT_ENGINE.md`（与其他文档冲突时以它为准）
- 数据工具：`uw_short_fetch/`（只取数、不判断；用法见其 README.md）
- 每日收盘扫描：`daily_short/run.sh`（17:00 ET 定时任务调用，每只票一个独立会话）
- 盘后每只票的分析前先发一张 §4.2 暗池重心迁移图：`daily_short/dp_chart.py`，用 analysis_data 里同一份 brief 画，只画数据不下结论；PNG 在 `media/dp_charts/<日期>/`（不进 git）
- 每次分析实际用的数据：`analysis_data/<日期>/`（market_brief.json + 每只票一个 json）；结果在 `daily_short/logs/<日期>/`
- 盘前确认：`daily_short/premarket.sh` → `confirm.py`（06:50 ET 定时任务，周一至周五；UW 的 OI 06:30 起逐个合约更新，06:45 左右更新完）：拿今早公布的次日 OI 复核上一次扫描的每一只票（不论档位）；输入在 `analysis_data/<日期>_premarket/`，结果在 `daily_short/logs/<日期>_premarket/`
- 盘中盯线：`daily_short/watch.sh` → `watch.py`（定时任务"claw-short 盘中盯线"，09:30–16:05 ET 每 5 分钟）。每份报告末尾的 ```watch 判决线在发帖时会被删掉，另存为 `logs/<run>/<T>.watch.json`。盯线拿 UW screener 一次请求取全部现价比对，破线在频道提醒，同一条线一天只报一次；状态在 `daily_short/logs/<日期>_watch/`
- 破线自动重跑：`daily_short/rerun.py T…`。盯线发现破线后在后台启动，现拉数据、用当天规则重读这只票，再贴一条简版（结论 / 仓位 / 失效位）。每只票每天最多重跑 1 次，全天最多 8 次，15:45 以后只提醒不重跑。数据标成 `<日期>_HHMM`，所以 17:00 扫描照常从干净的目录开始
