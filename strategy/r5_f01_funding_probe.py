"""Backtest only. Fixed 1 BTC short, no dynamic sizing. Real uploaded daily curve."""
from AlgoAPI import AlgoAPIUtil, AlgoAPI_Backtest
import json

ENABLE_FUNDING = False
SYMBOL = 'BTCUSDM'
CURVE = 'BINANCE_BTCUSDT_USDM_FUNDING_DAILY_APPROX'

class AlgoEvent:
    def __init__(self):
        self.sent = False
        self.filled = False
        self.last = None

    def log(self, tag, payload):
        self.evt.consoleLog(tag+' '+json.dumps(payload,default=str,sort_keys=True))

    def start(self, mEvt):
        self.evt = AlgoAPI_Backtest.AlgoEvtHandler(self,mEvt)
        spec = self.evt.getContractSpec(SYMBOL)
        if float(spec.get('contractSize',0)) != 1:
            raise RuntimeError('Probe requires contractSize=1')
        self.log('PROBE_SPEC',spec)
        if ENABLE_FUNDING:
            result = self.evt.setFundingCurve(instrument=SYMBOL,curve_name=CURVE)
            self.log('PROBE_BIND',{'curve':CURVE,'result':repr(result)})
            if result is False or (isinstance(result,dict) and result.get('status') is False):
                raise RuntimeError('Funding binding rejected')
        self.evt.start()

    def on_bulkdatafeed(self,isSync,bd,ab):
        if not isinstance(bd,dict):
            return
        q=bd.get(SYMBOL)
        if not isinstance(q,dict):
            return
        t=str(q.get('timestamp'))
        if t==self.last:
            return
        self.last=t
        self.log('PROBE_ACCOUNT',{'time':t,'account':ab,'bid':q.get('bidPrice'),'ask':q.get('askPrice'),'filled':self.filled})
        if not self.sent and q.get('bidPrice') and q.get('askPrice'):
            self.sent=True
            o=AlgoAPIUtil.OrderObject()
            o.instrument=SYMBOL
            o.orderRef='F01-FIXED-SHORT'
            o.openclose='open'
            o.buysell=-1
            o.ordertype=0
            o.volume=1.0
            self.evt.sendOrder(o)

    def on_orderfeed(self,of):
        d={k:getattr(of,k,None) for k in ('instrument','timestamp','status','orderRef','tradeID','openclose','fill_price','fill_volume')}
        self.log('PROBE_FILL',d)
        if str(d['status']).lower()=='success' and d['openclose']=='open':
            self.filled=True

    def on_dailyPLfeed(self,pl):
        self.log('PROBE_DAILY',pl)

    def on_marketdatafeed(self,md,ab): pass
    def on_openPositionfeed(self,op,oo,uo): pass
    def on_newsdatafeed(self,nd): pass
    def on_weatherdatafeed(self,wd): pass
    def on_econsdatafeed(self,ed): pass
    def on_corpAnnouncement(self,ca): pass
