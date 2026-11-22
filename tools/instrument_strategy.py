"""Instrument strategy source at submission without editing frozen originals."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def instrument(source):
    module = (ROOT / "tools/trade_statistics.py").read_text(encoding="utf-8")
    # Module follows original imports; preserve original future/docstring semantics.
    replacements = [
        ("class AlgoEvent:", module + "\n\nclass AlgoEvent:"),
        ("        self.contracts = {}", "        self.stats = TradeStatistics()\n        self.contracts = {}"),
        ("            self.log('LEG_FILL'", "            self.stats.fill(p['id'],leg['symbol'],trade_id,'open',qty,price)\n            self.log('LEG_FILL'"),
        ("            self.log('LEG_CLOSED'", "            self.stats.fill(p['id'],leg['symbol'],trade_id,'close',qty,price,lot['pnl'])\n            self.log('LEG_CLOSED'"),
        ("            self.log('PAIR_DONE'", "            self.stats.finish(p,self.now)\n            self.log('PAIR_DONE'"),
        ("        month=now.strftime('%Y-%m')", "        self.stats.sample(now,nav,self.gross_reserved())\n        month=now.strftime('%Y-%m')"),
        ("        self.log('AUDIT V8.1'", """        if trigger=='YEAR_END_QUOTE':
            report=self.stats.snapshot(self.now,nav,states,self.counts,trigger)
            report['halt_entries']=self.halt_entries
            report['active_mark_pnl']={p['id']:self.liquidation_pnl(p) for p in self.active_pairs()}
            # Small separate records avoid a single huge console line.
            for part in ('groups','months','reasons','worst'):
                data=report.pop(part)
                if isinstance(data,dict):
                    for key,value in sorted(data.items()):
                        self.log('TRADE_STATS_V1 '+json.dumps(dict(asof=report['asof'],part=part,key=key,data=value),separators=(',',':')))
                else:
                    for i,value in enumerate(data):
                        self.log('TRADE_STATS_V1 '+json.dumps(dict(asof=report['asof'],part=part,key=str(i),data=value),separators=(',',':')))
                report[part+'_records']=len(data)
            self.log('TRADE_STATS_V1 '+json.dumps(dict(asof=report['asof'],part='summary',key='total',data=report),separators=(',',':')))
        self.log('AUDIT V8.1'"""),
    ]
    for old,new in replacements:
        if source.count(old)!=1:
            raise ValueError("Statistics hook mismatch: "+old[:80])
        source=source.replace(old,new)
    compile(source,"instrumented_strategy.py","exec")
    return source
