"""Inject deterministic execution stress into the frozen P80 runner."""
def apply_stress(source, experiment):
    def replace(old,new):
        nonlocal source
        if source.count(old)!=1:
            raise RuntimeError("Stress anchor mismatch: "+old[:80])
        source=source.replace(old,new)
    if experiment.startswith("R3-11"):
        delay=1 if experiment.endswith("A") else 2
        start=source.index("        for key in ('S','F'):\n")
        end=source.index("    def request_exit",start)
        block=source[start:end]
        block=block.replace("        for key in ('S','F'):", "        self.send_stress_leg(p,'S')\n        self.finish_if_flat(p)\n\n    def send_stress_leg(self,p,key):\n        pid=p['id']\n        for key in (key,):")
        block=block.replace("order.volume = qty","order.volume = leg['requested']")
        source=source[:start]+block+source[end:]
        replace("            if p['phase']=='OPENING' and age>=OPEN_TIMEOUT_HOURS:", """            if p['phase']=='OPENING' and p['legs']['F']['state']=='queued':
                if age<${delay}:
                    continue
                if p['legs']['S']['state']=='filled' and self.fresh(p['legs']['F']['symbol']):
                    self.counts['stress_delayed_hedges']+=1
                    self.log('STRESS_HEDGE_SEND',p['id'],now,'delay_hours',age)
                    self.send_stress_leg(p,'F')
                    continue
                if age<${delay}+OPEN_TIMEOUT_HOURS:
                    continue
            if p['phase']=='OPENING' and age>=${delay}+OPEN_TIMEOUT_HOURS:""".replace("${delay}",str(delay)))
    else:
        hours=6 if experiment.endswith("A") else 24
        replace("        self.quotes=parsed\n        for p in list(self.active_pairs()):", """        # One deterministic portfolio-wide interruption per UTC month, starting
        # at the first subsequent feed with an already active hedge.
        month_key=now.strftime('%Y-%m')
        until=getattr(self,'_stress_until',None)
        if until is not None and now<until:
            self.quotes={}
            self.counts['stress_outage_feed_callbacks']+=1
            return
        if until is not None:
            self.log('STRESS_OUTAGE_END',now)
            self._stress_until=None
        if getattr(self,'_stress_month',None)!=month_key and any(p['phase']=='ACTIVE' for p in self.active_pairs()):
            self._stress_month=month_key
            self._stress_until=now+HOUR*${hours}
            self.counts['stress_outages']+=1
            self.log('STRESS_OUTAGE_START',now,'until',self._stress_until)
            self.quotes={}
            return
        self.quotes=parsed
        for p in list(self.active_pairs()):""".replace("${hours}",str(hours)))
        replace("    def try_closes(self,p):\n","    def try_closes(self,p):\n        if getattr(self,'_stress_until',None) is not None and self.now<self._stress_until:\n            return\n")
    compile(source,"stress_strategy.py","exec")
    return source
