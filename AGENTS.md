# AGENTS.md — claw-short

做空候选分析 bot。

- 规则唯一来源：`SHORT_ENGINE.md`（与其他文档冲突时以它为准）
- 数据工具：`uw_short_fetch/`（只取数、不判断；用法见其 README.md）
- 每日收盘扫描：`daily_short/run.sh`（17:00 ET 定时任务调用，每只票一个独立会话）
- 每次分析实际用的数据：`analysis_data/<日期>/`（market_brief.json + 每只票一个 json）；结果在 `daily_short/logs/<日期>/`
