# SHORT_ENGINE.md — 做空候选分析唯一规则文档

> 本文档是今后做空候选分析的**唯一**规则来源，由 RULEBOOK（UW 暗池/期权流/GEX 规则书）与 Dealer Hedging Rules 提炼合并而成，只保留做空相关逻辑。与旧文档冲突时，以本文档为准。
>
> **数据源只有两个：Unusual Whales API（简称 UW API）和 QuantData 网页版。** 不使用 MenthorQ、OptionData 或任何其他来源；所有"结构位"（Call Wall / Put Wall / Gamma Flip）一律来自 UW `gex-levels`，"OI 是否真实变化"一律用 UW 期权链 OI 数据或 QuantData 网页的 OI 变化页面做次日确认。

---

## 0 · 唯一不可动摇的框架

- **不预测价格。** 找的是"谁在什么位置、为什么这样持仓"的名字，输出的是仓位、意图、不对称性和失效位（invalidation），不是目标价。
- **暗池（DP）成交量不是信号，只是量级闸门**——它只说明"发生了事情"。方向来自真实的逐档 DP% 与多窗口价格迁移；动机来自多信号联合签名。**永远不要**用自制的"重心 vs 现价偏移"代替真实 DP%，**永远不要**用单一快照定方向（这正是 AXTI/NBIS 误判的根源）。
- 所有概率均为风险中性/隐含概率，不是 alpha。

---

## 1 · 数据源与层级映射

### 1.1 UW API 端点（8 层）

| 角色 | 层 | UW API 端点 | 关键字段 |
|---|---|---|---|
| Trigger | DP 方向 | `darkpool-levels` | 逐档 DP%（dark vs regular volume） |
| Safety | DP 大单 | `darkpool` | 大宗成交的时间/规模 |
| Flow | 期权意图 | `option-trades` | side（ask/bid）、premium、sweep |
| Ready | GEX 墙 | `gex-levels` | gamma_flip / magnet / call_wall / put_wall |
| Ready | 做市商 gamma | `greek-exposure` | 一年期序列；今天 = `max(date)` 行 |
| Veto | 空头持仓 | `short-interest` | si_float、days_to_cover、fee_rate、shares_available |
| Veto | 空头成交比 | `short-volume` | short_volume_ratio（payload 键是 `si` 不是 `data`） |
| Veto | 借券 | `short-data` | 实时借券费率 + 可借股数 |

8 层全部可经 REST 运行——失败就是真实故障（空 payload / API 错误），不存在"该层不可用"。

**DP% 原语（唯一合法算法）：** 每个价位档 `pct = dark_pool_volume / (dark_pool_volume + regular_volume)`。这才是真实逐档 DP%。

### 1.2 QuantData 网页版的用途

QuantData 只做**交叉验证与次日确认**，不做首发信号：

- 次日确认 OI 变化（对应原 OptionData 的角色）：昨天的 flow 是否真的变成了新持仓。
- 暗池大单打印、GEX 结构位的第二视角核对（与 UW API 数字不一致时，以 UW API 为准并记录分歧）。

### 1.3 数据新鲜度表（每条腿必须标注 as-of）

| 层 | 节奏 | 典型滞后 |
|---|---|---|
| `darkpool-levels` / `darkpool` | 实时（约延迟 15 分钟） | 当日 |
| `option-trades`（flow） | 盘中实时 | 当日 |
| `gex-levels` / `greek-exposure` | 实时；序列为一年期 | 当日（取 `max(date)`，不是第一行） |
| `short-interest`（SI% float） | FINRA 双月结算 | **滞后约 2–3 周** |
| `short-volume`（场外空头比） | T+1 | 前一交易日 |
| `short-data`（借券费/可借量） | 实时 | 当日 |

**Veto 权重规则：** 因 SI% float 滞后约 2 周，挤仓否决以**实时借券费率 + T+1 空头成交比**为主导，SI% float 降级为背景参考。用陈旧触发换取实时借券证据。

---

## 2 · 强制前置：挤仓否决（Squeeze Veto）

**在给任何做空候选排名之前必须先跑。** 检查 SI%、场外空头成交比、借券费率 + 可借量。

- **SI 高，或借券紧张（费率高/可借量少），或该名字刚刚急涨 → 🚫 禁止做空。** 暗池看不到被迫回补的买家；这种名字上的高空头比例是**燃料，不是卖压**——不要读反。
- 此类名字最多只允许"flip 收复失败后的限定风险彩票单"：风险 ≤ 0.25% 账户，且不追穿越 gamma flip 超过 1 ATR 的价格。
- **全部干净（低 SI + 低费率 + 可借充足）→ 该做空候选才允许进入后续分析。**

---

## 3 · 强制熔断：做空引擎断路器（Circuit Breaker）

若做市商 gamma 全场是正 gamma 压制（板块内负 gamma 名字 ≤ 4/35，或等效证据表明多数名字处于正 gamma）：

