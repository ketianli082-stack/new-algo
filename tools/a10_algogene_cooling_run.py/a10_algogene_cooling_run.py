"""V8 research：ALGOGENE 单次云端回测，严格仅调用 BACKTEST API。

GitHub Actions Secrets: ALGOGENE_USER_ID / ALGOGENE_API_KEY
首轮仅提交 2025 基准；其余区间需手动指定。
不调用交易账户或订单 API；不把敏感值写入日志/产物。
"""
if __package__:
    from .instrument_strategy import instrument
    from .extract_trade_statistics import extract
else:
    from instrument_strategy import instrument
    from extract_trade_statistics import extract
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
API = "https://algogene.com/rest/v1"
SYMBOLS = ["BTCUSD", "BTCUSDM", "ETHUSD", "ETHUSDM"]
DATES = {
    "2025": ("2025-01", "2025-12"),
    "2023-2025": ("2023-01", "2025-12"),
    "2024-2025": ("2024-01", "2025-12"),
    "2021-2025": ("2021-01", "2025-12"),
}
FIELDS = ("Score_Total", "TotalPnL", "AnnualSharpe", "maxDrawdown_pct",
          "TradeCnt", "profit_factor", "WinRate")


def redact(obj, secrets):
    hidden = {"user", "user_id", "api_key", "token", "password", "email"}
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if str(k).lower() in hidden
                    else redact(v, secrets)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x, secrets) for x in obj]
    if isinstance(obj, str):
        for s in secrets:
            if s:
                obj = obj.replace(s, "[REDACTED]")
    return obj


def settings(window):
    if window not in DATES:
        raise ValueError("未知回测时间范围")
    a, b = DATES[window]
    return dict(strategyName="A10 V8.1-NEXTBAR COOL1H H1 " + window,
                subscribeList=SYMBOLS, StartDate=a, EndDate=b,
                InitialCapital=1000000, BaseCurrency="USD", risk_free=0,
                Leverage=1, allowShortSell=True, dataset=60,
                isPositionBaseEnv=False, isNewsFeedOn=False,
                isEconstatFeedon=False, isWeatherFeedOn=False)


def validate_instrument_metadata(response, symbol):
    """Validate the observed /meta_instrument response schema.

    Platform metadata may contain only `res`, without `status`.
    Reject explicit status=false, missing `res`, or empty venue data.
    This is NOT verification of the strategy runtime getContractSpec().
    """
    if not isinstance(response, dict) or response.get("status") is False:
        raise RuntimeError("Instrument metadata explicitly rejected: " + symbol)
    spec = response.get("res")
    if not isinstance(spec, dict) or not spec:
        raise RuntimeError("Instrument metadata missing or empty: " + symbol)
    venues = [name for name, value in spec.items() if isinstance(value, dict) and value]
    if not venues:
        raise RuntimeError("Instrument metadata has no nonempty venue data: " + symbol)
    return venues


