"""R5-11..R5-14: Binance H1 liquidity, impact scenarios and capacity estimates.

This is a post-trade research tool.  It downloads public Binance 1-hour klines,
reads already-completed P80 ALGOGENE artifacts, and never submits a backtest or
changes the strategy.  Market impact and capacity are explicit scenarios, not
claims about executable or realized capacity.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW = ROOT / "data" / "binance_r5_11" / "raw"
DEFAULT_SOURCE = ROOT / "results" / "phase_b" / "r5_11_14" / "source"
DEFAULT_OUT = ROOT / "results" / "phase_b" / "r5_11_14"
MONTHS = pd.period_range("2024-01", "2025-12", freq="M")
SYMBOLS = ("BTCUSDT", "ETHUSDT")
VENUES = ("spot", "um")
PARTICIPATION = (0.01, 0.05, 0.10)
Y_VALUES = (0.5, 1.0, 1.5)


@dataclass(frozen=True)
class RunSpec:
    run: str
    capital: float
    rel: str


RUNS = (
    RunSpec("R5-07", 1_000_000.0, "R5-07"),
    RunSpec("R5-09", 10_000_000.0, "R5-09"),
    RunSpec("R5-10", 100_000_000.0, "R5-10"),
)


def archive_url(venue: str, symbol: str, month: pd.Period) -> str:
    root = "spot" if venue == "spot" else "futures/um"
    stem = f"{symbol}-1h-{month}.zip"
    return f"https://data.binance.vision/data/{root}/monthly/klines/{symbol}/1h/{stem}"


def _download_one(task: tuple[str, str, pd.Period], raw_dir: Path) -> dict:
    venue, symbol, month = task
    url = archive_url(venue, symbol, month)
    target = raw_dir / venue / symbol / url.rsplit("/", 1)[-1]
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.stat().st_size == 0:
        tmp = target.with_suffix(".part")
        req = urllib.request.Request(url, headers={"User-Agent": "new-algo-r5-liquidity/1"})
        with urllib.request.urlopen(req, timeout=90) as response, tmp.open("wb") as fh:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
        os.replace(tmp, target)
    blob = target.read_bytes()
    checksum_url = url + ".CHECKSUM"
    checksum_file = target.with_suffix(target.suffix + ".CHECKSUM")
    if not checksum_file.exists() or checksum_file.stat().st_size == 0:
        req = urllib.request.Request(checksum_url, headers={"User-Agent": "new-algo-r5-liquidity/1"})
        with urllib.request.urlopen(req, timeout=30) as response:
            checksum_file.write_bytes(response.read())
    expected_sha256 = checksum_file.read_text(encoding="utf-8").split()[0].lower()
    actual_sha256 = hashlib.sha256(blob).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(f"Binance checksum mismatch: {target}")
    return {
        "venue": venue,
        "symbol": symbol,
        "month": str(month),
        "url": url,
        "checksum_url": checksum_url,
        "local_file": str(target.relative_to(ROOT)),
        "bytes": len(blob),
        "sha256": actual_sha256,
        "publisher_sha256": expected_sha256,
        "checksum_verified": True,
    }


def download_archives(raw_dir: Path, workers: int = 8) -> pd.DataFrame:
    tasks = [(v, s, m) for v in VENUES for s in SYMBOLS for m in MONTHS]
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_download_one, task, raw_dir): task for task in tasks}
        for future in as_completed(futures):
            rows.append(future.result())
    return pd.DataFrame(rows).sort_values(["venue", "symbol", "month"]).reset_index(drop=True)


def normalize_epoch(value: int) -> pd.Timestamp:
    """Binance spot uses microseconds in newer archives; futures uses ms."""
    unit = "us" if abs(value) >= 10**15 else "ms"
    return pd.to_datetime(value, unit=unit, utc=True)


def load_archives(manifest: pd.DataFrame, raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    market = []
    audited = []
    for row in manifest.itertuples(index=False):
        path = ROOT / row.local_file
        if not path.exists():
            path = raw_dir / row.venue / row.symbol / row.url.rsplit("/", 1)[-1]
        with zipfile.ZipFile(path) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if len(csv_names) != 1:
                raise RuntimeError(f"Unexpected archive members in {path}: {zf.namelist()}")
            with zf.open(csv_names[0]) as fh:
                frame = pd.read_csv(fh, header=None)
        if frame.shape[1] < 8:
            raise RuntimeError(f"Kline schema too short in {path}: {frame.shape}")
        # Some newer public-data files may include a header row.
        frame = frame[pd.to_numeric(frame[0], errors="coerce").notna()].copy()
        open_times = pd.to_numeric(frame[0]).astype("int64")
        idx = pd.DatetimeIndex([normalize_epoch(int(v)) for v in open_times])
        out = pd.DataFrame(
            {
                "timestamp": idx,
                "venue": row.venue,
                "symbol": row.symbol,
                "open": pd.to_numeric(frame[1]).to_numpy(),
                "high": pd.to_numeric(frame[2]).to_numpy(),
                "low": pd.to_numeric(frame[3]).to_numpy(),
                "close": pd.to_numeric(frame[4]).to_numpy(),
                "base_volume": pd.to_numeric(frame[5]).to_numpy(),
                "quote_volume": pd.to_numeric(frame[7]).to_numpy(),
                "trades": pd.to_numeric(frame[8]).to_numpy(),
            }
        )
        out = out[(out["timestamp"] >= "2024-01-01") & (out["timestamp"] < "2026-01-01")]
        market.append(out)
        audited.append(
            {
                **row._asdict(),
                "rows": len(out),
                "first_open_utc": out["timestamp"].min().isoformat(),
                "last_open_utc": out["timestamp"].max().isoformat(),
            }
        )
    result = pd.concat(market, ignore_index=True).sort_values(["venue", "symbol", "timestamp"])
    if result.duplicated(["venue", "symbol", "timestamp"]).any():
        raise RuntimeError("Duplicate Binance H1 keys detected")
    expected = len(pd.date_range("2024-01-01", "2025-12-31 23:00", freq="h", tz="UTC"))
    counts = result.groupby(["venue", "symbol"]).size()
    if not (counts == expected).all():
        raise RuntimeError(f"Incomplete Binance H1 series: expected {expected}, got {counts.to_dict()}")
    result["log_return"] = result.groupby(["venue", "symbol"])["close"].transform(
        lambda x: np.log(x).diff()
    )
    return result.reset_index(drop=True), pd.DataFrame(audited)


def load_run(source_dir: Path, spec: RunSpec) -> tuple[dict, dict, list[dict]]:
    base = source_dir / spec.rel
    platform = json.loads((base / "platform-responses.json").read_text(encoding="utf-8"))
    stats_doc = json.loads((base / "trade_statistics.json").read_text(encoding="utf-8"))
    if stats_doc.get("status") != "SNAPSHOT_COMPLETE":
        raise RuntimeError(f"{spec.run} summary is not complete: {stats_doc.get('status')}")
    stats = stats_doc["snapshots"][-1]
    trades_payload = platform["platform_responses"]["trades"][-1]
    trades = trades_payload.get("res", [])
    return platform, stats, trades


def market_key(symbol: str) -> tuple[str, str]:
    mapping = {
        "BTCUSD": ("spot", "BTCUSDT"),
        "BTCUSDM": ("um", "BTCUSDT"),
        "ETHUSD": ("spot", "ETHUSDT"),
        "ETHUSDM": ("um", "ETHUSDT"),
    }
    return mapping[symbol]


def summarize_market(market: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (venue, symbol), g in market.groupby(["venue", "symbol"]):
        q = g["quote_volume"]
        r = g["log_return"].dropna()
        daily = g.set_index("timestamp")["close"].resample("1D").last().pipe(np.log).diff().dropna()
        rows.append(
            {
                "venue": venue,
                "symbol": symbol,
                "hours": len(g),
                "quote_volume_total_usd": q.sum(),
                "quote_volume_p10_usd": q.quantile(0.10),
                "quote_volume_median_usd": q.median(),
                "quote_volume_p90_usd": q.quantile(0.90),
                "hourly_log_return_sigma": r.std(ddof=1),
                "daily_log_return_sigma": daily.std(ddof=1),
            }
        )
    return pd.DataFrame(rows).sort_values(["symbol", "venue"]).reset_index(drop=True)


def build_backtest_tables(source_dir: Path, market: pd.DataFrame):
    market_lookup = market.set_index(["venue", "symbol", "timestamp"])["quote_volume"]
    summaries, samples, group_rows = [], [], []
    for spec in RUNS:
        platform, stats, trades = load_run(source_dir, spec)
        requested = platform["requested_settings"]
        financing = stats.get("funding_native_fields", {}).get("financing")
        summaries.append(
            {
                "run": spec.run,
                "initial_nav_usd": spec.capital,
                "backtest_id": platform.get("backtest_id"),
                "artifact_status": platform.get("status"),
                "summary_completeness": "complete",
                "asof_utc": stats.get("asof"),
                "fills_complete": stats.get("fills"),
                "completed_pairs_complete": stats.get("completed_pairs"),
                "executed_notional_complete_usd": stats.get("executed_notional"),
                "final_snapshot_nav_complete_usd": stats.get("platform_nav"),
                "native_financing_complete_usd": financing,
                "mean_reserved_gross_nav_complete": stats.get("mean_reserved_gross_nav"),
                "max_reserved_gross_nav_complete": stats.get("max_reserved_gross_nav"),
                "trade_rows_returned": len(trades),
                "trade_rows_reported_count": platform["platform_responses"]["trades"][-1].get("count"),
                "trade_sample_completeness": f"truncated_first_{len(trades)}_of_{stats.get('fills')}",
                "requested_start": requested.get("StartDate"),
                "requested_end": requested.get("EndDate"),
            }
        )
        for group, row in stats["groups"].items():
            group_rows.append(
                {
                    "run": spec.run,
                    "initial_nav_usd": spec.capital,
                    "group": group,
                    "pairs_complete": row["pairs"],
                    "completed_notional_usd": row["notional"],
                    "average_leg_fill_usd_complete": row["notional"] / (row["pairs"] * 4),
                    "average_leg_fill_nav_ratio_complete": row["notional"] / (row["pairs"] * 4 * spec.capital),
                }
            )
        for t in trades:
            venue, symbol = market_key(t["symbol"])
            ts = pd.Timestamp(t["timestamp"], tz="UTC").floor("h")
            qv = float(market_lookup.loc[(venue, symbol, ts)])
            notional = abs(float(t["volume"]) * float(t["price"]))
            samples.append(
                {
                    "run": spec.run,
                    "initial_nav_usd": spec.capital,
                    "sample_scope": f"first_{len(trades)}_of_{stats.get('fills')}",
                    "timestamp_utc": ts.isoformat(),
                    "algogene_symbol": t["symbol"],
                    "venue": venue,
                    "binance_symbol": symbol,
                    "openclose": t["openclose"],
                    "side": int(t["buysell"]),
                    "volume": float(t["volume"]),
                    "fill_price": float(t["price"]),
                    "fill_notional_usd": notional,
                    "fill_nav_ratio": notional / spec.capital,
                    "binance_h1_quote_volume_usd": qv,
                    "observed_participation": notional / qv if qv > 0 else np.nan,
                }
            )
    return pd.DataFrame(summaries), pd.DataFrame(group_rows), pd.DataFrame(samples)


def participation_summary(samples: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, g in samples.groupby(["run", "venue", "binance_symbol"]):
        p = g["observed_participation"]
        rows.append(
            {
                "run": keys[0],
                "venue": keys[1],
                "symbol": keys[2],
                "sample_fills": len(g),
                "sample_start_utc": g["timestamp_utc"].min(),
                "sample_end_utc": g["timestamp_utc"].max(),
                "participation_median": p.median(),
                "participation_p90": p.quantile(0.90),
                "participation_p95": p.quantile(0.95),
                "participation_max": p.max(),
                "share_above_1pct": (p > 0.01).mean(),
                "share_above_5pct": (p > 0.05).mean(),
                "share_above_10pct": (p > 0.10).mean(),
            }
        )
    return pd.DataFrame(rows)


def impact_table(market_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for m in market_summary.itertuples(index=False):
        for participation in PARTICIPATION:
            for y in Y_VALUES:
                # Matching a one-hour volume bucket with one-hour return volatility.
                impact_bp = y * m.hourly_log_return_sigma * math.sqrt(participation) * 10_000
                rows.append(
                    {
                        "venue": m.venue,
                        "symbol": m.symbol,
                        "participation_assumption": participation,
                        "Y_assumption": y,
                        "hourly_sigma": m.hourly_log_return_sigma,
                        "one_way_impact_bp_scenario": impact_bp,
                    }
                )
    return pd.DataFrame(rows)


def capacity_table(
    market_summary: pd.DataFrame, group_stats: pd.DataFrame, samples: pd.DataFrame
) -> pd.DataFrame:
    rows = []
    sample507 = samples[samples["run"] == "R5-07"]
    for m in market_summary.itertuples(index=False):
        group = "BTC" if m.symbol.startswith("BTC") else "ETH"
        sg = sample507[(sample507["venue"] == m.venue) & (sample507["binance_symbol"] == m.symbol)]
        tail_ratio = float(sg["fill_nav_ratio"].quantile(0.95))
        for p in PARTICIPATION:
            for volume_basis, hourly_volume in (
                ("p10_hour", m.quote_volume_p10_usd),
                ("median_hour", m.quote_volume_median_usd),
            ):
                available = p * hourly_volume
                rows.append(
                    {
                        "venue": m.venue,
                        "symbol": m.symbol,
                        "participation_assumption": p,
                        "hourly_volume_basis": volume_basis,
                        "hourly_quote_volume_usd": hourly_volume,
                        "max_fill_usd_scenario": available,
                        "nav_capacity_policy_20pct_leg_usd": available / 0.20,
                        "nav_capacity_truncated_sample_p95_fill_usd": available / tail_ratio,
                        "policy_fill_ratio_source": "strategy single leg target approximately 20pct contemporaneous NAV",
                        "tail_fill_ratio_source": f"R5-07_truncated_first_{len(sample507)}_fills",
                    }
                )
    return pd.DataFrame(rows)


def impact_cost_table(group_stats: pd.DataFrame, impacts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    idx = impacts.set_index(["venue", "symbol", "participation_assumption", "Y_assumption"])
    for g in group_stats.itertuples(index=False):
        symbol = f"{g.group}USDT"
        for p in PARTICIPATION:
            for y in Y_VALUES:
                spot_bp = float(idx.loc[("spot", symbol, p, y), "one_way_impact_bp_scenario"])
                um_bp = float(idx.loc[("um", symbol, p, y), "one_way_impact_bp_scenario"])
                # Completed notional contains both venues and both entry/exit; split 50/50.
                cost = g.completed_notional_usd * (spot_bp + um_bp) / 2 / 10_000
                rows.append(
                    {
                        "run": g.run,
                        "group": g.group,
                        "participation_assumption": p,
                        "Y_assumption": y,
                        "completed_notional_usd": g.completed_notional_usd,
                        "spot_impact_bp": spot_bp,
                        "um_impact_bp": um_bp,
                        "estimated_impact_cost_usd_scenario": cost,
                        "impact_cost_pct_initial_nav_scenario": cost / g.initial_nav_usd * 100,
                    }
                )
    return pd.DataFrame(rows)


def save_figures(
    market: pd.DataFrame,
    samples: pd.DataFrame,
    impacts: pd.DataFrame,
    capacity: pd.DataFrame,
    chart_dir: Path,
) -> None:
    chart_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")

    fig, ax = plt.subplots(figsize=(10, 5.5))
    labels, values = [], []
    for (venue, symbol), g in market.groupby(["venue", "symbol"]):
        labels.append(f"{symbol}\n{venue}")
        values.append(g["quote_volume"].to_numpy())
    ax.boxplot(values, labels=labels, showfliers=False)
    ax.set_yscale("log")
    ax.set_ylabel("Hourly quote volume (USD, log scale)")
    ax.set_title("Binance 2024-2025 H1 liquidity")
    fig.tight_layout()
    fig.savefig(chart_dir / "r5_11_hourly_quote_volume.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    for run, g in samples.groupby("run"):
        x = np.sort(g["observed_participation"].dropna().to_numpy()) * 100
        y = np.arange(1, len(x) + 1) / len(x)
        ax.plot(x, y, label=f"{run} (first 100 fills)")
    ax.set_xscale("log")
    ax.axvline(1, color="grey", ls="--", lw=1)
    ax.axvline(5, color="grey", ls=":", lw=1)
    ax.axvline(10, color="grey", ls="-.", lw=1)
    ax.set_xlabel("Fill / same Binance H1 quote volume (%)")
    ax.set_ylabel("Empirical CDF")
    ax.set_title("Observed participation in truncated ALGOGENE trade samples")
    ax.legend()
    fig.tight_layout()
    fig.savefig(chart_dir / "r5_12_participation_cdf.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, venue in zip(axes, VENUES):
        sub = impacts[(impacts["venue"] == venue) & (impacts["Y_assumption"] == 1.0)]
        for symbol, g in sub.groupby("symbol"):
            ax.plot(g["participation_assumption"] * 100, g["one_way_impact_bp_scenario"], marker="o", label=symbol)
        ax.set_title(f"{venue}: Y=1.0")
        ax.set_xlabel("Assumed participation (%)")
        ax.legend()
    axes[0].set_ylabel("One-way impact (bp, scenario)")
    fig.suptitle("Square-root market-impact scenarios (hourly sigma)")
    fig.tight_layout()
    fig.savefig(chart_dir / "r5_13_impact_scenarios.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    sub = capacity[
        (capacity["hourly_volume_basis"] == "p10_hour")
        & (capacity["participation_assumption"] == 0.05)
    ].copy()
    sub["key"] = sub["symbol"] + " " + sub["venue"]
    ax.bar(sub["key"], sub["nav_capacity_truncated_sample_p95_fill_usd"] / 1e6)
    ax.axhline(100, color="red", ls="--", label="R5-10 initial NAV")
    ax.set_ylabel("Estimated NAV capacity (USD millions)")
    ax.set_title("5% participation, P10 liquidity, sample-P95 fill sizing")
    ax.legend()
    fig.tight_layout()
    fig.savefig(chart_dir / "r5_14_capacity_scenarios.png", dpi=180)
    plt.close(fig)


def write_outputs(
    out_dir: Path,
    manifest: pd.DataFrame,
    audited_manifest: pd.DataFrame,
    market: pd.DataFrame,
    source_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    market_summary = summarize_market(market)
    backtests, group_stats, samples = build_backtest_tables(source_dir, market)
    psummary = participation_summary(samples)
    impacts = impact_table(market_summary)
    capacity = capacity_table(market_summary, group_stats, samples)
    impact_costs = impact_cost_table(group_stats, impacts)
    tables = {
        "r5_11_data_manifest.csv": audited_manifest,
        "r5_11_market_summary.csv": market_summary,
        "r5_11_14_backtest_summary.csv": backtests,
        "r5_12_trade_sample_matched.csv": samples,
        "r5_12_participation_summary.csv": psummary,
        "r5_13_impact_scenarios.csv": impacts,
        "r5_13_impact_cost_scenarios.csv": impact_costs,
        "r5_14_capacity_scenarios.csv": capacity,
        "r5_14_group_fill_scaling.csv": group_stats,
    }
    for name, frame in tables.items():
        frame.to_csv(out_dir / name, index=False, float_format="%.12g")
    save_figures(market, samples, impacts, capacity, out_dir / "charts")
    provenance = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "binance_period": "2024-01-01T00:00:00Z/2025-12-31T23:00:00Z",
        "bar_frequency": "1h",
        "archives": len(manifest),
        "market_rows": len(market),
        "impact_formula": "impact_bp = Y * hourly_log_return_sigma * sqrt(participation) * 10000",
        "capacity_warning": "Scenario estimate only; not observed executable capacity.",
        "trade_sample_warning": "ALGOGENE strategy_trade returned only first 100 of 1694 fills per run.",
    }
    (out_dir / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()
    if args.skip_download:
        rows = []
        for venue in VENUES:
            for symbol in SYMBOLS:
                for month in MONTHS:
                    url = archive_url(venue, symbol, month)
                    path = args.raw_dir / venue / symbol / url.rsplit("/", 1)[-1]
                    blob = path.read_bytes()
                    checksum_file = path.with_suffix(path.suffix + ".CHECKSUM")
                    expected_sha256 = checksum_file.read_text(encoding="utf-8").split()[0].lower()
                    actual_sha256 = hashlib.sha256(blob).hexdigest()
                    if actual_sha256 != expected_sha256:
                        raise RuntimeError(f"Binance checksum mismatch: {path}")
                    rows.append(
                        {
                            "venue": venue,
                            "symbol": symbol,
                            "month": str(month),
                            "url": url,
                            "checksum_url": url + ".CHECKSUM",
                            "local_file": str(path.relative_to(ROOT)),
                            "bytes": len(blob),
                            "sha256": actual_sha256,
                            "publisher_sha256": expected_sha256,
                            "checksum_verified": True,
                        }
                    )
        manifest = pd.DataFrame(rows)
    else:
        manifest = download_archives(args.raw_dir, args.workers)
    market, audited_manifest = load_archives(manifest, args.raw_dir)
    write_outputs(args.out_dir, manifest, audited_manifest, market, args.source_dir)


if __name__ == "__main__":
    main()
