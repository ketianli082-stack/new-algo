# Binance USD-M Funding 数据（ALGOGENE）

本目录保存 BTCUSDT、ETHUSDT 从 2021-01-01 至 2026-11-24 最新已结算记录（UTC）。每个品种 6,460 条，重复时间键为 0，超过 8 小时的内部缺口为 0；2026-10 数据已与 Binance Vision 官方月度归档逐行核对，时间与费率完全一致。

## 文件

- `BTCUSDT_binance_usdm_funding_raw.csv`、`ETHUSDT_binance_usdm_funding_raw.csv`：逐次真实结算记录，保留原始结算时间、费率、标记价格和 `rate_type`。
- `BTCUSDT_algogene_funding_daily_approx.csv`、`ETHUSDT_algogene_funding_daily_approx.csv`：按 UTC 日期汇总的 ALGOGENE 日频近似曲线。正 Binance 费率转换为 `Long=-日内费率合计`、`Short=+日内费率合计`。
- `_meta_.json`：ALGOGENE Funding 曲线注册配置。
- `funding_validation.json`：覆盖、重复、缺口、文件哈希及官方归档交叉校验报告。

## 重要说明

ALGOGENE 官方示例按日计算融资费用，因此 `*_daily_approx.csv` 是日频近似，不能称为精确的 8 小时 Funding 结算。需要精确结算时间时，应使用 `*_raw.csv`。Binance BTCUSDT/ETHUSDT 也是研究代理数据，不应表述为 ALGOGENE 原生费率。

本目录不修改 R5 基线，不包含回测结果，也不会触发实盘交易。
