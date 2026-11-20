import unittest

from tools.algogene_bas001_run import validate_instrument_metadata


class InstrumentMetadataTests(unittest.TestCase):
    def test_observed_valid_response_without_status(self):
        response = {
            "res": {
                "aiprime": {"MT5": {"trade_contract_size": 0.01}},
                "binance": {"symbol": "BTCUSD"},
            }
        }
        self.assertEqual(
            validate_instrument_metadata(response, "BTCUSD"),
            ["aiprime", "binance"],
        )

    def test_explicit_rejection(self):
        with self.assertRaises(RuntimeError):
            validate_instrument_metadata(
                {"status": False, "res": {"binance": {"symbol": "BTCUSD"}}},
                "BTCUSD",
            )

    def test_empty_or_malformed_data(self):
        for payload in ({"res": {}}, {"res": []}, {"res": {"binance": {}}}, {}):
            with self.subTest(payload=payload):
                with self.assertRaises(RuntimeError):
                    validate_instrument_metadata(payload, "BTCUSD")

    def test_explicit_success(self):
        self.assertEqual(
            validate_instrument_metadata(
                {"status": True, "res": {"binance": {"symbol": "ETHUSD"}}},
                "ETHUSD",
            ),
            ["binance"],
        )


if __name__ == "__main__":
    unittest.main()
