# SHORT_ENGINE.md — 做空候选分析规则（v2 · 2026-09-28 重写）

> **依据**（ZZ 2026-09-28 定）：① RULEBOOK.pdf 附录「canonical RULEBOOK.md」原文（冲突时以它为准）；② Dealer Hedging Rules（§6）；③ PDF 第 1–9 节里与附录不冲突的操作细节（8 层端点、数据新鲜度、数据坑、逐层日志）；④ DP 灰色重心迁移法（ZZ 2026-09-28，§4.2 方向）。每条规则后面的〔 〕是出处。
>
> **不看 cliff**（ZZ 2026-09-28）：原文中依赖 cliff 的分量（vit/zvit、tail/tailTop/ttX、cross/clfX、floorX/putvitX、nstrk 等）一律去掉，去掉了哪些见 §10.2。
>
> **数据源**：只用 Unusual Whales REST API。原文里来自 MenthorQ / SpotGamma 的 gamma flip、call/put wall、negG，统一改用 UW `gex-levels` / `greek-exposure`〔PDF §3〕。不用 QuantData。
>
> **有歧义时以 rulebook 原文字面为准，不另加数字或解读**（ZZ 2026-09-28）。数字来自脚本，本文件只管解读〔附录〕。旧版（Fable 整理）备份在 `SHORT_ENGINE.v1-fable.md`。

---

## 0 · 框架（不可动摇）

- **不预测价格。** 找"谁在什么位置、为什么这样持仓"，输出仓位、意图、不对称性、失效位。所有概率 = risk-neutral / implied，非 alpha。〔附录·目标〕
- **DP volume 本身不是信号，只是"有事发生"的量级闸。** 方向看真实 DP% 和多时间窗价格迁移；动机靠联立证据反推（因果推断，不是分类）。永远不用自制的"重心 vs 现价偏移"代替真实 DP%，不用单一快照定方向——这正是 AXTI/NBIS 误判的根源。〔附录·DP 动机因果推断；PDF §1〕
- **Darkpool = 安全闸**：长期意图，硬闸；short 侧主力；给真实 S/R。〔附录·四层架构〕
- **解读口吻 = 顶级 quant trader**：谁在什么位置建/平仓、市场在 price 什么、这份信念是真还是机械、DP 对面是谁（吸/派/搬库存）、dealer gamma 怎么逼 flow、risk-reward 与失效位、什么 regime。禁 engineer 口吻（背字段定义、讲管道实现）。指标只是证据，话要落在 positioning / 意图 / 不对称性上。〔附录·纪律 2026-06-17 Olivia〕

---

## 1 · 数据层与新鲜度

### 1.1 8 层 → UW REST〔PDF §3〕

| 角色 | 层 | UW 端点 | 关键字段 |
|---|---|---|---|
| Trigger | DP 方向 | `darkpool-levels` | 逐档 DP%（dark vs regular） |
| Safety | DP 大单 | `darkpool` | 大宗成交的时间/规模 |
| Flow | 期权意图 | `option-trades` | side（ask/bid）、premium、sweep |
| Ready | GEX 墙 | `gex-levels` | gamma_flip / magnet / call_wall / put_wall |
| Ready | 做市商 gamma | `greek-exposure` | 一年期序列；今天 = `max(date)` 行 |
| Veto | 空头持仓 | `short-interest` | si_float、days_to_cover、fee_rate、shares_available |
| Veto | 空头成交比 | `short-volume` | short_volume_ratio（payload 键是 `si`） |
| Veto | 借券 | `short-data` | 实时借券费率 + 可借股数 |

8 层全部可经 REST 运行——失败就是真实故障（空 payload / API 错误），永远不是"该层不可用"。〔PDF §3〕

**DP% 原语：** 每个价位 `pct = dark_pool_volume / (dark_pool_volume + regular_volume)`。这才是真实逐档 DP%，不许用代理值替代。〔PDF §3〕

### 1.2 新鲜度（每条腿标 as-of）〔PDF §4〕

| 层 | 节奏 | 典型滞后 |
|---|---|---|
| `darkpool-levels` / `darkpool` | 实时（约 15 分钟延迟） | 当日 |
| `option-trades` | 盘中实时 | 当日 |
| `gex-levels` / `greek-exposure` | 实时；序列一年期 | 当日（取 `max(date)`） |
| `short-interest` | FINRA 双月结算 | 约 2–4 周，只能等披露 |
| `short-volume` | T+1 | 前一交易日 |
| `short-data` | 实时 | 当日 |

