# V8 research：使用 GitHub Actions 提交 ALGOGENE 回测

## 入口
[GitHub Actions — V8 research ALGOGENE 2025 基准回测](https://github.com/ketianli082-stack/new-algo/actions/workflows/v81-2021-2025.yml)

## Actions Secrets
仅在仓库 Settings → Secrets and variables → Actions 设置：
- `ALGOGENE_USER_ID`
- `ALGOGENE_API_KEY`

两个值不应出现在公开仓库代码、GitHub issue、提交信息或聊天中。工作流会通过环境变量安全读取，不输出 Secrets。

## 运行方式
工作流首次被提交到 `main` 时，配置了仅针对工作流文件的 `push` 触发，目标是自动运行一次 **2025** 基准。也支持在 Actions 页选择 **Run workflow**，指定：
- `2025`（优先验证）
- `2023-2025`
- `2021-2025`

**在确认首轮真实执行状态之前，不要重复点击 Run workflow。** ALGOGENE 同一账户可能已有活动任务；若提交响应不明确，严禁盲目再次提交。

## 已固定的真实平台参数
```text
subscribeList = BTCUSD, BTCUSDM, ETHUSD, ETHUSDM
dataset = 60
InitialCapital = 1000000 USD
Leverage = 1
allowShortSell = True
isPositionBaseEnv = False
risk_free = 0
# 不向 ALGOGENE 传入固定金额成本字段；百分比手续费在离线模型核算
```
策略源码：`strategy/crypto_basis_v8_1.py`，未改交易逻辑。

## 提交流程
1. `python -m compileall -q strategy tools tests`，运行离线测试。
2. `GET /get_current_tasks` 检查 ALGOGENE 是否无未完成任务。
3. `GET /meta_instrument` 对四种标的核对 `contractSize=1`。
4. 单次 `POST /run_backtest`，不重试不确定提交，记录 runtime_id 与 task_id。
5. `GET /task_status` 轮询；完成后尝试查询 `strategy_stats`、`strategy_logs`、`strategy_trade`、`strategy_pl`。
6. 无论成功失败，上传 `outputs/v81/` 为 GitHub Actions Artifact（90 天）。
7. **只提交回测，不调用实盘订单 API。**

## 成本与 Funding 的特别说明
V8 research 的百分比手续费与滑点、BTC/ETH 年度平均 Funding 目前仅为离线分析方案。平台回测不传入固定金额手续费参数，`risk_free=0` 仅用于基准复现；这不是完整成本后的净收益。后续要基于真实订单和有来源的年度费率计算两套收益，并核对平台是否重复计费。

## 如何判断成功
请查看对应 Action 的状态和 Artifact 中的 `platform-responses.json`：
- `SUBMITTED`：平台接受任务，但尚无完成保证。
- `TASK_DONE`：平台任务完成，后续结果待拉取。
- `COLLECTED`：请求返回且完成数据收集，不保证经济收益为正。
- `PENDING`：超出等待窗口，需查询原 task_id，不能再提交新任务。
- `ERROR` / `SUBMISSION_UNCERTAIN`：需核对异常、现有任务或平台历史，不能盲目重试。

## 注意
若 Secrets 不属于 `new-algo` 而仅设置在旧仓库，本 Action 无法读到。两仓库的 Actions Secrets 不是自动共享的。
