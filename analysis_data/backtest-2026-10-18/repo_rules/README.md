# claw-stock rules/ 借鉴回测（2026-10-18，ZZ："看一下 claw-stock/rules 有没有什么 rule 有借鉴意义"）

- 来源：github.com/zoeywang98/claw-stock `rules/`（CANON.md F1–F14、learning/、memory/ 的 fail_* 和做空相关 feedback）
- 样本、口径同上一级目录：9/25–10/16 的 368 份收盘扫描，3 / 5 天跑输 23 只等权平均的比例；v3 四条规则的机械版同 /tmp/bt/four.py
- cand.py：所有能用 UW 数据算的候选规则；drill.py：距 2D 重心阈值、去光模块、前后半段、Gamma+DEX 和 A 段闸的稳健性；dist_hits.py：v3 命中按距 2D 重心分档 + 10/16 的 13 只
- 结论：只有 F1.5（±2% = AT-spot 带）在我们数据里成立且有梯度；Gamma+DEX、A 段闸有苗头但样本小 / 分不开光模块；F10 shortG、板块 beta 否决、借券收紧、SI 降、DTC>5、相位闸测出来没用或反向
- A 段闸的定义（30 日内涨 ≥15% 且期间 IV30 上升）、可借量 ±30/50% 是我定的阈值，仓库里没给数

## uw-summary skill（rules/skills/uw-summary、rules/claude-skill/uw-daily-summary，ZZ 14:23 "skill里的uw summary呢"）
- skill.py / skill_drill.py：skill 自己的 10 条读法；大部分是 CANON 复述，加上可见 Chrome / MenthorQ 的取数流程（已过时）
- 有用：「趋势仓 > 反转仓」——v3 命中里前一天已在 2D 下方的 3/5 天 80% / 85%，第一天跌破的 59% / 68%；和距 2D 深度合起来，浅（≤2%）且第一天跌破 = 49% / 68%（n 35/31），其余 85% / 81%（n 39/26）
- 没用 / 反向：暗池绝对量（高量看着更准，但全是深度效应，≤2% 里没差别；<5% 闸在我们数据里从不触发）、拥挤 + 刚跌过 = 燃料（反向）、借券松 = 空头舒服（反向）、跟前一天比重仓带下迁、低点大单吸收、DP + flow 双源
- 样本太小：contest day、财报前、暴跌 + put 爆量
