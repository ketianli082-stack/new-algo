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


def settings(window, leverage):
    if window not in DATES:
        raise ValueError("未知回测时间范围")
    a, b = DATES[window]
    return dict(strategyName="R5-04B SAMEBAR FUNDING-ANNUALIZED EXPANDED H1 " + window + " L" + str(leverage),
                subscribeList=SYMBOLS, StartDate=a, EndDate=b,
                InitialCapital=1000000, BaseCurrency="USD", risk_free=0,
                Leverage=leverage, allowShortSell=True, dataset=60,
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


def execute(window, leverage):
    out = ROOT / "outputs" / "r5_04b_exposure" / window / ("L"+str(leverage))
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "strategy/a16_crypto_basis_v8_1_nextbar_costtp_cap50.py").read_text(encoding="utf-8")
    for old,new in (
        ("PAIR_GROSS_CAP = .40", "PAIR_GROSS_CAP = "+str(.40*leverage)),
        ("TOTAL_GROSS_CAP = .50", "TOTAL_GROSS_CAP = "+str(.50*leverage)),
        ("PAIR_RISK_CAP = .0025", "PAIR_RISK_CAP = "+str(.0025*leverage)),
    ):
        if source.count(old)!=1:
            raise RuntimeError("Exposure parameter anchor mismatch: "+old)
        source=source.replace(old,new)
    source=source.replace("pair/total gross40%/80%", "expanded gross caps")
    source=source.replace("risk cap0.25% NAV/pair", "expanded risk budget")
    source = instrument(source)
    # Same-bar control: remove only the deferred-entry state machine.
    start = source.index("            pend=self.pending.get(group)")
    end = source.index("        if now.month==12", start)
    source = source[:start] + """            if signal is None or not aligned or nav is None or self.halt_entries or self.closing_block():
                continue
            if any(p['group']==group for p in self.active_pairs()):
                continue
            if self.cooldown.get(group) is not None and now<self.cooldown[group]:
                continue
            if self.last_entry.get(group)==now:
                continue
            self.last_entry[group]=now
            self.log('ENTRY_SAME_BAR',group,now,'signal_entry_bp',signal['entry'],
                     'exec_entry_bp',current['entry'],'target_bp',signal['target'])
            self.open_pair(group,signal,nav,ab)

""" + source[end:]

    # Accumulate all unique accepted fills, emit compact snapshots repeatedly.
    hooks = [
        ("            self.stats.fill(p['id'],leg['symbol'],trade_id,'open',qty,price)",
         "            self.quote_diag(p,leg,trade_id,'open',qty,price,of)\n            self.stats.fill(p['id'],leg['symbol'],trade_id,'open',qty,price)"),
        ("            self.stats.fill(p['id'],leg['symbol'],trade_id,'close',qty,price,lot['pnl'])",
         "            self.quote_diag(p,leg,trade_id,'close',qty,price,of)\n            self.stats.fill(p['id'],leg['symbol'],trade_id,'close',qty,price,lot['pnl'])"),
        ("        self.stats.sample(now,nav,self.gross_reserved())",
         "        self.stats.sample(now,nav,self.gross_reserved())\n        if getattr(self,'_qd_last_day',None)!=(now.year,now.strftime('%W')):\n            self._qd_last_day=(now.year,now.strftime('%W'))\n            self.quote_diag_report()"),
        ("    def on_marketdatafeed(self,md,ab):", """    def quote_diag(self,p,leg,trade_id,kind,qty,price,of):
        if not hasattr(self,'_qd'):
            self._qd={}
        key=leg['symbol']+'|'+kind
        a=self._qd.setdefault(key,{'count':0,'missing':0,'stale':0,'raw':[],'adverse':[],'usd':0.0,'matched_usd':0.0,'matched':0,'fill_time_present':0})
        a['count']+=1
        if getattr(of,'timestamp',None) is not None:
            a['fill_time_present']+=1
        q=self.quotes.get(leg['symbol'],{})
        side=leg['side'] if kind=='open' else -leg['side']
        b=q.get('ask' if side==1 else 'bid')
        if not b:
            a['missing']+=1
            return
        if q.get('t')!=self.now:
            a['stale']+=1
            return
        raw=(price/b-1)*10000
        adverse=side*raw
        a['raw'].append(raw)
        a['adverse'].append(adverse)
        a['usd']+=side*qty*(price-b)
        if not hasattr(self,'_qd_open'):
            self._qd_open={}
        k=(leg['symbol'],trade_id)
        if kind=='open':
            self._qd_open[k]=side*qty*(price-b)
        elif k in self._qd_open:
            a['matched']+=1
            a['matched_usd']+=self._qd_open.pop(k)+side*qty*(price-b)
        self.quote_diag_report()

    def quote_diag_report(self):
        if not getattr(self,'_qd',None):
            return
        def metrics(values):
            n=len(values)
            if not n:
                return None
            v=sorted(values)
            return dict(mean=sum(v)/n,median=(v[(n-1)//2]+v[n//2])/2,
                        p95=v[max(0,(95*n+99)//100-1)],min=v[0],max=v[-1],
                        max_abs=max(abs(x) for x in v))
        for key,a in sorted(self._qd.items()):
            row={k:v for k,v in a.items() if k not in ('raw','adverse')}
            row.update(raw_bp=metrics(a['raw']),adverse_bp=metrics(a['adverse']),valid=len(a['raw']))
            self.log('QUOTE_DIAG_R5 '+json.dumps(dict(asof=str(self.now),group=key,data=row),separators=(',',':')))

    def on_marketdatafeed(self,md,ab):""")
    ]
    for old,new in hooks:
        if source.count(old)!=1:
            raise RuntimeError("R1 diagnostic anchor mismatch: "+old[:80])
        source=source.replace(old,new)

    # Bind only the perpetual legs to the uploaded daily approximation curves.
    # No additional offline Funding debit: platform financing must be verified.
    funding_anchor = "        self.evt.start()"
    funding_code = """        for symbol, curve in (
            ('BTCUSDM', 'BINANCE_BTCUSDT_USDM_FUNDING_DAILY_APPROX_ANNUALIZED'),
            ('ETHUSDM', 'BINANCE_ETHUSDT_USDM_FUNDING_DAILY_APPROX_ANNUALIZED'),
        ):
            result = self.evt.setFundingCurve(instrument=symbol, curve_name=curve)
            self.log('FUNDING_BIND_R5', symbol, curve, repr(result))
            if result is False or (isinstance(result, dict) and result.get('status') is False):
                raise RuntimeError('Funding curve binding rejected: '+symbol)
        self.evt.start()"""
    if source.count(funding_anchor) != 1:
        raise RuntimeError("Funding start anchor mismatch")
    source = source.replace(funding_anchor, funding_code)
    source = source.replace("no funding curve assigned", "daily proxy funding curves requested")

    # Capture actual account financing without changing trading or shared statistics.
    account_anchor = "        self.stats.sample(now,nav,self.gross_reserved())"
    account_code = """        if isinstance(ab,dict):
            finance = {k:v for k,v in ab.items() if 'financ' in str(k).lower() or 'funding' in str(k).lower() or 'swap' in str(k).lower()}
            self._native_funding = finance
            if getattr(self,'_last_native_funding',None)!=finance or (now.month==12 and now.day==31 and now.hour==23):
                self._last_native_funding = dict(finance)
                self.log('FUNDING_NATIVE_R5 '+json.dumps(dict(asof=str(now),fields=finance,nav=nav),default=str,separators=(',',':')))
        self.stats.sample(now,nav,self.gross_reserved())"""
    if source.count(account_anchor)!=1:
        raise RuntimeError("Funding account anchor mismatch")
    source = source.replace(account_anchor,account_code)
    report_anchor = "            report=self.stats.snapshot(self.now,nav,states,self.counts,trigger)"
    if source.count(report_anchor)!=1:
        raise RuntimeError("Funding statistics anchor mismatch")
    source = source.replace(report_anchor, report_anchor+"\n            report['funding_native_fields']=getattr(self,'_native_funding',{})")
    # Observe account fields and mark-based funding requirements without modifying orders.
    sample_anchor = "        self.stats.sample(now,nav,self.gross_reserved())"
    sample_code = """        if isinstance(ab,dict) and nav is not None:
            cap=getattr(self,'_capital_audit',None)
            if cap is None:
                cap=self._capital_audit=dict(samples=0,fields={},max_theoretical_required_nav=0.0,
                    max_theoretical_shortfall_usd=0.0,shortfall_samples=0,stale_mark_samples=0)
            cap['samples']+=1
            for k,v in ab.items():
                if any(x in str(k).lower() for x in ('margin','balance','borrow','loan','interest','financ','nav')):
                    try:
                        v=float(v)
                        if not isfinite(v): continue
                    except (TypeError,ValueError):
                        continue
                    f=cap['fields'].setdefault(str(k),dict(min=v,max=v,last=v))
                    f.update(min=min(f['min'],v),max=max(f['max'],v),last=v)
            spot_gross=future_gross=0.0
            stale=False
            for p in self.active_pairs():
                for leg in p['legs'].values():
                    qty=sum(lot['qty'] for lot in leg['lots'].values() if not lot['closed'])
                    if not qty: continue
                    q=self.quotes.get(leg['symbol'])
                    if not q or not self.fresh(leg['symbol']): stale=True
                    mark=q['mid'] if q else leg['estimate']
                    if leg['side']==1: spot_gross+=qty*mark
                    else: future_gross+=qty*mark
            if stale: cap['stale_mark_samples']+=1
            required=spot_gross+future_gross/PROBE_LEVERAGE
            shortfall=max(0.0,required-nav)
            cap['max_theoretical_required_nav']=max(cap['max_theoretical_required_nav'],required/nav)
            cap['max_theoretical_shortfall_usd']=max(cap['max_theoretical_shortfall_usd'],shortfall)
            if shortfall>0: cap['shortfall_samples']+=1
        self.stats.sample(now,nav,self.gross_reserved())"""
    if source.count(sample_anchor)!=1:
        raise RuntimeError("Capital audit anchor mismatch")
    source=source.replace(sample_anchor,sample_code.replace("PROBE_LEVERAGE",str(leverage)))
    summary_anchor="            report['funding_native_fields']=getattr(self,'_native_funding',{})"
    if source.count(summary_anchor)!=1:
        raise RuntimeError("Capital audit report anchor mismatch")
    source=source.replace(summary_anchor,summary_anchor+"\n            report['capital_audit']=getattr(self,'_capital_audit',{})")
    compile(source, "a16_crypto_basis_v8_1_nextbar_costtp_cap50.py", "exec")
    user = os.environ.get("ALGOGENE_USER_ID", "").strip()
    key = os.environ.get("ALGOGENE_API_KEY", "").strip()
    secrets = (user, key)
    st = settings(window, leverage)
    run = {"experiment": "R5-04B", "leverage": leverage, "pair_gross_cap": .40*leverage, "total_gross_cap": .50*leverage, "pair_risk_cap": .0025*leverage, "window": window, "status": "NOT_RUN",
           "created_from_commit": os.environ.get("GITHUB_SHA"),
           "github_run_id": os.environ.get("GITHUB_RUN_ID"),
           "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
           "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
           "requested_settings": st, "backtest_id": None, "task_id": None,
           "platform_responses": {}, "errors": [],
           "notes": ["Platform fixed-cost parameter omitted; fees assessed separately as percentage of executed notional.",
                     "Annualized daily Binance proxy curves (daily sum x365) requested for BTCUSDM and ETHUSDM. Daily settlement/date alignment is approximate and may introduce timing bias. Platform financing is already included in native NAV if binding succeeds; do not add it again. Closed price-PnL statistics exclude Funding.",
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
    parser.add_argument("--leverage", type=int, choices=[2,3], required=True)
    a = parser.parse_args()
    return execute(a.window, a.leverage)


if __name__ == "__main__":
    sys.exit(main())

