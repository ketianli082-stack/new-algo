"""Read-only trade accounting for ALGOGENE V8 research.
Embedded into submitted strategy by the runner; no exchange orders.
All fee/slippage figures are scenarios, not platform debits.
"""
import json
import math

class TradeStatistics:
    def __init__(self):
        self.fills = {}
        self.closed = {}
        self.completed = {}
        self.groups = {}
        self.months = {}
        self.reasons = {}
        self.worst = []
        self.samples = 0
        self.util_sum = 0.0
        self.util_max = 0.0
        self.last_sample = None
        self.fee_rate = 0.0005
        self.slip_rate = 0.0001

    def fill(self, pid, symbol, tid, kind, qty, price, pnl=0.0):
        key = (str(tid), kind)
        if key not in self.fills:
            self.fills[key] = (pid, symbol, qty*price, pnl)
        if kind == 'close':
            self.closed[str(tid)] = (pid, pnl)

    @staticmethod
    def add(table, key, gross, fee, slip, hours, hedged):
        x = table.setdefault(key, dict(pairs=0, hedged_pairs=0, gross=0.0,
            fee=0.0, slippage=0.0, net=0.0, net_wins=0, gross_wins=0,
            hours=0.0, max_hours=0.0, notional=0.0))
        net = gross-fee-slip
        x['pairs'] += 1
        x['hedged_pairs'] += int(hedged)
        x['gross'] += gross
        x['fee'] += fee
        x['slippage'] += slip
        x['net'] += net
        x['net_wins'] += int(net>0)
        x['gross_wins'] += int(gross>0)
        x['hours'] += hours
        x['max_hours'] = max(x['max_hours'], hours)
        return x

    def finish(self, p, now):
        pid = p['id']
        if pid in self.completed:
            return
        rows = [v for v in self.fills.values() if v[0]==pid]
        if not rows:
            return
        gross = sum(lot.get('pnl',0.0) for leg in p['legs'].values()
                    for lot in leg['lots'].values())
        notional = sum(v[2] for v in rows)
        fee, slip = notional*self.fee_rate, notional*self.slip_rate
        hours = max(0.0,(now-p['created']).total_seconds()/3600)
        hedged = bool(p['was_hedged'])
        reason = str(p['reason'] or 'UNKNOWN')
        month = now.strftime('%Y-%m')
        self.completed[pid] = (gross, fee, slip, hours, notional, hedged)
        for table,key in ((self.groups,p['group']),(self.months,month),(self.reasons,reason)):
            self.add(table,key,gross,fee,slip,hours,hedged)['notional'] += notional
        net = gross-fee-slip
        if net < 0:
            self.worst.append(dict(id=pid,group=p['group'],reason=reason,
                closed_at=now.isoformat(),gross=gross,net=net,fee=fee,
                slippage=slip,hours=hours))
            self.worst = sorted(self.worst,key=lambda x:x['net'])[:10]

    def sample(self, now, nav, reserved):
        if nav is None or nav<=0 or self.last_sample==now:
            return
        self.last_sample = now
        u = reserved/nav
        if math.isfinite(u):
            self.samples += 1
            self.util_sum += u
            self.util_max = max(self.util_max,u)

    def snapshot(self, now, nav, active, counters, trigger):
        rows = list(self.completed.values())
        all_notional = sum(v[2] for v in self.fills.values())
        realized_leg_pnl = sum(v[1] for v in self.closed.values())
        gross = sum(v[0] for v in rows)
        fee = sum(v[1] for v in rows)
        slip = sum(v[2] for v in rows)
        return dict(schema=1,asof=now.isoformat(),trigger=trigger,
            final_callback=False,platform_nav=nav,fee_rate=self.fee_rate,
            slippage_rate=self.slip_rate,funding=None,
            fills=len(self.fills),closed_legs=len(self.closed),
            executed_notional=all_notional,realized_leg_pnl=realized_leg_pnl,
            all_fill_fee=all_notional*self.fee_rate,
            all_fill_slippage=all_notional*self.slip_rate,
            completed_pairs=len(rows),hedged_pairs=sum(v[5] for v in rows),
            completed_gross=gross,completed_fee=fee,completed_slippage=slip,
            completed_net=gross-fee-slip,
            net_wins=sum(v[0]-v[1]-v[2]>0 for v in rows),
            gross_wins=sum(v[0]>0 for v in rows),
            average_hours=sum(v[3] for v in rows)/len(rows) if rows else None,
            groups=self.groups,months=self.months,reasons=self.reasons,worst=self.worst,
            active=active,counters=dict(counters),util_samples=self.samples,
            mean_reserved_gross_nav=self.util_sum/self.samples if self.samples else None,
            max_reserved_gross_nav=self.util_max if self.samples else None)
