"""R5-11A read-only ALGOGENE historical market-data API diagnostic.

Queries four strategy instruments through ``GET /history_price`` at hourly
granularity.  The saved report contains only request metadata, observed schema,
and a small allow-listed market-data sample.  Credentials and raw error bodies
are never persisted or printed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request


API_URL = "https://algogene.com/rest/v1/history_price"
SYMBOLS = ("BTCUSD", "BTCUSDM", "ETHUSD", "ETHUSDM")
DEFAULT_TIMESTAMP = "2025-12-31"
DEFAULT_COUNT = 3
MIN_REQUEST_GAP_SECONDS = 65
OUT = Path("outputs/r5_11a/history-api-diagnostic.json")

# ALGOGENE documents aggregated OHLCV, plus bid/ask size and order-book data
# for market-data products.  Keep aliases broad because the diagnostic's job is
# to discover the schema actually returned by /history_price.
PRICE_FIELDS = {
    "t", "timestamp", "time", "o", "open", "h", "high", "l", "low",
    "c", "close", "bid", "ask", "b", "a", "mid", "last", "lastprice",
}
VOLUME_FIELDS = {
    "v", "volume", "vol", "tick_volume", "real_volume", "trade_volume",
}
DEPTH_FIELDS = {
    "bid_size", "ask_size", "bidsize", "asksize", "bidvolume", "askvolume",
    "bid_volume", "ask_volume", "bid_depth", "ask_depth", "biddepth",
    "askdepth", "bid_book", "ask_book", "bidbook", "askbook", "bids",
    "asks", "orderbook", "order_book", "depth", "book",
}
DENY_FIELDS = {
    "user", "user_id", "userid", "api_key", "apikey", "token", "password",
    "email", "session", "session_id", "account", "account_id",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalized_key(key: object) -> str:
    return str(key).strip().lower().replace("-", "_").replace(" ", "_")


def is_safe_scalar(value: object) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def safe_depth_summary(value: object) -> dict:
    """Describe a depth value without copying an unbounded order book."""
    summary = {"type": type(value).__name__}
    if isinstance(value, (list, tuple)):
        summary["level_count"] = len(value)
        if value:
            first = value[0]
            if isinstance(first, (list, tuple)):
                summary["first_level_width"] = len(first)
                summary["first_level_numeric"] = all(
                    isinstance(item, (int, float)) and not isinstance(item, bool)
                    for item in first
                )
            elif isinstance(first, dict):
                summary["first_level_fields"] = sorted(
                    normalized_key(key) for key in first if normalized_key(key) not in DENY_FIELDS
                )
    elif isinstance(value, dict):
        summary["level_count"] = len(value)
        summary["fields"] = sorted(
            normalized_key(key) for key in value if normalized_key(key) not in DENY_FIELDS
        )[:20]
    elif is_safe_scalar(value):
        summary["value"] = value
    return summary


def summarize_bars(payload: object, sample_limit: int = 3) -> dict:
    """Return an allow-listed, bounded summary of a history_price response."""
    result = {
        "response_type": type(payload).__name__,
        "api_status": None,
        "result_type": None,
        "bar_count": 0,
        "bar_fields": [],
        "volume_fields_present": [],
        "depth_fields_present": [],
        "samples": [],
    }
    if not isinstance(payload, dict):
        return result
    if isinstance(payload.get("status"), bool):
        result["api_status"] = payload["status"]
    bars = payload.get("res")
    result["result_type"] = type(bars).__name__
    if isinstance(bars, dict):
        # Tolerate a timestamp-keyed mapping as used by getHistoricalBar.
        normalized = []
        for timestamp, value in bars.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("t", timestamp)
                normalized.append(row)
        bars = normalized
    if not isinstance(bars, list):
        return result

    rows = [row for row in bars if isinstance(row, dict)]
    result["bar_count"] = len(rows)
    field_map = {}
    for row in rows:
        for original in row:
            key = normalized_key(original)
            if key not in DENY_FIELDS:
                field_map.setdefault(key, str(original))
    fields = sorted(field_map)
    result["bar_fields"] = fields
    result["volume_fields_present"] = sorted(set(fields) & VOLUME_FIELDS)
    result["depth_fields_present"] = sorted(set(fields) & DEPTH_FIELDS)

    allowed_scalars = PRICE_FIELDS | VOLUME_FIELDS | DEPTH_FIELDS
    for row in rows[:sample_limit]:
        sample = {}
        for original, value in row.items():
            key = normalized_key(original)
            if key in DENY_FIELDS or key not in allowed_scalars:
                continue
            if key in DEPTH_FIELDS and not is_safe_scalar(value):
                sample[key] = safe_depth_summary(value)
            elif is_safe_scalar(value):
                sample[key] = value
        result["samples"].append(sample)
    return result


def classify_http_error(error: urllib.error.HTTPError) -> str:
    body = error.read(4096).decode("utf-8", errors="replace").lower()
    if error.code == 429 or "exceed maximum access count" in body or "too many requests" in body:
        return "RATE_LIMIT"
    if "api_key" in body and any(word in body for word in ("invalid", "incorrect", "unauthorized")):
        return "CREDENTIAL_REJECTED"
    if error.code in (401, 403) or "permission" in body or "forbidden" in body:
        return "PERMISSION_DENIED"
    return "UNCLASSIFIED_HTTP_ERROR"


def query_symbol(symbol: str, user: str, key: str, count: int, timestamp: str) -> dict:
    public_request = {
        "instrument": symbol,
        "count": count,
        "interval": "H",
        "timestamp": timestamp,
    }
    params = dict(public_request, user=user, api_key=key)
    request = urllib.request.Request(
        API_URL + "?" + urllib.parse.urlencode(params),
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "new-algo-r5-11a/1.0"},
    )
    item = {"request": public_request, "status": "UNKNOWN"}
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read(2_000_000).decode("utf-8", errors="strict")
            item["http_status"] = response.status
        payload = json.loads(raw)
        item.update(summarize_bars(payload, sample_limit=count))
        accepted = item.get("api_status") is not False and item.get("bar_count", 0) > 0
        item["status"] = "SUCCESS" if accepted else "EMPTY_OR_REJECTED"
    except urllib.error.HTTPError as error:
        item.update(
            status="HTTP_ERROR",
            http_status=error.code,
            reason_category=classify_http_error(error),
            retry_after_present=bool(error.headers.get("Retry-After")),
        )
    except urllib.error.URLError as error:
        item.update(status="NETWORK_ERROR", exception_type=type(error.reason).__name__)
    except (UnicodeError, json.JSONDecodeError) as error:
        item.update(status="INVALID_RESPONSE", exception_type=type(error).__name__)
    except Exception as error:  # Keep diagnostics available for unexpected failures.
        item.update(status="OTHER_ERROR", exception_type=type(error).__name__)
    return item


def run(count: int, timestamp: str, output: Path = OUT, request_gap: int = MIN_REQUEST_GAP_SECONDS) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    user = os.environ.get("ALGOGENE_USER_ID", "").strip()
    key = os.environ.get("ALGOGENE_API_KEY", "").strip()
    report = {
        "experiment": "R5-11A",
        "mode": "read_only",
        "endpoint": "/history_price",
        "generated_at_utc": utc_now(),
        "credentials_present": bool(user and key),
        "symbols": list(SYMBOLS),
        "requested_interval": "H",
        "requested_count": count,
        "requested_timestamp": timestamp,
        "request_gap_seconds": request_gap,
        "official_references": [
            "https://algogene.com/RestDoc",
            "https://algogene.com/community/post/30",
            "https://algogene.com/community/post/48",
        ],
        "results": {},
        "status": "UNKNOWN",
        "notes": [
            "No credential values or raw error bodies are stored.",
            "Samples contain only allow-listed market-data fields.",
            "Hourly OHLCV availability does not imply historical order-book depth availability.",
        ],
    }

    def save() -> None:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not user or not key:
        report["status"] = "MISSING_SECRETS"
        save()
        print("R5-11A MISSING_SECRETS", flush=True)
        return 1

    for index, symbol in enumerate(SYMBOLS):
        if index and request_gap > 0:
            time.sleep(request_gap)
        item = query_symbol(symbol, user, key, count, timestamp)
        report["results"][symbol] = item
        save()
        print(
            "R5-11A",
            symbol,
            item["status"],
            "HTTP",
            item.get("http_status"),
            "bars",
            item.get("bar_count", 0),
            "volume_fields",
            item.get("volume_fields_present", []),
            "depth_fields",
            item.get("depth_fields_present", []),
            flush=True,
        )

    success_count = sum(item.get("status") == "SUCCESS" for item in report["results"].values())
    report["successful_symbols"] = success_count
    report["status"] = "SUCCESS" if success_count == len(SYMBOLS) else "PARTIAL_OR_FAILED"
    save()
    print("R5-11A COMPLETE", report["status"], success_count, "/", len(SYMBOLS), flush=True)
    return 0 if report["status"] == "SUCCESS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--timestamp", default=DEFAULT_TIMESTAMP)
    args = parser.parse_args()
    if not 1 <= args.count <= 10:
        parser.error("--count must be between 1 and 10")
    return run(args.count, args.timestamp)


if __name__ == "__main__":
    raise SystemExit(main())
