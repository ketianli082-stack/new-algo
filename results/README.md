# 回测结果区
当前未写入可核验的回测表现。未来每次回测建议独立目录 `EXPxxx_日期_简述/`，包含：
- `config.md` 平台设置及代码 SHA
- `metrics.csv` 指标明细
- `monthly_returns.csv` 月度收益
- `fills.csv` 开平仓与逐腿成交记录
- `audit.log` 风控与订单异常记录
- `charts/` 净值、回撤、月度收益、归因

**不得把模拟的示例数值或计划中的结果写成真实回测数据。**
