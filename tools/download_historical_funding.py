"""通过 Binance 公共 API 下载历史 Funding（研究代理数据）。

USDⓈ-M: https://fapi.binance.com/fapi/v1/fundingRate
本工具不假定 ALGOGENE 的 BTCUSDM/ETHUSDM 与币安产品相同。
输出 mark_price 来自 API 的 markPrice 字段，并保留原始原子时间戳。
"""
import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


def ms(s):
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("请使用带时区的 ISO 时间")
    return int(d.astimezone(timezone.utc).timestamp() * 1000)


def fetch(symbol, start, end):
    t, stop = ms(start), ms(end)
    if t >= stop:
        raise ValueError("start 必须早于 end")
    records = {}
    while t <= stop:
        params = urlencode({"symbol": symbol, "startTime": t, "endTime": stop, "limit": 1000})
        with urlopen("https://fapi.binance.com/fapi/v1/fundingRate?" + params, timeout=30) as response:
            page = json.load(response)
        if not isinstance(page, list):
            raise RuntimeError("API 返回非数组：" + str(page)[:200])
        if not page:
            break
        for x in page:
            tick = int(x["fundingTime"])
            records[tick] = {
                "symbol": symbol,
                "funding_time_utc": datetime.fromtimestamp(tick / 1000, timezone.utc).isoformat(),
                "funding_rate": str(x["fundingRate"]),
                "mark_price": str(x["markPrice"]),
            }
        nxt = max(int(x["fundingTime"]) for x in page) + 1
        if nxt <= t:
            raise RuntimeError("API 分页没有推进")
        t = nxt
        time.sleep(0.2)
    return [records[k] for k in sorted(records)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    p.add_argument("--start", default="2021-01-01T00:00:00+00:00")
    p.add_argument("--end", default="2026-01-01T00:00:00+00:00")
    p.add_argument("--output", type=Path, default=Path("data/binance_usdm_funding_2021_2025.csv"))
    a = p.parse_args()
    rows = []
    for symbol in a.symbols:
        chunk = fetch(symbol, a.start, a.end)
        print(symbol, len(chunk), "条历史结算")
        if not chunk:
            raise RuntimeError(symbol + " 返回空数据，不写出不完整文件")
        rows.extend(chunk)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["symbol", "funding_time_utc", "funding_rate", "mark_price"])
        w.writeheader()
        w.writerows(rows)
    print("保存：", a.output, "共", len(rows), "条")


if __name__ == "__main__":
    main()
