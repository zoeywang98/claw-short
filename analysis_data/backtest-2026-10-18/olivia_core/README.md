# Olivia 的"核心做空指标"回测（2026-11-12，ZZ："这一点我们的rulebook里有吗，着重分析"）

- 原话（Olivia 11/12 04:12）："dp量大，但价格在dp量大价格之下也在长周期dp核心价格之下就是核心做空指标"
- 样本：2026-08-13 到 11-11，23 只名单（1M 窗口要 21 天历史，暗池逐日 price-levels 从 7/16 起：7/16–8/24 用 dp_trap/fetch_dp.py 重拉到 /private/tmp/bt_trap/dp_raw，8/24 以后用 uw_short_fetch/cache，缺的用 11/11 brief 的 per_day）
- 日线：../prices.json + 10/26、11/11 brief 的 last_22_bars
- 重心按 layers.level_stats 重算（panel2.py）；和 10/16、11/04、11/11 brief 的 2D / 1M 对了 138 次，3 次差 >0.5%
- 口径（阈值是我定的）：放量 = 当天暗池 ≥ 1M 日均 1.3 倍（同 day_flow）；"dp量大价格" 试了当天最密 1% 价带、当天 POC、1D 重心、2D 重心；"长周期核心" 试了 1M 重心和 1M POC
- 胜率：之后 1 / 3 / 5 天跑输 23 只等权平均的比例（同 10/18 回测），"跌"是真跌；td = 按日期聚合后的 t 值
- 文件：panel2.py → panel2.json；olivia_bt.py（主口径、拆分、两段）、more.py（2D 口径、事件明细）、poc.py（1M POC、光模块拆分）；输出在 results.txt

## 第二轮（ZZ 13:03："那你回测：放量冲上去，收盘掉回大量价位下面，但还在长周期核心上方"）
- 样本拉长到 2026-04-30 → 11-11（fetch_more.py 补了 4/01–7/15 的暗池 price-levels，到 /private/tmp/bt_trap/dp_raw，1,656 次请求；日线用 1 年 ohlc/1d 的 regular 段 prices1y.json，和 ../prices.json 重叠部分 0 处不一致）
- 主口径：当天暗池 ≥ 1M 日均 1.3 倍 + 冲高（最高相对昨收的幅度 ≥ 最低的幅度，同 day_flow 的 move=up）+ 收盘 < 当天最密 1% 价带下沿 + 收盘 ≥ 1M 重心；另试放量 1.0/1.5/2.0、冲高 ≥3%/≥5%、"大量价位"换 POC / 1D / 2D 重心、1M POC
- 文件：panel3.py → panel3.json；bt2.py（主口径、对照、敏感度、拆分、事件明细和当晚档位）；regime.py（名单 20 天平均涨幅分强弱）；输出 results_zz2.txt

## 第三轮（ZZ 13:23："那你时间放长，回测……就是核心做空指标"）
- 样本拉长到一年：2025-12-11 → 2026-11-11（fetch_year.py 补了 2025-11-12–2026-03-31 的暗池 price-levels，2,185 次请求，到 /private/tmp/bt_trap/dp_raw；1M 窗口要 21 天，所以从 12/11 起算）
- 注意：这一年"跑输平均"的基准是 54–56%（超额收益右偏，中位数为负），要和基准比，不是和 50% 比
- 文件：panel4.py → panel4.json；bt3.py（原口径、敏感度、拆分、对照、每月次数）；输出 results_year.txt