- **做空引擎熔断：当日零确认做空**，只允许输出决策线（"跌破 X 之前不构成 setup"）。
- 正 gamma 毯子之下，派发阶梯会被逢跌买入直接买穿——做空不成立。
- **当日拿不到 GEX 数据 → 默认熔断**（保守处理）。

---

## 4 · 三步读取顺序（量级 → 方向 → 动机）

硬性顺序，不许跳步，不许用记忆里的近似值代替实拉数据。

### 第 1 步 · 量级闸门（Magnitude）

- 绝对 DP 成交量是否足够大？**绝对量 = 置信度，永远不定方向。**
- 大单参与度约 16–21% = 机构（可信）；约 3–4% = 散户噪音（打折）。
- 量太薄 → 不许强行给方向。

### 第 2 步 · 方向（Direction）

方向 = 真实逐档 DP%（§1.1 原语）+ 多窗口迁移。拉 `darkpool-levels --date <D>` 覆盖今日 / 1 周 / 1 月三个窗口，计算 top-8 档的 DP 加权重心，比较迁移：

- **做空关注的形态：重心下移或走平、下跌后档位在更低位置重建、价格站不上各档 → 派发（distribution）/看空。**
- 重心上移且价格逐级站稳 = 吸筹/看多 → **不是做空候选，直接排除。**
- 单窗口偏移不是方向；两个快照不是价格行为——必须拉真实多窗口价格路径，读 DP 价格带的 K 线，而不是名义金额。

### 第 3 步 · 动机（Motive）

动机 = 跨 OI-vs-volume、ask 侧 flow-IV、SI/借券、gamma 位置的**联合签名因果推断**，从六指纹中选一个并给出证据链。禁止只贴"吸筹/派发"二元标签。

---

## 5 · 动机指纹：唯一的做空指纹与五个排除项

同样的 DP 大单，动机不同 → 交易方向相反。读联合签名，不读规模。

### ✅ 唯一可做空的指纹：派发（Distribution）

- DP 量大且 DP% 高，**但档位不上移**（走平/下移）；
- 价格滞涨或阴跌；
- Call OI 走平/下降，或 Put OI 上升；
- IV 走平/压缩；活跃度（vitality）走平/收缩；上行尾部收缩。
- **滞涨本身就是派发的早期信号，先于重心下移出现。**

### 🚫 五个排除指纹（出现任何一个 → 不是做空理由）

1. **吸筹（Accumulation）→ 看多。** DP 集中在现价及下方、档位逐窗口上移、价格逐级站稳、Call OI↑、IV 从压缩低位扩张。
2. **库存转移（Inventory transfer）→ 中性偏多。** 盘后大宗 DP 但 Call OI↑ + IV↑ + 期权量 > OI（新仓）+ 尾部与活跃度扩张。这是机构挪库存建期权仓，不是供给砸盘。**判别式：派发从不与 Call OI + IV + 活跃度同步上升共存。**
3. **Gamma 对冲 → 无方向。** DP 聚集在 gamma 墙/flip 附近、现价穿越关键位时放量、机械且双向、DP% 无持续迁移、IV 不必扩张。是 dealer delta 对冲，不是观点。
4. **对冲/领口（Hedge/Collar）→ 方向降权。** DP 伴随保护性结构（Put OI↑ / collar）、IV↑ 但价格不破位、call 侧活跃度不扩张。是持有人给多头上保险，不是离场——**DP 成交量 ≠ 出货。**
5. **基金再平衡 → 机械性，降权。** 月末/季末或指数调仓时段的大宗 DP、跨相关名字呈篮子状、无期权确认（OI/IV 平）、DP% 只在单一窗口尖峰、价格均值回归。不是知情交易。

---

## 6 · Dealer 对冲确认（结构 + flow + OI 三点合一）

原则：**结构位（UW `gex-levels`）回答"结构性风险在哪"；UW flow 回答"今天谁在主动交易"；次日 OI（UW 期权链 / QuantData）回答"持仓是否真的变了"；价格回答"定位是否被确认"。永远不用单一工具下结论。**

### 6.1 四步法

1. **结构（UW `gex-levels`）**：只观察 Call Wall / Put Wall / Gamma Flip 的位置与移动。墙从 360 移到 365 只能得出"风险中心从 360 移到 365"，**不许**直接推断 dealer 挪仓或客户看多。
2. **Flow（UW `option-trades`）**：看 ask/bid、sweep、premium、volume vs OI。同一时段 360 bid + 365 ask 常提示 roll；连续 ask sweep 提示激进买入。
3. **OI 次日确认**：360 OI 降了吗？365 OI 升了吗？只有确认后才知道昨天的交易变成了新持仓。
4. **推断 dealer 对冲方向**（见决策表）。

### 6.2 决策表（做空视角）

