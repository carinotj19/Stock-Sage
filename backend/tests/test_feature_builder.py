import pandas as pd

from app.ml.feature_builder import build_feature_frame


def test_build_feature_frame_contains_expected_features() -> None:
    dates = pd.date_range("2026-01-01", periods=14, freq="D")
    sales_history = pd.DataFrame(
        {
            "date": dates,
            "units": [5, 6, 4, 7, 8, 5, 6, 7, 8, 10, 11, 9, 8, 12],
        }
    )
    price_history = pd.DataFrame(
        {
            "date": [dates[0], dates[4], dates[9]],
            "price": [3.50, 3.75, 4.00],
        }
    )
    stock_history = pd.DataFrame(
        {
            "date": [dates[0], dates[6], dates[13]],
            "on_hand_qty": [100, 85, 70],
        }
    )

    frame = build_feature_frame(sales_history, price_history, stock_history)

    expected_columns = {
        "date",
        "y",
        "lag_1",
        "lag_7",
        "ma_7",
        "day_of_week",
        "week_of_year",
        "month",
        "price",
        "on_hand_qty",
    }
    assert expected_columns.issubset(set(frame.columns))
    assert frame["date"].is_monotonic_increasing
    assert frame[["lag_1", "lag_7", "ma_7", "price", "on_hand_qty"]].isna().sum().sum() == 0

    sixth_day = frame.iloc[5]
    fifth_day = frame.iloc[4]
    assert sixth_day["lag_1"] == fifth_day["y"]

    first_day = frame.iloc[0]
    assert first_day["lag_1"] == 0
    assert first_day["lag_7"] == 0

    assert frame.iloc[-1]["price"] == 4.00
    assert frame.iloc[-1]["on_hand_qty"] == 70