SI 只能等 FINRA 披露，没有更新的源（ZZ 2026-09-28）：照用，但必须标 as-of 和滞后天数。

### 1.3 输入新鲜度闸〔附录·纪律 2026-07-10，只保留 UW 层部分〕

动笔前逐层核对 as-of == 目标 session。任何一层不符 → 报告头部大字标"⚠ <层> = T-1（asof YYYYMMDD）"，该层结论全部降为观察；禁止不标注就照常使用。UW 变慢时宁可标缺，不可装新。

---

## 2 · 🧨 挤仓否决（squeeze-watch）〔附录 2026-07-14，AEHR +37% 教训〕

**判定：以下三条同时成立 → 标 🧨**（原文第一条"vit/zvit 板内前列"属 cliff，已去掉）：

1. SI ≥ 10% float，**或** 场外空头成交比（SVR）≥ 55% 连日；
2. DTC ≤ 2，**或** DTC 逐期上升：最近三期 FINRA 结算的 DTC 一期比一期高，说明空头越来越挤（ZZ 2026-09-28；例：NBIS 8/14 2.02 → 8/31 2.31 → 9/15 3.6）；
3. |spot − gamma flip| ≤ 3%。

**🧨 名字：**
- **做空绝对禁止。** squeeze 的买家是被迫回补 + dealer gamma，暗池里永远提前看不到；SI 高位读数在此类名字上是**燃料不是卖压**，别读反。
- 只发 **flip 收复触发位** + defined-risk lottery 纪律：**flip 上方一档 call**，风险 ≤ 0.25%，穿 flip > 1 ATR 不追。（这是顺着挤仓做多的彩票，不是做空。）

**相位闸**〔附录 2026-07-15，AEHR 二次教训〕：squeeze 票的 SI/SVR **单日 −10pt 及以上** = 回补 climax 尾段签名，不是 ignition → 🧨 机械降级"已点火偏晚"，禁追高（07-15 AEHR 单日 SI −18pt，看多次日 −5%）。借券费 / 可借余量骤降同向确认燃料退潮。（原文"ttX>1 外推同读偏晚"属 cliff，已去掉。）

**挤压反噬闸**〔附录 2026-08-12，DELL +8.2% 教训〕：SI/SVR ≥ 50% 的名字，任何派发/空头读数必须显式标"**挤压反噬风险**"；干净单票派发梯挡不住板块级轧空 beta——确认空头还需大盘/板块**不在轧空相位**（板块当日普涨/逼空迹象 = veto）。

**不满足 🧨 的名字：** 附录没有单独的"刚急涨"否决（PDF 第 7 节英文摘要写的"SI 高或借券紧或刚急涨即禁空"与附录冲突，以附录为准）。冲高后、SI 高、借券紧的名字照常走 §9 流水线，但要过相位闸、挤压反噬闸；凡需要挂"拥挤/燃料/相位可疑"类 caveat 的，按 §8.2 整行降出确认表。

---

## 3 · 空头引擎熔断〔附录 2026-08-13，轧空周 DELL/META/DDOG 0/3 教训〕

- 当日 dealer gamma 面若为**全场 pin**（名单内负 gamma 票数 ≤ 4〔原文 ≤4/35〕，或等效证据显示名单内绝大多数正 gamma）→ **空头引擎熔断**：一切派发读数只挂 flip / 判决线（"破 X 前不是 setup"），不给确认空头入场位。
- 正 gamma 毯下，派发梯会被 dealer 高抛低吸直接碾穿。
- 当日无 GEX 数据 → 默认熔断（宁保守）。
- "全场 / 板内" = **ZZ 给的票的列表**（`uw_short_fetch/uwsf/watchlist.py`，现为 23 只，含 SLV）。原文的 MQ 批次 35 只就是这份名单（ZZ 2026-09-28）。**不是板块**，也不单独给 ETF 另设池子。门槛照原文数字：负 gamma ≤ 4 只（名单现为 23 只）。

---

## 4 · 读取顺序：量级 → 方向 → 动机（硬顺序，不跳步）〔PDF §5；附录〕

### 4.1 量级闸

- 绝对 DP 量 = 信心，**永远不定方向**。
- 大单参与度 16–21% = 机构意图（可信）；3–4% = 散户噪音（降权）。
- 量薄 → 不强行给方向。