| 信号组合 | 客户行为 | Dealer 对冲 | 做空含义 |
|---|---|---|---|
| Wall↑ + **Bid** + OI↑ | Sell to Open（备兑/熊差 call 卖方） | Dealer 买入 call → **卖股票对冲** | **看空确认：上方形成盖子（cap）** |
| Wall↓ + **Bid** + OI↓ | Sell to Close | Dealer 平仓 → **卖股票**（对冲移除） | 上方支撑撤除，偏空 |
| Wall↑ + **Ask** + OI↑ | Buy to Open | Dealer 卖出 call → 买股票对冲 | 偏多，**不利于做空** |
| Wall↓ + **Ask** + OI↓ | Buy to Close | Dealer 买股票 | 偏多，**不利于做空** |

**重要真相：OI 单独永远不足以判断 dealer 在买还是卖股票**——OI 增可来自客户 Buy to Open 或 Sell to Open，OI 减可来自 Sell to Close 或 Buy to Close。必须叠加 ask/bid 方向。

**最高置信度 = 四点全部一致**：① 结构位移动（`gex-levels`）② UW flow ③ 次日 OI 确认 ④ 价格行为。缺任何一点都降级处理。

---

## 7 · 数据坑与硬性 Gotchas

1. **期权 flow 的 strike 在本账户上编码错位（约 33×）——永远不要用期权 flow 去画 strike 位/写墙。** 现价从 DP 的 NBBO 中点取，不用 `underlying_price`（同样不可靠）。
2. **按意图净额计算，不按 call/put 计数。** "calls > puts" 是陷阱：ask 侧 = 主动买入；bid 侧 = 卖出/被写。**大额 call premium 打在 bid 上 = 卖 call = 盖子，不是点火。**
3. **Flow 从不单独定方向**——只有当它与 DP% 方向 + SI/借券燃料一致时才加一档置信度；不一致时标注冲突、不下注。
4. DP 约延迟 15 分钟（用于盘中结构足够）。
5. `greek-exposure` 返回一年期序列——今天的敞口取 `date == 目标日` 的行，即 `max(date)`，**绝不取第一行**。
6. `short-volume` payload 键是 `si` 不是 `data`；`gex-levels` payload 是嵌套字典 `data={date,time,…}`。
7. SI / short-volume / short-data 各行按**降序**排列——取 `max(date)`，不是最后一行。
8. UW CLI 输出在 JSON 前带 `UW usage: daily used=…` 横幅——解析前先剥掉（`grep -v "^UW usage"` 或从首个 `{` 起 `raw_decode`）。

---

## 8 · 逐层运行日志（可审计性）

每一批分析必须输出"哪些规则层真正跑了 / 哪些失败"的日志，避免把部分运行误当成完整交叉验证：

- 每层输出 `✅ RAN {layer} as-of <date> rows=N` 或 `❌ FAIL {layer} reason: <具体原因>`；
- 汇总一条覆盖率行 `N/8` 并贴到看板；
- FAIL 是真实故障（空 payload / API 错误），永远不是"该层不可用"；
- 每条腿标注各自的 as-of 日期（尤其 SI 的 2–3 周滞后）。

---

## 9 · 做空候选完整流水线（汇总）

```
候选名单
  │
  ├─ ① Squeeze Veto（§2）：SI/借券费/可借量/近期急涨
  │     └─ 任一触发 → 🚫 禁止做空（最多 flip 失守彩票单，≤0.25% 风险）
  │
  ├─ ② 熔断检查（§3）：全场正 gamma 压制或无 GEX 数据
  │     └─ 触发 → 当日零确认做空，只出决策线
  │
  ├─ ③ 量级闸门（§4.1）：DP 绝对量 + 大单参与度
  │     └─ 量薄 → 不给方向，弃
  │
  ├─ ④ 方向（§4.2）：真实逐档 DP% + 今日/1周/1月重心迁移
  │     └─ 重心上移站稳 = 吸筹 → 弃；重心走平/下移 + 滞涨 → 继续
  │
  ├─ ⑤ 动机（§5）：联合签名 → 必须命中"派发"指纹
  │     └─ 命中其余五指纹任何一个 → 弃或降权
  │
  ├─ ⑥ Dealer 对冲确认（§6）：gex-levels 结构 + flow 方向 + 次日 OI（UW/QuantData）+ 价格
  │     └─ Wall↑+Bid+OI↑（盖子）或 Wall↓+Bid+OI↓（撤保护）→ 置信度升级
  │
  └─ ⑦ 输出：仓位/意图/不对称性/失效位 + 8 层运行日志 + 各腿 as-of
```

**输出纪律：** 每个确认的做空候选必须附带证据链（六指纹选一 + 决策表命中项）、失效位（通常为 gamma flip 或 DP 重心上沿收复）、以及数据覆盖率行。任何缺少 veto 检查或熔断检查的做空结论无效。
