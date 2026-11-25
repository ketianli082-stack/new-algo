import json
import unittest

from tools.r5_11a_algogene_history_api import (
    classify_http_error,
    safe_depth_summary,
    sanitize_error_body,
    summarize_bars,
)


class R511AHistoryApiTests(unittest.TestCase):
    def test_summarizes_ohlcv_and_depth_without_credentials(self):
        result = summarize_bars(
            {
                "status": True,
                "res": [
                    {
                        "t": "2025-12-31 22:00:00",
                        "o": 100.0,
                        "h": 102.0,
                        "l": 99.0,
                        "c": 101.0,
                        "v": 1234,
                        "bids": [[100.9, 4.2], [100.8, 2.0]],
                        "asks": [[101.1, 3.1]],
                        "api_key": "must-not-survive",
                    }
                ],
            }
        )
        self.assertEqual(result["bar_count"], 1)
        self.assertEqual(result["volume_fields_present"], ["v"])
        self.assertEqual(result["depth_fields_present"], ["asks", "bids"])
        self.assertNotIn("api_key", result["bar_fields"])
        self.assertNotIn("api_key", result["samples"][0])
        self.assertEqual(result["samples"][0]["bids"]["level_count"], 2)
        self.assertNotIn("value", result["samples"][0]["bids"])

    def test_timestamp_keyed_mapping_is_supported(self):
        result = summarize_bars(
            {"res": {"2025-12-31 22:00:00": {"c": 101, "volume": 22}}}
        )
        self.assertEqual(result["bar_count"], 1)
        self.assertEqual(result["samples"][0]["t"], "2025-12-31 22:00:00")
        self.assertEqual(result["volume_fields_present"], ["volume"])

    def test_malformed_payload_is_bounded(self):
        result = summarize_bars({"status": False, "res": "error text"})
        self.assertFalse(result["api_status"])
        self.assertEqual(result["bar_count"], 0)
        self.assertEqual(result["samples"], [])

    def test_depth_summary_does_not_copy_levels(self):
        result = safe_depth_summary([[1, 2], [3, 4]])
        self.assertEqual(
            result,
            {
                "type": "list",
                "level_count": 2,
                "first_level_width": 2,
                "first_level_numeric": True,
            },
        )

    def test_error_summary_redacts_credentials_and_email(self):
        result = sanitize_error_body(
            '{"status": false, "res": "upgrade plan for me@example.com", '
            '"user": "user-123", "api_key": "key-456"}',
            ("user-123", "key-456"),
        )
        self.assertEqual(result["user"], "[REDACTED]")
        self.assertEqual(result["api_key"], "[REDACTED]")
        self.assertEqual(result["res"], "upgrade plan for [REDACTED_EMAIL]")
        self.assertEqual(
            classify_http_error(400, json.dumps(result)),
            "SUBSCRIPTION_OR_DATA_PLAN",
        )


if __name__ == "__main__":
    unittest.main()
