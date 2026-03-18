from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import ceil, sqrt

import pandas as pd


@dataclass
class ReorderComputation:
    predicted_stockout_date: date | None
    reorder_point: int
    suggested_qty: int
    confidence_score: float


class ReorderService:
    def compute_safety_stock(self, historical_daily_units: list[float], lead_time_days: int) -> int:
        if not historical_daily_units or lead_time_days <= 0:
            return 0

        series = pd.Series(historical_daily_units, dtype=float)
        std_dev = float(series.std(ddof=0))
        safety = ceil(1.65 * std_dev * sqrt(lead_time_days))
        return max(0, safety)

    def compute_reorder(
        self,
        current_stock: int,
        forecast_frame: pd.DataFrame,
        lead_time_days: int,
        reorder_min_qty: int,
        reorder_multiple: int,
        safety_stock: int,
        recent_actual_daily_units: list[float] | None = None,
        model_wmape_pct: float | None = None,
        confidence_score: float | None = None,
    ) -> ReorderComputation:
        if forecast_frame.empty:
            fallback_conf = 0.0 if confidence_score is None else float(max(0.0, min(1.0, confidence_score)))
            return ReorderComputation(None, reorder_point=safety_stock, suggested_qty=0, confidence_score=fallback_conf)

        safe_lead = max(1, lead_time_days)
        forecast_lead_demand = float(forecast_frame["predicted_units"].head(safe_lead).sum())

        recent_demand_floor = 0.0
        if recent_actual_daily_units:
            recent_series = pd.Series(recent_actual_daily_units, dtype=float).tail(14)
            if not recent_series.empty:
                recent_avg_daily = float(recent_series.mean())
                recent_demand_floor = max(0.0, recent_avg_daily * safe_lead)

        validated_lead_demand = max(forecast_lead_demand, recent_demand_floor)
        wmape_ratio = max(0.0, min(0.6, (model_wmape_pct or 0.0) / 100.0))
        uncertainty_buffer = ceil(validated_lead_demand * wmape_ratio)
        reorder_point = max(0, ceil(validated_lead_demand + max(0, safety_stock) + uncertainty_buffer))

        target_days = safe_lead + 7
        forecast_target_demand = float(forecast_frame["predicted_units"].head(target_days).sum())
        recent_target_floor = recent_demand_floor + max(0.0, recent_demand_floor * (7 / safe_lead))
        validated_target_demand = max(forecast_target_demand, recent_target_floor)
        target_stock = ceil(validated_target_demand + max(0, safety_stock) + uncertainty_buffer)
        suggested = max(0, target_stock - current_stock)

        if suggested > 0:
            suggested = max(suggested, max(1, reorder_min_qty))
            multiple = max(1, reorder_multiple)
            if suggested % multiple != 0:
                suggested = ceil(suggested / multiple) * multiple

        predicted_stockout_date = self._estimate_stockout_date(current_stock, forecast_frame)

        if confidence_score is None:
            final_confidence = 0.75
        else:
            final_confidence = float(max(0.0, min(1.0, confidence_score)))

        return ReorderComputation(
            predicted_stockout_date=predicted_stockout_date,
            reorder_point=reorder_point,
            suggested_qty=suggested,
            confidence_score=final_confidence,
        )

    def _estimate_stockout_date(self, current_stock: int, forecast_frame: pd.DataFrame) -> date | None:
        if current_stock <= 0:
            first_date = forecast_frame.iloc[0]["forecast_date"]
            return first_date

        cumulative_demand = 0.0
        for _, row in forecast_frame.iterrows():
            cumulative_demand += float(row["predicted_units"])
            if cumulative_demand > current_stock:
                return row["forecast_date"]

        return None
