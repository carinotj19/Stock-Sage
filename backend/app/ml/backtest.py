from __future__ import annotations

import numpy as np
import pandas as pd


def train_validation_split(features: pd.DataFrame, validation_days: int = 30) -> tuple[pd.DataFrame, pd.DataFrame]:
    if validation_days <= 0:
        raise ValueError("validation_days must be positive")

    if len(features) <= validation_days:
        raise ValueError("Not enough rows for requested validation window")

    split_at = len(features) - validation_days
    train_df = features.iloc[:split_at].copy()
    valid_df = features.iloc[split_at:].copy()
    return train_df, valid_df


def mean_absolute_error(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def mean_absolute_percentage_error(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    safe_true = np.where(y_true == 0, 1, y_true)
    return float(np.mean(np.abs((y_true - y_pred) / safe_true)) * 100)

