# R5-F05 Annualized Funding 验收（2026-11-24）

来源：[R5-F05 run 45351691951](https://github.com/ketianli082-stack/new-algo/actions/runs/45351691951)，artifact 14900564010，head ee0b5da51472565c9932803ed964e9e16b7d08c1。已解压核对 platform-responses.json 与 trade_statistics.json，COLLECTED，无错误。R5 与 R5-F02 对照亦来自各自原始 ZIP。

## 验收
- R5-F01 校准研究支持年化输入/365、每日融资记账；R5-F05 使用注册名称 BINANCE_BTCUSDT_USDM_FUNDING_DAILY_APPROX_ANNUALIZED、BINANCE_ETHUSDT_USDM_FUNDING_DAILY_APPROX_ANNUALIZED。
- R5/F02/F05 native TotalPnL: 2394304.353887 / 2394323.211543 / 2401127.857327 USD；Sharpe 6.801290 / 6.801314 / 6.808793；F05 Score 86.2190673，最大回撤比例 0.0140200332，1694 fills。
- F05 年末 UTC 2025-12-31 23:00 snapshot (final_callback=false) native financing=3388.39 USD，NAV 3403456.356139；原 trade statistics funding=null 是历史字段，新增 funding_native_fields.financing 有真实值。相较 R5 native PnL +6823.50 并不等于 funding；动态仓位影响价格 PnL。
- F05 423 已平仓（391 净盈利/32 亏损），平均 3.07565h，最长245h；一对 ETH 未平仓，浮动 PnL 2726.35；配对等待173h；最大已平仓净损失18590.53。mean/peak reserved gross NAV 1.75765%/50.95309%。
- 已平仓价格毛利润2397400.88，手续费315344.96，滑点63068.99，净2018986.93（不含资金费率）。全成交名义金额632050231.99，估算手续费316025.12、滑点63205.02。
- 年末快照 NAV 减全部已执行交易估算成本 =3024226.22，收益202.4226%；保守7bp=2961021.19，收益196.1021%。不要再加 Financing。native TotalPnL 与年末快照并非同一时点，不混算。已平仓净收益与含未平仓估值的账户口径分别报告；未含未来平仓成本。历史毛 NAV 驱动仓位，事后估算成本非内生复利。
- Funding 验收：已验证平台存在真实融资字段；可作为日频代理研究工作基准，保留无 Funding R5 对照。不是精确8h结算；同日合计费率在平台日初记账可能造成前视时点偏差，币种采用 Binance 代理，未完成跨日对齐与 ETH 独立校准，不宣称精确费率现金流或严格无前视。报告优先，不继续追加 Funding 实验。