### 4.2 方向：DP 灰色重心迁移法 + 价格 acceptance〔DP 灰色重心迁移法，ZZ 2026-09-28；附录·多时间窗价格行为〕

**核心原则**：不看某一根 grey bar 是买还是卖，而是比较长 / 中 / 短周期的 DP 成交重心是**上移、下移还是停滞**。DP volume-at-price 本身不提供买卖方向；"吸筹 / 派发"来自**重心迁移 + 后续价格行为**的联合判断。**重心迁移给方向偏置；价格 acceptance / failed acceptance 给最终确认。**

**周期**：长 = 1M（原文配 1H K 线）· 中 = 1W（15m）· 短 = 2D（5m）。
数据对应：`darkpool_levels.windows` 的 1M / 1W / 2D；"重心" = `centroid_top8`（灰色集中区的加权中心），`dark_vwap_all` 作参考；dominant grey node = `poc`。K 线：1M 用日线，1W / 2D 用 5 分钟线（近 5 日）；1H 线目前没有。

**阅读流程（按顺序）**：
1. **Long**：先找长期 dominant grey node / value area——历史主要库存在哪里？
2. **Medium**：最近一周的重心相对长期是上移、下移还是横移？
3. **Short**：最近两天是否继续同方向迁移？
4. **Price**：比较 spot 与最新 DP 重心——价格是否跑在 inventory 前面？
5. **Retest**：第一次重要回踩是否 defend DP core？这是最有价值的确认。
6. **Cross-check**：再和 GEX / DEX（`greek_exposure` 的 net_gamma / net_delta 序列、`gex_levels`）一起看——衍生品结构是否得到 DP inventory 迁移确认？

**价格负责裁决 DP 的意义**（读 DP 带上的 K 线 price action，不读名义额）：
- **健康 acceptance**：到达 DP node → 停留 → 回踩守住 → 再向上离开。旧 inventory 被 defend，新 value 被接受。
- **失败 / trapped inventory**：冲到高位 DP 区 → 无法站稳 → 跌回旧 DP core → 再失守。高价 inventory 没有得到市场确认。

**三种状态**：
- **吸筹确认**：Long < Medium < Short 重心逐级上移 + 价格接受新高位（能站在新的高位 DP 区附近或上方）。含义：市场愿意在越来越高的价格完成大量换手。→ **不是做空候选**。
- **派发确认**：Long > Medium > Short 重心逐级下移（尤其发生在一段上涨之后，说明最新 inventory 越来越在低价区重新成交）+ 高位失守。
- **Trap warning（DP non-confirmation）**：Price ↑↑ 但中 / 短周期 DP 重心 →（没有同步向高位迁移）。价格跑在 inventory 前面，上涨缺少 equity-inventory confirmation。**这不是已经确认的派发**，等 retest 裁决：
  - 跌回并失守共同 DP core、没有吸收和 reclaim → 升级为 **confirmed trap**（高价持仓被套 / regime failure），按派发确认处理；
  - 回踩守住 DP core 并再向上离开 → 健康 acceptance，trap warning 解除。

**案例（COHR）**：8/17 价格约 325→360，但中 / 短周期 DP 主重心仍停在 325–334，没有同步迁到 350–360；同时 GEX rebuild、DEX 快速扩张 → 标 bullish markup with DP non-confirmation（trap warning，不是已确认派发）。8/18 价格直接回到并跌穿 325–334 共同 DP core；健康的吸筹本应看到吸收、reclaim 330、再回 340，实际没有 → 升级为 confirmed regime failure / trapped high-price positioning。

**一句话**：DP 不是看"哪里有大单"，而是看"成交重心如何随时间迁移，以及价格是否接受这个新重心"。

补充（附录）：只在单一窗口冒尖、其它窗口无延续 = rebalance / noise；停滞本身就是早于下迁的派发信号；两个快照 ≠ 价格行为，必须真拉价格路径。`windows` 里的 1D / 3D 可作参考。

### 4.3 动机

联合签名因果推断：从 §5.2 六指纹里选一个，报证据链。**不许只贴"吸/派"二分标签**——同一笔 DP 大单，动机不同，交易方向相反。〔附录 2026-06-17 Olivia〕

---

## 5 · 动机：判别关节、六指纹、IV×RV regime

### 5.1 判别关节（缺一不能定性）〔附录 2026-06-17 Olivia〕

