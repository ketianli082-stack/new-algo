import math

import pandas as pd

from tools.r5_11_14_binance_capacity import archive_url, impact_table, normalize_epoch


def test_archive_urls_cover_spot_and_usdm():
    month = pd.Period("2024-01", freq="M")
    assert archive_url("spot", "BTCUSDT", month).endswith(
        "/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2024-01.zip"
    )
    assert archive_url("um", "ETHUSDT", month).endswith(
        "/futures/um/monthly/klines/ETHUSDT/1h/ETHUSDT-1h-2024-01.zip"
    )


def test_normalize_epoch_supports_ms_and_us():
    expected = pd.Timestamp("2025-01-01T00:00:00Z")
    assert normalize_epoch(1735689600000) == expected
    assert normalize_epoch(1735689600000000) == expected


def test_impact_formula_is_square_root_in_participation_and_linear_in_y():
    market = pd.DataFrame(
        [{"venue": "spot", "symbol": "BTCUSDT", "hourly_log_return_sigma": 0.01}]
    )
    result = impact_table(market)
    low = result[(result.participation_assumption == 0.01) & (result.Y_assumption == 0.5)].iloc[0]
    high = result[(result.participation_assumption == 0.01) & (result.Y_assumption == 1.5)].iloc[0]
    assert math.isclose(low.one_way_impact_bp_scenario, 5.0)
    assert math.isclose(high.one_way_impact_bp_scenario, 15.0)
