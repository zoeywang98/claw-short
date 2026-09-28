# AGENTS.md — claw-short

做空候选分析 bot。

- 规则唯一来源：`SHORT_ENGINE.md`（与其他文档冲突时以它为准）
- 数据工具：`uw_short_fetch/`（只取数、不判断；用法见其 README.md）
- 每日收盘扫描：`daily_short/run.sh`（17:00 ET 定时任务调用，每只票一个独立会话）