- **OI vs 成交量**：option volume > OI = 新建仓（有信念）；volume < OI = 平仓/移仓（无信念）。
- **flow-IV 方向**：看今日新成交 prints 的 IV 相对前几日是否抬升（尤其 ask-side / lifted 那部分，premium 加权做日对日）。抬 = 买方愿意出更高的钱 = 真需求、信念在加注；平/降 = 没人加注 = 机械流。IV30 从压缩低位 expand 是更慢的确认层，不是当日 tell。
- **DP 时点**：盘后 / 大宗 block + 期权建仓 = 库存转移；月末/季末价不敏感、沿 VWAP 摊 = rebalance；贴 gamma wall = hedge。
- **大单%**：16–21% = 机构意图；3–4% = 散户噪音，降权。

（原文"tail + vit 同时扩张 = DP 背后有投机想象 / DP 大但 vit≈0 = 机械"属 cliff，已去掉。）

### 5.2 六指纹〔附录 2026-06-17 Olivia，两处写法合并；已去掉 vit / tail / tailTop 分量〕

- **派发 Distribution → bear（唯一可做空的指纹）**：DP 大量、DP% 高，但价位不上迁（平/下）；价顶不动或在其下停滞；block 后价继续淌、梯子重建在更低位、头顶供给；call 写在 bid；call OI 平/降 或 put OI↑；IV 平/压缩。→ 借强出货，变成上方阻力。
- **吸货 Accumulation → bull**：DP 重心在 spot 处/下方；DP% 价位多窗口上迁（梯子 1d/3d/1w 上移）；价站上每级；call OI↑；IV30 从低位 expand。→ 有人低位建仓等 markup。**不是做空候选。**
- **库存转移 Inventory transfer → 中性偏多**：盘后大额 DP（常单笔 / block）+ call OI↑ + IV↑ + option volume > OI（新仓）。→ dealer/MM 为配合大额期权单做的对盘/转库存，不是供给砸盘。**判别：期权账本在同步扩张——派发不会和 call OI + IV 同步扩张共存。**
- **Gamma hedge → 无方向**：DP/print 量跟随 dealer gamma——簇在 gamma wall/flip，spot 穿关键位时爆量，机械、双向、围绕墙均值回归，DP% 无持续迁移，OI 无信念，IV 不从意图扩。UW gex-levels 的位对齐 = tell。非方向意图，别当信念。
- **对冲 Hedge → 方向降权**：DP **配对反向期权**（call 买 + DP 卖 / 领口），**净 delta ≈ 平、两侧 OI 都增、IV 闷**。→ 在对冲敞口，不是方向押注。
  - 只有满足上面这几条才算对冲。原文另一条"护盘"（DP block + put OI↑ / 保护结构 + IV↑ 但价不破位）已按 ZZ 2026-09-28 删去：put OI↑ + IV↑ + 价格没破位，不再算对冲。
  - 判定对冲前，先按 §7.3 把 flow 结构拆开（单腿还是多腿、side、vol vs OI、sweep/重复、到期）。
- **Fund rebalance → 机械，降权**：月末/季末/指数重构日的大 DP，价不敏感、沿 VWAP 摊全天，篮子型（同日多只相关名字），无期权确认（OI/IV 平），DP% 仅单窗口冒尖、无多窗口迁移，事件后价均值回归。→ 非 informed，别读成意图。

### 5.3 IV × RV × 价格 regime〔附录 2026-07-21 Olivia，WDC 案例〕

IV30 与 RV（HV20）必须连价格一起读，判定用整段轨迹，不用单日快照：

- **RV > IV 且在高位 / RV、价齐涨 + IV 高位向上 = 空头行情**（除非巨大利好）。WDC 6/25 顶部（~745）即此形态 → 需要做空。
- **顶部机制**：一轮上涨后 IV 超高 → IV 拐头向下 + RV 拐头向上 = buy OTM call 的力量用尽，临近到期持仓者集体转 sell call → vol 供给压顶 + dealer 反向 = RV > IV 高位空头行情。**IV 下拐 / RV 上穿的交叉点就是 call 买盘枯竭的标记。**
- 空头行情之后 IV 翻上 RV = bounce 相位，不是新趋势（WDC 7/16–21 的反弹）。
- IV > RV 期间两线再次相交 = 价格回归信号。
- IV > RV 且 IV 在高位 = vol 终将回归，别按趋势读。
- RV > IV 但 IV 在低位 = 多数是多头行情；IV 低位向上走 + RV > IV 但回落中 = 多头单腿 call 行情。→ 这两种不做空。

