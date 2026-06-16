# 交易规则与公共费率来源审计（2026-06-16）

## 结论

当前 `rules_v1.yaml` 覆盖的沪深主板股票与主板 ST 规则已完成 source audit：

- 结构规则：主板股票 `tick=0.01`、买入 `100` 股整数倍、单笔申报上限 `1,000,000`、T+1、普通主板涨跌幅 `10%`、风险警示 `5%` 维持 `verified`。
- 公共费率：印花税 `0.0005`、股票交易过户费 `0.00001`、A 股交易经手费 `0.0000341` 标为 `verified`。
- 券商佣金：不属于公开交易所/登记结算规则，继续 `value: null`，置信标记为 `broker_configured`。实盘费用以券商配置、成交回报和盘后对账为准。
- `require_verified=True` 仍会阻断任何 `provisional` 规则或费用项；本次只移除已完成来源审计的公共费用阻断。

## 来源

| 项 | 当前值 | 来源与状态 |
|---|---:|---|
| 主板结构规则 | `tick=0.01`、`min_buy=100`、`max_order=1000000` | [上交所 2023 现行有效交易规则页](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20250612_10781695.shtml) / [深交所交易规则页](https://www.szse.cn/lawrules/rule/trade/)，`verified` |
| 印花税 | `0.0005`，卖方收取 | [财政部、税务总局关于减半征收证券交易印花税的公告](https://guizhou.chinatax.gov.cn/wjjb/zcfgk/szfl/yhs/202308/t20230828_82084744.html)，2023-08-28 起实施，`verified` |
| 过户费 | `0.00001`，双边 | [新华社转中国结算通知](https://www.news.cn/fortune/2022-04/28/c_1128605983.htm)，2022-04-29 起统一下调为成交金额 `0.01‰` 双向收取，`verified` |
| 经手费 | `0.0000341` | [证监会降费安排](https://www.csrc.gov.cn/csrc/c100028/c7426794/content.shtml)，沪深交易所 A 股、B 股证券交易经手费 2023-08-28 起下调为成交金额 `0.00341%` 双向收取，`verified` |
| 券商佣金 | `null` | 券商协议/账户配置项，非公共规则，`broker_configured` |

## 工程处理

- `quant/providers/data/rules_v1.yaml` 中三条种子规则的公共费用改为 `verified`，佣金改为 `broker_configured`。
- `TradingRuleProvider.rules_for(..., require_verified=True)` 的语义保持不变：仅当规则级非 `verified` 或任一费用项为 `provisional` 时阻断。
- 回测摩擦模型可继续读取公共费率；真实交易成本仍需要用券商回报和盘后对账校准。

## 剩余边界

- 科创板、创业板、北交所、ETF、可转债、B 股仍不进入当前实盘范围。
- 新股上市前 5 日无涨跌幅、集合竞价不可撤单窗口、退市整理等更细规则没有纳入当前主板种子，应在扩展对应交易策略前单独补 fixture 和 source audit。
- 2026-07-06 生效的交易所规则修订尚未切入当前 `effective_from=2020-01-01` 规则；如启用新规差异，必须新增带生效区间的新规则行，不能覆盖历史规则。
