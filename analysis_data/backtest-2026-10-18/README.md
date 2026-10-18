# 规则回测 2026-10-18（ZZ："回测那些对的分析，trigger 的 rule 是不是准的"）

- 样本：logs/2026-09-25 … 2026-10-16 的 368 份收盘扫描报告（16 天 × 23 只）
- 触发的规则：`extracted.json`，由 Sonnet 5.5 从报告原文抽取（scripts/extract.py），每份一条：档位、🧨 三条、熔断、③、④ 读数、重心顺序、⑤ 指纹、IV×RV、⑥ 决策表、flow、挤压反噬、THIN、财报
- 原始信号：`signals.json`，从 analysis_data/<D>/<T>.json 直接重算（scripts/signals.py），不依赖模型判断
- 结果：`prices.json` 是日线；`joined.json` 记录每条报告 D 收盘后 1 / 3 / 5 个交易日的涨跌，以及相对 23 只等权平均的超额
- 输出：`results.txt` 是全部规则；`drill.txt` 按日期、按票、去掉光模块、只看 10/08 前；`drill2.txt` 是 🧨 / 拥挤 × 2D 重心等组合
- 限制：只有 16 天、一个行情阶段；样本重叠（3 / 5 天窗口、同一只票连续多天）；约 70 个组合，存在多重检验；规则版本在 9/28、10/14 改过
