# analysis_data

每次扫描时模型实际读到的数据，一天一个目录（`daily_short/run.sh` 在逐只分析前写入）。

```
analysis_data/<日期>/
  market_brief.json   市场数据：熔断计数（watchlist_breaker_board）、全名单截面（watchlist_cross_section）、日历、相关性、板块 ETF
  <票>.json           该票的 brief，就是分析时的"本票数据"，逐层运行日志在里面的 run_log_core
```

- 模型的输入 = `SHORT_ENGINE.md` + `daily_short/INSTRUCTIONS.md` + 这里的 `market_brief.json` 和 `<票>.json`
- 分析结果：`daily_short/logs/<日期>/<票>.reply.json`
- 完整数据和原始 API 返回：`uw_short_fetch/runs/tickers/<票>/<日期>/<票>/`（snapshot.json、raw/）；市场层：`uw_short_fetch/runs/market/<日期>/`

已有目录：
- `2026-09-25-v1`：9/25 原来那次扫描（旧版规则，9/28 凌晨跑）的输入，从 git 7c51810 取回
- `2026-09-25`：9/28 下午用新版规则和新脚本重跑 9/25 的输入（原数据补了新字段），另有 ARM（不在名单，单独拉的）
- `2026-09-28`：9/28 17:00 定时扫描的输入
