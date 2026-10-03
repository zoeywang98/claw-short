# AGENTS.md — claw-short

做空候选分析 bot。

- 规则唯一来源：`SHORT_ENGINE.md`（与其他文档冲突时以它为准）
- 数据工具：`uw_short_fetch/`（只取数、不判断；用法见其 README.md）
- 每日收盘扫描：`daily_short/run.sh`（17:00 ET 定时任务调用，每只票一个独立会话）
- 盘后每只票的分析前先发一张 §4.2 暗池重心迁移图：`daily_short/dp_chart.py`，用 analysis_data 里同一份 brief 画，只画数据不下结论；PNG 在 `media/dp_charts/<日期>/`（不进 git）
- 每次分析实际用的数据：`analysis_data/<日期>/`（market_brief.json + 每只票一个 json）；结果在 `daily_short/logs/<日期>/`
- 盘前确认：`daily_short/premarket.sh` → `confirm.py`（06:50 ET 定时任务，周一至周五；UW 的 OI 06:30 起逐个合约更新，06:45 左右更新完）：拿今早公布的次日 OI 复核上一次扫描的每一只票（不论档位）；输入在 `analysis_data/<日期>_premarket/`，结果在 `daily_short/logs/<日期>_premarket/`
