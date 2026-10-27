# RULEBOOK 全部规则回测（2026-10-27，ZZ："回测rulebook里的所有rule"）

- 规则来源：~/Downloads/RULEBOOK.pdf（Part I–VII 加附录 canonical RULEBOOK.md），加上 DP_读法_灰色重心迁移法.pdf 和 Dealer_Hedging_Rules_Full_Guide.pdf
- 样本：2026-07-22 到 10-26，23 只名单。3 天结果只到 10/21，5 天只到 10/19
- 胜率口径同 10/18 回测：看空规则数"跑输 23 只等权平均"的比例，看多 / 禁空规则数"跑赢"的比例，"绝对"是真涨或真跌。td 是按日期聚合后的 t 值
- 数据（只取数）：fetch_all.py 用了 1,250 次 UW 请求，原始数据在 /private/tmp/bt_all/raw，不进 git
  - 每只票一次请求就能拿到历史：options-volume（500 天，按 ask/bid 拆分的成交量、权利金、call/put OI）、greek-exposure（1 年 net gamma / delta）、volatility/realized（1 年 IV30 / RV21；RV 按 unshifted_rv_date 重新对日期，同 layers.py）、short volume（500 天）、SI（结算日 +7 个工作日才算公布）、借券费 / 可借量（7/08 起）、财报日、4H K 线、日线
  - gex-levels（vol 口径）按天取，cache 里没有的才补
  - 暗池逐日 price-levels 和 dp_trap 用的是同一份
- features.py 生成每天的特征表 features.json；rules.py 是 78 个机械测试；结果在 rules_out.txt / rules_out.json
- 只有扫描日（9/25 起）有的数据：大单参与度（brief 的 derived.block_participation）、flow-IV（history/flow_iv）
- 阈值大多是我定的，文件里没有给数，具体见 rules.py 里每条规则的定义。几个关键的：
  - 放量 = 1D 暗池量 ≥ 1M 日均（或其 1.5 倍）
  - IV 高位 = 1 年 IV30 区间里的位置 ≥0.5，低位 <0.3
  - 熔断 = 名单里负 gamma ≤4/23
  - "派发读数" = 1M>1W>2D 并且收盘 < 2D，用作各种闸的对照空头信号
  - Call Holder Trap 的第一触发原文要 cliff 双侧扩张，这里换成同一天 call OI、put OI 都增加
- 测不了：cliff / vit / tail / floor 那一整套（点火、push-out、ttX、tailTop、受阻、put 端 ≥2 项确认、floor 在升、THIN 链、低价票打折、入场 setup、rank_v2 评分、塌缩摘除），还有 IV rank 定 call 贵贱（要算期权损益）、HIRO / SpotGamma / MenthorQ 层，以及流程类规则（as-of、caveat 降档、禁沉默、口吻）
- 结论分档：成立 3、反向 6、没优势 46、"没方向"说对了 7、没方向却说错了 4、样本不够 12
- 限制：只有 3 个月、一个行情阶段（8 月光模块震荡，9 月底轧空，10 月回落）；样本重叠；78 个测试存在多重检验
