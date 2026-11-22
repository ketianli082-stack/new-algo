import unittest
from datetime import datetime,timedelta
from tools.trade_statistics import TradeStatistics
from tools.instrument_strategy import instrument, ROOT
from tools.extract_trade_statistics import extract
from tempfile import TemporaryDirectory
from pathlib import Path
import json

class StatsTests(unittest.TestCase):
    def test_all_versions_compile(self):
        for path in sorted((ROOT/'strategy').glob('crypto_basis_v8*.py')):
            self.assertIn('self.stats.finish',instrument(path.read_text(encoding='utf-8')))
    def test_cost_and_duplicate(self):
        s=TradeStatistics()
        for _ in range(2):
            s.fill('p','BTCUSD',1,'open',1,10000)
            s.fill('p','BTCUSD',1,'close',1,10100,100)
        t=datetime(2025,1,1)
        p=dict(id='p',group='BTC',created=t,was_hedged=False,reason='UNWIND',
               legs={'S':{'lots':{1:{'pnl':100}}}})
        s.finish(p,t+timedelta(hours=2))
        s.finish(p,t+timedelta(hours=2))
        x=s.snapshot(t,None,[],{},'test')
        self.assertEqual(x['fills'],2)
        self.assertEqual(x['completed_pairs'],1)
        self.assertAlmostEqual(x['completed_net'],87.94)
    def test_missing_export(self):
        with TemporaryDirectory() as d:
            self.assertEqual(extract([],Path(d)),'MISSING')
            self.assertEqual(json.loads((Path(d)/'trade_statistics.json').read_text())['status'],'MISSING')
