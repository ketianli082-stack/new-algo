"""Upload verified funding artifacts to ALGOGENE without running a backtest.

The official upload_data endpoint is called once per file.  Metadata is uploaded
last and only when the workflow explicitly confirms the expected remote state is
absent.  No credential or raw API response is printed or stored.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


API = "https://algogene.com/rest/v1/upload_data"
ROOT = Path("outputs/funding_2021_2026")
STATUS = ROOT / "algogene_upload_status.json"
DATA_FILES = [
    "BTCUSDT_binance_usdm_funding_raw.csv",
    "ETHUSDT_binance_usdm_funding_raw.csv",
    "BTCUSDT_algogene_funding_daily_approx.csv",
    "ETHUSDT_algogene_funding_daily_approx.csv",
    "funding_validation.json",
]
META_FILE = "_meta_.json"
MIN_INTERVAL_SECONDS = 65


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(report: dict) -> None:
    STATUS.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def post_file(user: str, key: str, path: Path) -> dict:
    payload = {
        "user": user,
        "api_key": key,
        "file": path.name,
        "mode": "w",
        "msg": path.read_text(encoding="utf-8"),
    }
    req = urllib.request.Request(
        API,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        obj = json.load(response)
        http_status = response.status
    if not isinstance(obj, dict) or obj.get("status") is not True:
        raise RuntimeError("ALGOGENE rejected upload")
    return {"http_status": http_status, "api_status": True}


def main() -> int:
    user = os.environ.get("ALGOGENE_USER_ID", "").strip()
    key = os.environ.get("ALGOGENE_API_KEY", "").strip()
    expected_meta = os.environ.get("ALGOGENE_META_EXPECTED_STATE", "").strip()
    report = {
        "endpoint": "/upload_data",
        "mode": "overwrite named files",
        "backtest_or_trading_called": False,
        "credentials_present": bool(user and key),
        "metadata_expected_remote_state": expected_meta,
        "status": "NOT_STARTED",
        "files": [],
    }
    ROOT.mkdir(parents=True, exist_ok=True)
    save(report)
    if not user or not key:
        report.update(status="MISSING_SECRETS")
        save(report)
        return 2
    if expected_meta != "absent_confirmed_by_user":
        report.update(status="METADATA_GUARD_BLOCKED")
        save(report)
        return 2

    ordered = DATA_FILES + [META_FILE]
    missing = [name for name in ordered if not (ROOT / name).is_file()]
    if missing:
        report.update(status="MISSING_LOCAL_FILES", missing=missing)
        save(report)
        return 2
    validation = json.loads((ROOT / "funding_validation.json").read_text(encoding="utf-8"))
    if validation.get("status") != "verified" or validation.get("exact_8h_representation") is not False:
        report.update(status="VALIDATION_GUARD_BLOCKED")
        save(report)
        return 2

    last_call = 0.0
    for name in ordered:
        path = ROOT / name
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - last_call)
        if wait > 0:
            time.sleep(wait)
        item = {"file": name, "bytes": path.stat().st_size, "sha256": sha256(path)}
        try:
            result = post_file(user, key, path)
            item.update(status="UPLOADED", **result)
            report["files"].append(item)
            report["status"] = "IN_PROGRESS"
            save(report)
        except urllib.error.HTTPError as exc:
            item.update(status="FAILED", http_status=exc.code, error_type="HTTPError")
            report["files"].append(item)
            report.update(status="FAILED", failed_file=name)
            save(report)
            return 1
        except Exception as exc:
            item.update(status="FAILED", error_type=type(exc).__name__)
            report["files"].append(item)
            report.update(status="FAILED", failed_file=name)
            save(report)
            return 1
        finally:
            last_call = time.monotonic()

    report["status"] = "SUCCESS"
    save(report)
    print("ALGOGENE funding upload SUCCESS:", ", ".join(ordered), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
