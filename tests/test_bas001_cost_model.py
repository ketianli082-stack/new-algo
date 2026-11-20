import unittest
from decimal import Decimal
from tools.bas001_cost_model import calculate


class TestCostModel(unittest.TestCase):
    def setUp(self):
        self.trade = {
            "quantity": 1, "spot_open_ask": 100000, "spot_close_bid": 101000,
            "perp_open_bid": 100500, "perp_close_ask": 101100,
            "holding_hours": 72, "funding_rate_annual_pct": 0,
        }

    def test_zero_cost(self):
        d = calculate(self.trade)
        self.assertEqual(Decimal(d["net_pnl_usd"]), Decimal("400"))

    def test_all_percentage(self):
        t = dict(self.trade)
        t["commission_rates"] = {x: 0.0005 for x in (
            "spot_open", "spot_close", "perp_open", "perp_close")}
        t["slippage_rates"] = {x: 0.0001 for x in t["commission_rates"]}
        t["funding_rate_annual_pct"] = 11.94
        d = calculate(t)
        self.assertEqual(Decimal(d["commission_usd"]), Decimal("201.3000"))
        self.assertEqual(Decimal(d["extra_slippage_usd"]), Decimal("40.2600"))
        expected = Decimal("400") - Decimal("201.3") - Decimal("40.26") + Decimal("100500") * Decimal("0.1194") * Decimal(72) / Decimal(8760)
        self.assertAlmostEqual(float(d["net_pnl_usd"]), float(expected), places=8)

    def test_negative_funding(self):
        d = calculate(dict(self.trade, funding_rate_annual_pct="-10"))
        self.assertLess(Decimal(d["net_funding_usd"]), 0)

    def test_financing_percent(self):
        t = dict(self.trade, financing_rate_annual_pct=10, borrowed_usd=100000)
        d = calculate(t)
        self.assertAlmostEqual(float(d["financing_usd"]), 100000 * .10 * 72 / 8760, places=8)

    def test_reject_usd_costs(self):
        with self.assertRaises(ValueError):
            calculate(dict(self.trade, extra_slippage_usd=20, platform_commission_usd=10))

    def test_negative_rate(self):
        with self.assertRaises(ValueError):
            calculate(dict(self.trade, slippage_rates={"spot_open": "-0.0001"}))


if __name__ == "__main__":
    unittest.main()
