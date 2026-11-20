import unittest
from decimal import Decimal
from tools.annual_funding import annual_funding
from tools.bas001_cost_model import calculate

FIXTURE = "tests/fixtures/annual_funding_synthetic.csv"


class BAS001CostTests(unittest.TestCase):
    def setUp(self):
        self.trade = {
            "quantity": 1,
            "spot_open_ask": 100000,
            "spot_close_bid": 101000,
            "perp_open_bid": 100500,
            "perp_close_ask": 101100,
            "perp_symbol": "BTCUSDT",
            "annual_funding_csv": FIXTURE,
            "open_time_utc": "2024-12-31T12:00:00+00:00",
            "close_time_utc": "2025-01-01T12:00:00+00:00"
        }

    def test_cross_year_segments(self):
        x = annual_funding(FIXTURE, "BTCUSDT",
                           self.trade["open_time_utc"],
                           self.trade["close_time_utc"], 1, 100500)
        self.assertEqual(len(x["segments"]), 2)
        self.assertEqual([s["year"] for s in x["segments"]], [2024, 2025])
        expected = Decimal("100500") * (Decimal("0.12") * 12
                                        + Decimal("-0.06") * 12) / 8760
        self.assertEqual(x["funding_usd"], expected)

    def test_separate_btc_eth_rates(self):
        btc = annual_funding(FIXTURE, "BTCUSDT",
                             "2025-01-01T00:00:00+00:00",
                             "2025-01-02T00:00:00+00:00", 1, 100000)
        eth = annual_funding(FIXTURE, "ETHUSDT",
                             "2025-01-01T00:00:00+00:00",
                             "2025-01-02T00:00:00+00:00", 1, 100000)
        self.assertLess(btc["funding_usd"], 0)
        self.assertGreater(eth["funding_usd"], 0)

    def test_two_net_return_fields(self):
        out = calculate(self.trade)
        self.assertEqual(Decimal(out["gross_pnl_usd"]), Decimal("400"))
        self.assertEqual(Decimal(out["net_pnl_ex_funding_usd"]), Decimal("400"))
        self.assertEqual(Decimal(out["net_pnl_including_estimated_funding_usd"]),
                         Decimal(out["net_pnl_ex_funding_usd"])
                         + Decimal(out["estimated_funding_usd"]))
        self.assertEqual(len(out["funding_year_segments"]), 2)

    def test_percentage_costs(self):
        t = dict(self.trade)
        t["commission_rates"] = {k: "0.0005" for k in
            ("spot_open", "spot_close", "perp_open", "perp_close")}
        t["slippage_rates"] = {k: "0.0001" for k in t["commission_rates"]}
        out = calculate(t)
        self.assertEqual(Decimal(out["commission_usd"]), Decimal("201.3000"))
        self.assertEqual(Decimal(out["extra_slippage_usd"]), Decimal("40.2600"))
        self.assertEqual(Decimal(out["net_pnl_ex_funding_usd"]), Decimal("158.4400"))

    def test_missing_year_fails(self):
        t = dict(self.trade, open_time_utc="2023-12-31T12:00:00+00:00")
        with self.assertRaises(ValueError):
            calculate(t)

    def test_missing_data_fails(self):
        with self.assertRaises(FileNotFoundError):
            calculate(dict(self.trade, annual_funding_csv="missing.csv"))

    def test_legacy_funding_input_rejected(self):
        with self.assertRaises(ValueError):
            calculate(dict(self.trade, funding_rate_annual_pct=11.94))
        with self.assertRaises(ValueError):
            calculate(dict(self.trade, funding_history_csv="old.csv"))

    def test_no_double_commission(self):
        with self.assertRaises(ValueError):
            calculate(dict(self.trade, platform_commission_usd=10))

if __name__ == "__main__":
    unittest.main()
