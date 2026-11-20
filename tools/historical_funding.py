"""BAS-001：按真实历史结算时点逐条计入 Funding；不使用历史平均数。

CSV: symbol,funding_time_utc,funding_rate,mark_price
funding_rate 是小数（0.0001 = 0.01%），mark_price 为结算时标记价格（USD）。
仅支持等币数、USD 线性合约；币本位/反向合约需转换后使用。
"""
import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


def utc(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Funding 时刻必须包含 UTC 时区")
    return dt.astimezone(timezone.utc)


def historical_funding(csv_path, symbol, start, end, quantity):
    """仅统计 start < settlement <= end，表示开仓时之后、平仓时及之前的结算。
    如成交恰好处于结算秒，先后顺序需由真实成交/结算数据确定。
    """
    start, end = utc(start), utc(end)
    if start >= end:
        raise ValueError("结束时间必须晚于开始时间")
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
            if start < t <= end:
                rate = Decimal(r["funding_rate"])
                mark = Decimal(r["mark_price"])
                if not rate.is_finite() or not mark.is_finite() or mark <= 0:
                    raise ValueError("Funding rate 或结算标记价格无效")
                rows.append((t, rate, mark))
    rows.sort()
    if len({t for t, _, _ in rows}) != len(rows):
        raise ValueError("存在重复 Funding 结算时间，拒绝重复计入")
    if not rows:
        raise ValueError("没有覆盖持仓期间的 Funding 结算记录；不可默认为 0")
    qty = Decimal(str(quantity))
    if qty <= 0:
        raise ValueError("quantity 必须大于零")
    # 永续空头在正资金费率时为正现金流
    pnl = sum((qty * mark * rate for _, rate, mark in rows), Decimal(0))
    return {"funding_usd": pnl, "funding_events": len(rows),
            "first_event": rows[0][0].isoformat(), "last_event": rows[-1][0].isoformat()}
