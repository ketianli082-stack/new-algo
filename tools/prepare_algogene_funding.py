"""Prepare verified Binance USD-M funding data and ALGOGENE daily proxy curves.

The raw CSVs preserve every settlement returned by Binance.  ALGOGENE's
documented funding-curve feature applies financing daily, so the curve CSVs are
explicit UTC-calendar-day approximations: each day's exact Binance settlement
rates are summed, with Long=-sum(rate) and Short=+sum(rate).  They must not be
described as exact 8-hour settlement curves.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API = "https://fapi.binance.com/fapi/v1/fundingRate"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
START = datetime(2021, 1, 1, tzinfo=timezone.utc)
END_CAP = datetime(2026, 11, 25, tzinfo=timezone.utc)  # exclusive
MAX_EXPECTED_GAP = timedelta(hours=8, minutes=1)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return dt.astimezone(timezone.utc)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def fetch_symbol(symbol: str, start: datetime, end_exclusive: datetime) -> list[dict]:
    """Fetch the inclusive Binance pages while exposing, not hiding, duplicates."""
    cursor = _ms(start)
    stop = _ms(end_exclusive) - 1
    rows: list[dict] = []
    while cursor <= stop:
        query = urlencode({
            "symbol": symbol,
            "startTime": cursor,
            "endTime": stop,
            "limit": 1000,
        })
        req = Request(API + "?" + query, headers={"Accept": "application/json"})
        with urlopen(req, timeout=45) as response:
            page = json.load(response)
        if not isinstance(page, list):
            raise RuntimeError("Binance funding endpoint returned a non-list response")
        if not page:
            break
        rows.extend(page)
        next_cursor = max(int(item["fundingTime"]) for item in page) + 1
        if next_cursor <= cursor:
            raise RuntimeError("Binance pagination did not advance")
        cursor = next_cursor
        time.sleep(0.2)
    return rows


def normalize_and_validate(
    symbol: str,
    rows: list[dict],
    start: datetime,
    observed_until: datetime,
) -> tuple[list[dict], dict]:
    normalized = []
    for item in rows:
        if item.get("symbol") != symbol:
            raise ValueError(f"{symbol}: API returned a different symbol")
        tick = int(item["fundingTime"])
        moment = datetime.fromtimestamp(tick / 1000, timezone.utc)
        rate = Decimal(str(item["fundingRate"]))
        mark = Decimal(str(item["markPrice"]))
        if not rate.is_finite() or not mark.is_finite() or mark <= 0:
            raise ValueError(f"{symbol}: invalid funding rate or mark price")
        if not start <= moment < observed_until:
            raise ValueError(f"{symbol}: settlement outside requested interval")
        normalized.append({
            "symbol": symbol,
            "funding_time_ms": tick,
            "funding_time_utc": iso_utc(moment),
            "funding_rate": str(item["fundingRate"]),
            "mark_price": str(item["markPrice"]),
            "_moment": moment,
            "_rate": rate,
        })
    normalized.sort(key=lambda row: row["funding_time_ms"])
    counts = Counter(row["funding_time_ms"] for row in normalized)
    duplicates = sorted(tick for tick, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"{symbol}: duplicate funding settlements: {len(duplicates)}")
    if not normalized:
        raise ValueError(f"{symbol}: no funding settlements returned")

    times = [row["_moment"] for row in normalized]
    gaps = [right - left for left, right in zip(times, times[1:])]
    excessive = [gap for gap in gaps if gap > MAX_EXPECTED_GAP]
    if times[0] - start > MAX_EXPECTED_GAP:
        raise ValueError(f"{symbol}: start coverage gap exceeds 8 hours")
    if observed_until - times[-1] > MAX_EXPECTED_GAP:
        raise ValueError(f"{symbol}: latest settlement is more than 8 hours stale")
    if excessive:
        raise ValueError(f"{symbol}: {len(excessive)} internal gaps exceed 8 hours")

    interval_counts = Counter(
        f"{gap.total_seconds() / 3600:g}" for gap in gaps
    )
    report = {
        "events": len(normalized),
        "duplicate_timestamps": 0,
        "first_settlement_utc": iso_utc(times[0]),
        "last_settlement_utc": iso_utc(times[-1]),
        "largest_gap_hours": max((gap.total_seconds() / 3600 for gap in gaps), default=0),
        "gaps_over_8_hours": 0,
        "interval_hours_histogram": dict(sorted(interval_counts.items())),
    }
    return normalized, report


def daily_curve(rows: list[dict]) -> list[dict]:
    totals: dict[str, Decimal] = defaultdict(Decimal)
    events: Counter = Counter()
    for row in rows:
        day = row["_moment"].date().isoformat()
        totals[day] += row["_rate"]
        events[day] += 1
    result = []
    for day in sorted(totals):
        short = totals[day]
        long = -short
        if long == 0:
            long = Decimal(0)
        if short == 0:
            short = Decimal(0)
        result.append({
            "Date": day,
            "Long": format(long, "f"),
            "Short": format(short, "f"),
            "_events": events[day],
        })
    return result


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare(output: Path, now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    observed_until = min(now, END_CAP)
    if observed_until <= START:
        raise ValueError("observed end must be after 2021-01-01 UTC")
    output.mkdir(parents=True, exist_ok=True)

    names = {
        "BTCUSDT": {
            "raw": "BTCUSDT_binance_usdm_funding_raw.csv",
            "curve": "BTCUSDT_algogene_funding_daily_approx.csv",
            "curve_name": "BINANCE_BTCUSDT_USDM_FUNDING_DAILY_APPROX",
        },
        "ETHUSDT": {
            "raw": "ETHUSDT_binance_usdm_funding_raw.csv",
            "curve": "ETHUSDT_algogene_funding_daily_approx.csv",
            "curve_name": "BINANCE_ETHUSDT_USDM_FUNDING_DAILY_APPROX",
        },
    }
    validation = {
        "status": "verified",
        "source": API,
        "market": "Binance USD-M perpetual futures",
        "requested_start_utc": iso_utc(START),
        "observed_until_utc_exclusive": iso_utc(observed_until),
        "hard_end_cap_utc_exclusive": iso_utc(END_CAP),
        "raw_unit": "decimal funding rate per actual Binance settlement",
        "curve_unit": "decimal sum of actual settlement rates per UTC calendar day",
        "curve_frequency": "daily approximation required by documented ALGOGENE daily financing behavior",
        "curve_sign": "Long=-daily_sum; Short=+daily_sum; positive Binance rate means longs pay shorts",
        "exact_8h_representation": False,
        "warnings": [
            "Curve rows aggregate exact intraday settlements by UTC date; they do not preserve 8-hour cash-flow timing.",
            "Binance BTCUSDT/ETHUSDT rates are proxy data and are not claimed to be ALGOGENE-native rates.",
            "The final UTC day can be partial when the workflow runs before 24:00 UTC.",
        ],
        "symbols": {},
    }

    for symbol in SYMBOLS:
        fetched = fetch_symbol(symbol, START, observed_until)
        raw, symbol_report = normalize_and_validate(symbol, fetched, START, observed_until)
        curve = daily_curve(raw)
        raw_path = output / names[symbol]["raw"]
        curve_path = output / names[symbol]["curve"]
        _write_csv(
            raw_path,
            ["symbol", "funding_time_ms", "funding_time_utc", "funding_rate", "mark_price"],
            raw,
        )
        _write_csv(curve_path, ["Date", "Long", "Short"], curve)
        symbol_report.update({
            "raw_file": raw_path.name,
            "curve_file": curve_path.name,
            "curve_name": names[symbol]["curve_name"],
            "curve_days": len(curve),
            "first_curve_date": curve[0]["Date"],
            "last_curve_date": curve[-1]["Date"],
            "last_curve_day_event_count": curve[-1]["_events"],
        })
        validation["symbols"][symbol] = symbol_report

    meta = {}
    for symbol in SYMBOLS:
        info = names[symbol]
        meta[info["curve_name"]] = {
            "file": info["curve"],
            "file_delimiter": ",",
            "fmt_time": "%Y-%m-%d",
            "col_time": 0,
            "col_long": 1,
            "col_short": 2,
        }
    meta_path = output / "_meta_.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    files = [
        output / names[symbol][kind]
        for symbol in SYMBOLS
        for kind in ("raw", "curve")
    ] + [meta_path]
    validation["files"] = {
        path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in files
    }
    validation_path = output / "funding_validation.json"
    validation_path.write_text(
        json.dumps(validation, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": validation["status"],
        "observed_until_utc_exclusive": validation["observed_until_utc_exclusive"],
        "symbols": validation["symbols"],
    }, ensure_ascii=False))
    return validation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/funding_2021_2026"),
    )
    args = parser.parse_args()
    prepare(args.output)


if __name__ == "__main__":
    main()
