"""检查历史 Funding CSV 的范围、唯一性、数值和明显缺口。

这是数据完整性预检，不是对 ALGOGENE 合约匹配或每次资金费到账的证明。
"""
import argparse
import csv
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tools.historical_funding import utc


def validate(path, symbols, start, end, max_gap_hours=24):
    begin, finish = utc(start), utc(end)
    gap = timedelta(hours=max_gap_hours)
    groups = defaultdict(list)
    with Path(path).open(encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        if not {"symbol", "funding_time_utc", "funding_rate", "mark_price"} <= set(rd.fieldnames or []):
            raise ValueError("CSV 列名不完整")
        for r in rd:
            if r["symbol"] not in symbols:
                raise ValueError("出现非目标 symbol: " + r["symbol"])
            date = utc(r["funding_time_utc"])
            rate, mark = Decimal(r["funding_rate"]), Decimal(r["mark_price"])
            if not rate.is_finite() or not mark.is_finite() or mark <= 0:
                raise ValueError("结算费率/标记价格非法")
            if date < begin or date > finish:
                raise ValueError("数据超出请求的历史区间")
            groups[r["symbol"]].append(date)
    results = {}
    for symbol in symbols:
        times = sorted(groups[symbol])
        if not times:
            raise ValueError(symbol + ": 没有数据")
        if len(times) != len(set(times)):
            raise ValueError(symbol + ": 结算时间重复")
        gaps = [b - a for a, b in zip(times, times[1:])]
        if times[0] - begin > gap or finish - times[-1] > gap or any(d > gap for d in gaps):
            raise ValueError(symbol + ": 覆盖不足或间隔超过 " + str(max_gap_hours) + " 小时")
        results[symbol] = {"events": len(times), "first": times[0].isoformat(),
                           "last": times[-1].isoformat(),
                           "largest_gap_hours": max((d.total_seconds()/3600 for d in gaps), default=0)}
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv", type=Path)
    p.add_argument("--symbols", nargs="+", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--max-gap-hours", type=float, default=24)
    args = p.parse_args()
    for s, info in validate(args.csv, args.symbols, args.start, args.end, args.max_gap_hours).items():
        print(s, info)


if __name__ == "__main__":
    main()
