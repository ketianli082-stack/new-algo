import unittest
from decimal import Decimal
from tools.bas001_cost_model import calculate
from tools.historical_funding import historical_funding

FIXTURE = "tests/fixtures/funding_synthetic.csv"

class CostModelTests(unittest.TestCase):
    def setUp(self):
        self.trade = {
            "quantity": 1, "spot_open_ask": 100000, "spot_close_bid": 101000,
            "perp_open_bid": 100500, "perp_close_ask": 101100,
            "holding_hours": 25, "funding_history_csv": FIXTURE,
            "perp_symbol": "BTCUSDT",
            "open_time_utc": "2025-01-01T00:00:00+00:00",
            "close_time_utc": "2025-01-02T01:00:00+00:00",
        }

    def test_each_settlement_changes_pnl(self):
        x = historical_funding(
            FIXTURE, "BTCUSDT", self.trade["open_time_utc"],
            self.trade["close_time_utc"], 1)
        self.assertEqual(x["funding_events"], 3)
        self.assertEqual(x["funding_usd"], Decimal("20.19"))

    def test_gross_and_funding(self):
        x = calculate(self.trade)
        self.assertEqual(Decimal(x["gross_pnl_usd"]), Decimal("400"))
        self.assertEqual(Decimal(x["net_funding_usd"]), Decimal("20.19"))
        self.assertEqual(Decimal(x["net_pnl_usd"]), Decimal("420.19"))

    def test_percentage_commission_slippage(self):
        t = dict(self.trade)
        t["commission_rates"] = {k: "0.0005" for k in
            ("spot_open", "spot_close", "perp_open", "perp_close")}
        t["slippage_rates"] = {k: "0.0001" for k in t["commission_rates"]}
        x = calculate(t)
        self.assertEqual(Decimal(x["commission_usd"]), Decimal("201.3000"))
        self.assertEqual(Decimal(x["extra_slippage_usd"]), Decimal("40.2600"))
        self.assertEqual(Decimal(x["net_pnl_usd"]), Decimal("178.6300"))

    def test_no_historical_average_allowed(self):
        with self.assertRaises(ValueError):
            calculate(dict(self.trade, funding_rate_annual_pct=11.94))

    def test_no_missing_funding_data_allowed(self):
        with self.assertRaises(FileNotFoundError):
            calculate(dict(self.trade, funding_history_csv="not-existing.csv"))

    def test_no_duplicate_settlement(self):
        with self.assertRaises(ValueError):
            historical_funding(FIXTURE, "BTCUSDT", "2026-01-01T00:00:00+00:00",
                               "2026-01-02T00:00:00+00:00", 1)

    def test_negative_funding_eth(self):
        x = historical_funding(
            FIXTURE, "ETHUSDT", self.trade["open_time_utc"],
            self.trade["close_time_utc"], 1)
        self.assertEqual(x["funding_events"], 3)
        self.assertEqual(x["funding_usd"], Decimal("-0.3520"))

    def test_reject_platform_and_offline_fees_same_time(self):
        with self.assertRaises(ValueError):
            calculate(dict(self.trade, platform_commission_usd=100,
                           commission_rates={"spot_open": ".0005"}))

if __name__ == "__main__":
    unittest.main()