def execute(window):
    out = ROOT / "outputs" / "a10_cool1h" / window
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "strategy/a10_crypto_basis_v8_1_nextbar_cool1h.py").read_text(encoding="utf-8")
    source = instrument(source)
    compile(source, "a10_crypto_basis_v8_1_nextbar_cool1h.py", "exec")
    user = os.environ.get("ALGOGENE_USER_ID", "").strip()
    key = os.environ.get("ALGOGENE_API_KEY", "").strip()
    secrets = (user, key)
    st = settings(window)
    run = {"experiment": "V8 research", "window": window, "status": "NOT_RUN",
           "created_from_commit": os.environ.get("GITHUB_SHA"),
           "github_run_id": os.environ.get("GITHUB_RUN_ID"),
           "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
           "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
           "requested_settings": st, "backtest_id": None, "task_id": None,
           "platform_responses": {}, "errors": [],
           "notes": ["Platform fixed-cost parameter omitted; fees assessed separately as percentage of executed notional.",
                     "Offline historical annual Funding estimates are NOT included in platform NAV.",
                     "This action submits BACKTEST only; no live/real orders."]}
    last_call = [0.0]
    last_endpoint = [None]

    def save():
        (out / "platform-responses.json").write_text(
            json.dumps(redact(run, secrets), ensure_ascii=False, indent=2),
            encoding="utf-8")

    def call(endpoint, payload, label, post=False):
        # One request every 75 seconds to stay conservative with rate limits.
        wait = 75 - (time.monotonic() - last_call[0])
        if wait > 0:
            time.sleep(wait)
        last_endpoint[0] = endpoint
        data = dict(payload, user=user, api_key=key)
        req = urllib.request.Request(
            API + endpoint + ("" if post else "?" + urllib.parse.urlencode(data)),
            data=json.dumps(data).encode("utf-8") if post else None,
            method="POST" if post else "GET",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                result = json.load(response)
            run["platform_responses"].setdefault(label, []).append(
                redact(result, secrets))
            save()
            return result
        finally:
            last_call[0] = time.monotonic()

    save()
    if not user or not key:
        run.update(status="NOT_RUN", reason="Actions secrets missing")
        save()
        return 2
    if os.environ.get("GITHUB_RUN_ATTEMPT", "1") != "1":
        run.update(status="NOT_RUN", reason="Refuse resubmission on rerun (duplicate-order guard)")
        save()
        return 1
    try:
        run["status"] = "PREFLIGHT"
        save()
        tasks = call("/get_current_tasks", {}, "current_tasks")
        if tasks.get("status") is not True or tasks.get("res") != []:
            raise RuntimeError("ALGOGENE still has a task or failed preflight")
        # /meta_instrument returns a dictionary grouped by venue (for example
        # {"binance": {...}, "atfx": {"MT5": {...}}, ...}), NOT
        # getContractSpec()'s flat {"contractSize": ...} schema.
        # Validate instrument metadata exists, without pretending a venue's
        # trade_contract_size is ALGOGENE's runtime contractSize.
        for sym in SYMBOLS:
            rsp = call("/meta_instrument", {"instrument": sym}, "spec_" + sym)
            venues = validate_instrument_metadata(rsp, sym)
            run.setdefault("metadata_summary", {})[sym] = {
                "venue_count": len(venues),
                "sample_venue_names": venues[:8],
                "runtime_contract_size_verified": False,
            }
            save()
        # V8.1 independently calls getContractSpec() at backtest startup
        # and halts if its runtime contractSize != 1; preserve that guard.
        # Single POST attempt only. If request outcome is ambiguous, stop.
        run["status"] = "SUBMITTING"
        save()
        rsp = call("/run_backtest", {"code": source, "settings": st},
                   "submission", post=True)
        if rsp.get("status") is not True:
            run["status"] = "SUBMISSION_REJECTED"
            save()
            return 1
        for src, dst in (("runtime_id", "backtest_id"), ("task_id", "task_id")):
            v = rsp.get(src)
            if not isinstance(v, str) or not v or any(c not in "0123456789_" for c in v):
                raise ValueError("Unknown accepted task ID; do not resubmit blindly")
            run[dst] = v
        run["status"] = "SUBMITTED"
        save()
        print("V8 research", window, "SUBMITTED", run["backtest_id"], flush=True)
        deadline = time.monotonic() + 35 * 60
        while time.monotonic() < deadline:
            time.sleep(90)
            rsp = call("/task_status", {"task": "backtest", "task_id": run["task_id"]},
                       "task_status")
            if rsp.get("status") is True and rsp.get("res") == "DONE":
                run["status"] = "TASK_DONE"
                save()
                break
        else:
            run.update(status="PENDING", reason="Monitoring timeout; do not resubmit")
            save()
            return 1
        params = {"runmode": "backtest", "runtime_id": run["backtest_id"], "acdate": ""}
        for endpoint, label in (
            ("/strategy_stats", "statistics"),
            ("/strategy_logs", "console"),
            ("/strategy_trade", "trades"),
            ("/strategy_pl", "daily_pl"),
        ):
            try:
                p = dict(params)
                if endpoint == "/strategy_logs":
                    p.pop("acdate")
                call(endpoint, p, label)
            except Exception as exc:
                run["errors"].append({"endpoint": endpoint, "type": type(exc).__name__})
                save()
        stats = run["platform_responses"].get("statistics", [{}])[-1]
        perf = stats.get("performance", {}) if isinstance(stats, dict) else {}
        run["native_metrics"] = {k: perf[k] for k in FIELDS if isinstance(perf, dict) and k in perf}
        run["trade_statistics_status"] = extract(run["platform_responses"].get("console", []), out)
        run["status"] = "COLLECTED" if not run["errors"] else "COLLECTED_WITH_ERRORS"
        save()
        return 0 if not run["errors"] else 1
    except Exception as exc:
        run["errors"].append({"endpoint": last_endpoint[0],
                              "http_status": getattr(exc, "code", None),
                              "type": type(exc).__name__,
                              "message": redact(str(exc)[:350], secrets)})
        if run["status"] == "SUBMITTING":
            run["status"] = "SUBMISSION_UNCERTAIN"
        else:
            run["status"] = "ERROR"
        save()
        print("V8 research stopped:", run["status"], "endpoint=", last_endpoint[0], "HTTP=", getattr(exc, "code", None), type(exc).__name__, flush=True)
        return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", choices=list(DATES), default="2024-2025")
    a = parser.parse_args()
    return execute(a.window)


if __name__ == "__main__":
    sys.exit(main())

