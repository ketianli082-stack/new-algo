import unittest

from tools.bas001_cost_model import calculate


class CostModelTests(unittest.TestCase):
    def setUp(self):
        self.trade = {
            "quantity": 1, "spot_open_ask": 100000, "spot_close_bid": 101000,
            "perp_open_bid": 100500, "perp_close_ask": 101100,
        }

    def test_gross_pnl(self):
        result = calculate(self.trade)
        self.assertEqual(result["gross_pnl_usd"], "400")
        self.assertEqual(result["net_pnl_usd"], "400")

    def test_four_leg_fees_and_signed_funding(self):
        trade = dict(self.trade)
        trade["commission_rates"] = {k: "0.0005" for k in (
            "spot_open", "spot_close", "perp_open", "perp_close")}
        trade["net_funding_usd"] = "-30"
        trade["extra_slippage_usd"] = "20"
        trade["financing_usd"] = "5"
        result = calculate(trade)
        self.assertEqual(result["commission_usd"], "201.8000")
        self.assertEqual(result["net_pnl_usd"], "143.2000")

    def test_no_double_commission(self):
        trade = dict(self.trade, platform_commission_usd=100,
                     commission_rates={"spot_open": "0.0005"})
        with self.assertRaises(ValueError):
            calculate(trade)

    def test_negative_funding_can_be_positive_receipt(self):
        trade = dict(self.trade, net_funding_usd=20)
        self.assertEqual(calculate(trade)["net_pnl_usd"], "420")

    def test_negative_cost_disallowed(self):
        with self.assertRaises(ValueError):
            calculate(dict(self.trade, extra_slippage_usd=-2))


if __name__ == "__main__":
    unittest.main()