---

## 6 · Dealer 对冲确认（Dealer Hedging Rules）〔DHR 原文：Dealer_Hedging_Rules_Full_Guide.pdf〕

原文用 MenthorQ（结构）+ Unusual Whales（flow）+ OptionData（次日 OI）+ 价格。按"只用 UW"，本版把结构换成 UW `gex-levels`，次日 OI 换成 UW `oi-change`，其余照原文。

**核心原则**：结构位回答"结构性风险在哪"；UW 回答"今天谁在主动交易"；次日 OI 回答"持仓是否真的变了"；价格回答"定位是否被确认"。**永远不只用一个工具。**

### 6.1 四步法

1. **结构**（原文 MenthorQ → UW `gex-levels`）：只观察 Call Wall / Put Wall / Gamma Flip / Dealer Pivot。Call Wall 从 360 移到 365，只能得出"风险中心从 360 移到 365"，**不许**推断 dealer 挪仓或客户看多。（UW 没有 Dealer Pivot 字段，这一项标"缺失"。）
2. **Flow**（UW `option-trades`）：看 ask/bid、sweep、premium、volume vs OI。同一时段 360 bid + 365 ask 常提示 roll；**重复的 ask sweep** 提示激进买入。
3. **次日 OI 确认**（原文 OptionData → UW `oi-change`）：360 OI 降了吗？365 OI 升了吗？只有确认后，才知道昨天的交易变成了新持仓。
4. **推断 dealer 对冲方向**（见 6.2）。

### 6.2 四种情形（决策表）

| 信号组合 | 客户（可能） | Dealer | Dealer 对股票（通常） |
|---|---|---|---|
| Wall↑ + Ask + OI↑ | Buy to Open | Sell to Open | **买**股票对冲 |
| Wall↑ + Bid + OI↑ | Sell to Open（备兑 / 熊市 call 价差） | Buy to Open | **卖**股票 |
| Wall↓ + Bid + OI↓ | Sell to Close | Buy to Close | **卖**股票（对冲移除） |
| Wall↓ + Ask + OI↓ | Buy to Close | Sell to Close | **买**股票 |

**重要事实**：OI 单独永远不能判断 dealer 在买还是卖股票。OI 增可来自客户 Buy to Open 或 Sell to Open；OI 减可来自客户 Sell to Close 或 Buy to Close。所以 OI 本身永远不够。

**置信度**：四点全部一致时置信度最高——① 结构 ② UW flow ③ 次日 OI 确认 ④ 价格行为。不依赖任何单一信号。


---

## 7 · Flow 纪律与数据坑

1. **期权 flow 的 strike 在本账户上编码错位（约 33×）——永远不用期权 flow 画 strike 位 / 写墙。** 现价取 DP 的 NBBO 中点，不用 `underlying_price`（同样不可靠）。〔PDF §8〕
2. **按意图净额，不按 call/put 计数。** "calls > puts"是陷阱：ask 侧 = 买入（lifted），bid 侧 = 卖出（written）。**大额 call premium 打在 bid 上 = 写 call = 盖子，不是点火。**〔PDF §8〕
3. **读 flow 要拆开**〔附录 2026-06-17 Olivia〕：结构（单腿 naked vs spread/collar/roll/risk-reversal——**多腿往往是对冲/调仓，不是方向押注**）、side（ask = 买 vs bid = 卖）、dealer 对冲 vs 真押注、IV/skew context（flow-IV 抬 = 付溢价）、vol vs OI（> OI = 新建仓）、**sweep / 重复 = 急迫度**、到期。缺这些拆解就喊多空 = 50% 抛硬币。
4. **UW 期权流永不单独发起方向**〔附录 2026-06-17 Olivia〕：只在与 DP% 方向 + SI/借券燃料同向时加一格置信；不同向 → 标 conflict，不下注。主信号永远 = DP 方向 + SI 燃料，flow 只佐证。
5. DP 约延迟 15 分钟（盘中结构够用）。〔PDF §8〕
6. `greek-exposure` 返回一年期序列——今天取 `date == 目标日` 的行（`max(date)`），绝不取第一行。〔PDF §8〕
7. `short-volume` payload 键是 `si` 不是 `data`；`gex-levels` payload 是嵌套字典 `data={date,time,…}`。〔PDF §8〕
8. SI / short-volume / short-data 各行按降序排列——取 `max(date)`，不是最后一行。〔PDF §8〕

