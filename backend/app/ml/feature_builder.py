from __future__ import annotations

import pandas as pd


def _normalize_daily_frame(data: pd.DataFrame, date_col: str, value_col: str, output_col: str) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame(columns=["date", output_col])

    frame = data[[date_col, value_col]].copy()
    frame[date_col] = pd.to_datetime(frame[date_col]).dt.normalize()
    frame = frame.groupby(date_col, as_index=False)[value_col].sum()
    frame = frame.rename(columns={date_col: "date", value_col: output_col})
    return frame


def build_feature_frame(
    sales_history: pd.DataFrame,
    price_history: pd.DataFrame | None = None,
    stock_history: pd.DataFrame | None = None,
) -> pd.DataFrame:
    sales = _normalize_daily_frame(sales_history, "date", "units", "y")
    if sales.empty:
        raise ValueError("sales_history must contain at least one row")

    full_dates = pd.date_range(start=sales["date"].min(), end=sales["date"].max(), freq="D")
    features = pd.DataFrame({"date": full_dates})
    features = features.merge(sales, on="date", how="left")
    features["y"] = features["y"].fillna(0).astype(float)

    if price_history is not None and not price_history.empty:
        prices = _normalize_daily_frame(price_history, "date", "price", "price")
        features = features.merge(prices, on="date", how="left")
        features["price"] = features["price"].ffill().bfill().fillna(0.0)
    else:
        features["price"] = 0.0

    if stock_history is not None and not stock_history.empty:
        stock = _normalize_daily_frame(stock_history, "date", "on_hand_qty", "on_hand_qty")
        features = features.merge(stock, on="date", how="left")
        features["on_hand_qty"] = features["on_hand_qty"].ffill().bfill().fillna(0.0)
    else:
        features["on_hand_qty"] = 0.0

    # Lag and rolling windows are shifted to avoid using same-day target values.
    features["lag_1"] = features["y"].shift(1)
    features["lag_7"] = features["y"].shift(7)
    features["ma_7"] = features["y"].shift(1).rolling(window=7, min_periods=1).mean()

    calendar = features["date"].dt.isocalendar()
    features["day_of_week"] = features["date"].dt.dayofweek
    features["week_of_year"] = calendar.week.astype(int)
    features["month"] = features["date"].dt.month

    numeric_fill_cols = ["lag_1", "lag_7", "ma_7", "price", "on_hand_qty"]
    features[numeric_fill_cols] = features[numeric_fill_cols].fillna(0.0)

    return features

