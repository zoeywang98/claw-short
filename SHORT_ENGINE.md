# SHORT_ENGINE.md — 做空规则（v3 · 2026-10-18）

只保留回测里准的 4 条做空规则（ZZ 2026-10-18："只保留这 4 个 rule"）。
依据：9/25–10/16 共 368 份收盘报告的规则回测（`analysis_data/backtest-2026-10-18/`）。
- 胜率 = 之后跑输名单 23 只等权平均的比例。
- 1 天胜率都在 50% 左右，优势在 3–5 个交易日。
- 限制：只有 16 天、一个行情阶段，样本攒多了要重算。

## 共同前提：收盘跌破 2D 暗池重心

四条都要求收盘跌破 2D 暗池重心。没跌破的票，不管别的信号怎样，一律不做空。
- 2D 暗池重心 = `darkpool_levels.windows.2D.centroid_top8`：最近 2 个交易日 dark 量最大的 8 个价位，按 dark 量加权的中心。
- 收盘 = `price.derived.close`。
- 回测对照：跌破 2D 重心但一条规则都没命中的票，3 天只有 45% 跑输平均，没有优势。

## 4 条规则（命中任一条 = 做空）

**规则 1 · 挤仓名单跌破 2D 重心**：3 天胜率 83%，5 天 87%（29 / 23 次）
- SI ≥ 10% float，或 SVR 连日 ≥ 55%；
- 且 DTC ≤ 2，或最近三期 DTC 逐期上升；
- 且 |收盘 − gamma flip| ≤ 3%（flip 用 `gex_levels.latest`，vol 口径）；
- 且收盘跌破 2D 重心。

**规则 2 · 负 gamma 跌破 2D 重心**：3 天 84%，5 天 73%（19 / 11 次，样本小）
- `greek_exposure.today.net_gamma` < 0；
- 且收盘跌破 2D 重心；
- 且不在 IV>RV 高位。

**规则 3 · 拥挤跌破 2D 重心**：3 天 70%，5 天 79%（54 / 43 次）
- SI ≥ 10% float，或最新一天 SVR ≥ 55%；
- 且收盘跌破 2D 重心。
- 规则 1 是规则 3 里最强的一组，同时命中就都写。

**规则 4 · 派发信号跌破 2D 重心**：3 天 75%，5 天 76%（52 / 37 次）
- 下面任一成立：
  - **派发确认**：1M > 1W > 2D 重心逐级下移，且价格失守高位，即跌回 DP core 下方、回踩站不回去（1M / 1W / 2D = `darkpool_levels.windows` 的 `centroid_top8`）；
  - **派发指纹**：DP 量大但价位不上迁；call 写在 bid；call OI 平 / 降，或 put OI 增；IV 平 / 压缩；
  - **flow 偏空**：按 ask / bid 意图净额，put 在 ask 买入、call 在 bid 卖出占优（看期权 flow 的 side，不按 call / put 计数）；
  - **put 被买**：`options_volume_5d` 最后一天 `net_put_premium` > 0；
- 且收盘跌破 2D 重心；
- 且不在 IV>RV 高位。

## 定义

- **IV>RV 高位** = `iv_rv` 最后一天 IV30 > RV21，且 `screener.iv_rank` ≥ 50。回测里这类票 5 天 74% 跑赢平均，所以规则 2、4 要排除。
- **SI** = `short_interest.latest.si_float`（FINRA 双月结算，标 as-of 和滞后天数）。
- **DTC** = `short_interest.series` 的 `days_to_cover`。
- **SVR** = `short_volume` 的 `short_volume_ratio`（T+1）。
- Finviz 的 SI 只作对照，不参与判定。

## 档位与失效

- 命中任一规则 → ✅ 做空，写出命中的规则号；都没命中 → ⚪ 不做空。
- 失效：
  - 收盘站回 2D 重心，规则就不再成立；
  - 再收复 1W 重心，空头作废。
- **持有**（ZZ 2026-10-18）：✅ 做空之后一直持有，以开仓那天的 2D 重心为失效位。
  - 结束条件：某天收盘站回失效位，或满 10 个交易日。
  - 持有期间，当天规则不再命中也写"✅ 持有"，不写 ⚪；⚪ 只表示今天不新开空。
  - 回测（44 笔，按这个规则持有）：39% 赚钱，平均每笔赚 4.6%。亏的大多 1–8%，第二天反弹就止损；赚的跌 10–42%。胜率不高，靠大赢家赚钱。

## 数据与纪律

- 数据只用 Unusual Whales：暗池 price-levels、greek-exposure、gex-levels、short interest / volume、options-volume、option-trades、iv-rv。
- 数字只用数据里出现的；缺数据写"未明确"，缺数据的条件按不成立处理。
- 每个数据标 as-of，SI 标滞后天数。

## 已删除（2026-10-18）

下面这些规则都已删除：🧨 挤仓否决、熔断、量级闸、Trap warning 和吸筹 / 库存转移 / 对冲 / Gamma hedge / Fund rebalance 指纹、IV×RV 的其它读法、dealer 决策表、flow 加减置信、板块轧空 veto、挤压反噬标签、THIN、财报 7 天、caveat 降档。

旧版全文：`analysis_data/backtest-2026-10-18/SHORT_ENGINE.before.md`。