---

## 8 · 输出纪律

### 8.1 严谨闸〔附录 2026-06-17 Olivia〕

- 每条腿标 **as-of + [已验证 / 假设 / 缺失]**。
- 因果判断所需的腿必须全部 = 已验证，否则**只报状态、不下结论**（别一边"定不了"一边下判）。
- stale / T+2 / 两个快照 ≠ 价格行为；多窗必须真拉价格路径 + DP K 线。
- 字段 / schema 没亲眼 fetch 到，不写进结论。

### 8.2 确认空头表的硬规则〔附录〕

- **财报**：每只确认票标"财报 MM-DD"或"财报未查"。已知 7 个自然日内有财报，或"未查 + THIN" → 弃权。
- **THIN 链**（nstrk < 45）永不进确认空头表，上限 = 观察行；挂 ⚠THIN 旗保留行位也不行，必须物理不入表。（2026-07-29 TEVA +9.6% 教训。nstrk = 当日有效合约——volume>0、双边 NBBO 有效——在所有到期日里的不同 strike 数〔附录 2026-09-01 链口径；到期日范围原文未写，暂取全链，待 ZZ 确认〕）
- **caveat 反向 = 机械降 tier**（07-17 档案条款升级为硬规）：凡文字里给某票挂"拥挤 / 燃料 / 相位可疑 / 降半档"类 caveat，该票必须整行降出确认表，禁止"降半档但保留行位"。
- 报动机 + 证据链（因果），不要只丢"吸/派"二分标签。

### 8.3 逐层运行日志〔PDF §9，Olivia 的可靠性要求〕

每一批分析必须输出哪些规则层真正跑了、哪些失败，避免把部分运行误当成完整交叉验证：

- 每层 `✅ RAN {layer} as-of <date> rows=N` 或 `❌ FAIL {layer} reason: <具体原因>`；
- 覆盖率一行 `N/8`，贴到看板；
- FAIL 是真实故障（空 payload / API 错误），永远不是"该层不可用"；
- 每条腿标各自的 as-of（尤其 SI 的滞后）。

### 8.4 格式〔附录·纪律〕

Discord 不渲染 markdown 表格，表格一律放 ``` 代码块；诚实标 as-of。

---

## 9 · 做空候选完整流水线

```
候选名单
  │
  ├─ ⓪ 输入新鲜度闸（§1.3）：每层 as-of == 目标 session，否则头部标 ⚠、该层降为观察
  │
  ├─ ① 🧨 挤仓否决（§2）：SI≥10% 或 SVR≥55% 连日 + DTC≤2 或 DTC 近三期逐期上升 + |spot−flip|≤3%
  │     └─ 🧨 → 做空绝对禁止；只发 flip 收复位 + call 彩票纪律；相位闸（SI/SVR 单日 −10pt）→ 降级偏晚
  │
  ├─ ② 熔断（§3）：名单负 gamma ≤4 只或名单内绝大多数正 gamma，或当日无 GEX 数据
  │     └─ 触发 → 零确认空头，只出判决线
  │
  ├─ ③ 量级闸（§4.1）：DP 绝对量 + 大单参与度
  │     └─ 量薄 → 不给方向
  │
  ├─ ④ 方向（§4.2 灰色重心迁移法）：1M → 1W → 2D 重心迁移 + 价格 acceptance / retest + GEX/DEX 交叉
  │     └─ 吸筹确认 → 弃；派发确认或 confirmed trap → 继续；
  │        Trap warning 未裁决 → 只出判决线（retest 的 DP core），不下做空结论；横移 / 不一致 → 不明
  │
  ├─ ⑤ 动机（§5）：判别关节 + 六指纹 + IV×RV regime；flow 按 §7.3 拆结构
  │     └─ 必须命中"派发"；命中其余指纹 → 弃或降权
  │
  ├─ ⑥ Dealer 确认（§6）：gex-levels 结构 + flow + 次日 OI + 价格 → 推断 dealer 买/卖股票
  │     └─ 四点一致 = 最高置信度；不依赖任何单一信号
  │
  └─ ⑦ 输出（§8）：挤压反噬闸（SI/SVR≥50% 标风险；板块轧空相位 = veto）；
        财报 7 天 / THIN / caveat 降级；仓位/意图/不对称性/失效位 + 证据链；
        逐层日志 + 各腿 as-of 与 [已验证/假设/缺失]
