import unittest
from datetime import datetime, timezone
from decimal import Decimal

from tools.prepare_algogene_funding import daily_curve, normalize_and_validate


class FundingPreparationTests(unittest.TestCase):
    def rows(self):
        values = [
            ("2021-01-01T00:00:00Z", "0.0001"),
            ("2021-01-01T08:00:00Z", "-0.0002"),
            ("2021-01-01T16:00:00Z", "0.0003"),
            ("2021-01-02T00:00:00Z", "0.0001"),
        ]
        result = []
        for timestamp, rate in values:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            result.append({
                "symbol": "BTCUSDT",
                "fundingTime": int(dt.timestamp() * 1000),
                "fundingRate": rate,
                "markPrice": "30000.0",
            })
        return result

    def test_daily_curve_uses_decimal_sum_and_explicit_signs(self):
        raw, report = normalize_and_validate(
            "BTCUSDT",
            self.rows(),
            datetime(2021, 1, 1, tzinfo=timezone.utc),
            datetime(2021, 1, 2, 1, tzinfo=timezone.utc),
        )
        curve = daily_curve(raw)
        self.assertEqual(report["duplicate_timestamps"], 0)
        self.assertEqual(curve[0]["Date"], "2021-01-01")
        self.assertEqual(Decimal(curve[0]["Long"]), Decimal("-0.0002"))
        self.assertEqual(Decimal(curve[0]["Short"]), Decimal("0.0002"))
        self.assertEqual(curve[0]["_events"], 3)

    def test_duplicate_settlement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            normalize_and_validate(
                "BTCUSDT",
                self.rows() + [self.rows()[0]],
                datetime(2021, 1, 1, tzinfo=timezone.utc),
                datetime(2021, 1, 2, 1, tzinfo=timezone.utc),
            )

    def test_gap_over_eight_hours_is_rejected(self):
        rows = self.rows()
        del rows[1]
        with self.assertRaisesRegex(ValueError, "gaps exceed 8 hours"):
            normalize_and_validate(
                "BTCUSDT",
                rows,
                datetime(2021, 1, 1, tzinfo=timezone.utc),
                datetime(2021, 1, 2, 1, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
