"""BAS-001 历史逐次 Funding 核算；禁止使用五年平均值。

输入仅支持 USD 线性合约的近似等币数数量与结算标记价。
CSV: symbol,funding_time_utc,funding_rate,mark_price.
正费率代表永续空头收取，负费率代表空头支付。

默认严格检查：持仓区间附近不能有超过 24 小时的数据空档。
这能拦截显著缺失，但不能证明每次结算完整；真实交易所可能调整间隔。
"""
import csv
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

MAX_GAP = timedelta(hours=24)


def utc(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Funding 时刻必须包含 UTC 时区")
    return dt.astimezone(timezone.utc)


def historical_funding(csv_path, symbol, start, end, quantity):
    start, end = utc(start), utc(end)
    if start >= end:
        raise ValueError("结束时间必须晚于开始时间")
    qty = Decimal(str(quantity))
    if not qty.is_finite() or qty <= 0:
        raise ValueError("quantity 必须为正有限数")
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError("历史 Funding 数据文件不存在: " + str(path))
    rows = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not {"symbol", "funding_time_utc", "funding_rate", "mark_price"} <= set(reader.fieldnames or ()):
            raise ValueError("Funding CSV 缺少必要字段")
        for r in reader:
            if r["symbol"] != symbol:
                continue
            t = utc(r["funding_time_utc"])
            try:
                rate = Decimal(r["funding_rate"])
                mark = Decimal(r["mark_price"])
            except (InvalidOperation, ValueError, TypeError):
                raise ValueError("Funding rate 或标记价格无法解析") from None
            if not rate.is_finite() or not mark.is_finite() or mark <= 0:
                raise ValueError("Funding rate 或结算标记价格无效")
            rows.append((t, rate, mark))
    rows.sort(key=lambda row: row[0])
    if len({t for t, _, _ in rows}) != len(rows):
        raise ValueError("存在重复 Funding 结算时间")
    if not rows:
        raise ValueError(f"{symbol} 没有历史 Funding 数据")
    if start < rows[0][0] - MAX_GAP or end > rows[-1][0] + MAX_GAP:
        raise ValueError("历史 Funding 未覆盖持仓时间附近；不可将缺失视为零")
    # 只检查与持仓相邻的间隔；用于拦截显著断档，而非保证结算数据完整。
    relevant = [t for t, _, _ in rows if start - MAX_GAP <= t <= end + MAX_GAP]
    if not relevant:
        raise ValueError("历史 Funding 缺少持仓附近结算点")
    if any(b - a > MAX_GAP for a, b in zip(relevant, relevant[1:])):
        raise ValueError("Funding 历史存在超过24小时的缺口，必须核对来源")
    selected = [(t, rate, mark) for t, rate, mark in rows if start < t <= end]
    funding = sum((qty * mark * rate for _, rate, mark in selected), Decimal(0))
    return {
        "funding_usd": funding,
        "funding_events": len(selected),
        "first_event": selected[0][0].isoformat() if selected else None,
        "last_event": selected[-1][0].isoformat() if selected else None,
        "coverage_checked": True,
    }