```

**任何缺少 🧨 检查或熔断检查的做空结论无效。**

---

## 10 · 变更说明

### 10.1 相对旧版（Fable 版）的主要改动

- 挤仓否决：旧版"SI 高 / 借券紧 / 刚急涨"三选一、无数字 → 🧨 三条同时成立（附录四条去掉 vit/zvit）；不再有单独的"刚急涨"否决。
- 🧨 彩票：旧版"flip 收复失败后做空" → 附录原文"flip 上方一档 call"。
- 熔断：旧版"板块内 ≤4/35" → ZZ 的票列表（全场）。
- 新增：相位闸、挤压反噬闸、逐价位 K 线读法（后并入 §4.2 灰色重心迁移法）、hedge/basis 定义、flow 拆结构、flow-IV、IV×RV regime、输入新鲜度闸、严谨闸、财报 7 天、THIN、caveat 降级。
- 对冲只保留 hedge/basis 定义（要配对反向头寸、净 delta ≈ 平、两侧 OI 都增、IV 闷）；原文"护盘"一条按 ZZ 2026-09-28 删去。
- 🧨 的 DTC 条件加上趋势（ZZ 2026-09-28）：DTC ≤ 2，或最近三期逐期上升（越来越挤）。原文只有 DTC ≤ 2，会把越来越拥挤的名字（NBIS 9/15 DTC 3.6）排除在外。
- §4.2 方向改用 DP 灰色重心迁移法（ZZ 2026-09-28）：长 1M / 中 1W / 短 2D 的重心迁移给方向偏置，价格 acceptance / retest 给最终确认，再和 GEX / DEX 交叉；新增 Trap warning 状态（价格跑在 inventory 前面，等 retest 裁决）。附录的"当日 / 3 日 / 1 周 / 1 月四窗"改为此三档。
- 删除 QuantData；次日 OI 只用 UW `oi-change`。
- §6 按 DHR 原文核对后改回：去掉旧版自加的"做空含义"一列（"看空确认：上方形成盖子""上方支撑撤除，偏空""不利于做空"）和"盖子/撤保护 → 置信度升级""缺任何一点都降级"；补回漏掉的 Dealer Pivot。

### 10.2 按"不看 cliff"去掉的附录条款

- 🧨 的"vit/zvit 板内前列"；相位闸里的"ttX>1 外推同读偏晚"。
- 指纹里的 tail / vit / tailTop 分量；判别关节"tail + vit"。
- 空头书（put_rank）：受阻（cross/clfX）、put 端 ≥2 项确认（floorX < 0.97 / putvitX > 1.1 / floor-spot 贴近 > 0.8）、floor 在升不空、put-vit 极值 + 刚暴跌 = 逼空燃料、薄链 pvitX 财报前读 hedging、低价票 fl/spot 打折。
- Call Holder Trap（2026-08-18）：第一触发腿是 cliff 的 put/call 两侧同时加仓，整段暂不启用。

### 10.3 已定（ZZ 2026-09-28：以 rulebook 为准）

1. 熔断名单 = ZZ 给的票列表（`uwsf/watchlist.py`）；门槛照原文数字，负 gamma ≤ 4 只。
2. 挤压反噬闸照原文：SI/SVR ≥ 50%。
3. "板块轧空相位"照原文定性判断（板块当日普涨 / 逼空迹象），不另设数字。
4. 🧨 照原文：只发 flip 收复触发位 + call 彩票纪律。
5. Call Holder Trap 的触发腿是 cliff，不启用。
6. "高 DP 量价位"照原文，不另设档数。
7. THIN 的 nstrk 按附录链口径数；原文没写按哪个到期日，暂取全链（所有到期日的不同 strike；只数最近月度会把 IBM 这类流动性好的票也判成 THIN），待确认。
8. 挤仓否决照附录 🧨 执行；PDF §4"以借券费 + SVR 为主、SI 降为背景"的提议附录里没有，不采用。
9. 大单参与度照原文 16–21% / 3–4%。
10. §6 只写 DHR 原文内容，不加"对做空的含义"；Dealer Pivot 照原文列出，UW 无此字段，标"缺失"。
11. 结构位（flip / wall）用 UW `gex-levels`〔PDF §3〕。
