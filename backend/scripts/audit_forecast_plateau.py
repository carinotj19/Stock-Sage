from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select

from app.db.models import ForecastRun, Product, ReorderRecommendation
from app.db.session import SessionLocal
from app.jobs.run_forecast_daily import (
    _apply_champion_lock_guardrail,
    _apply_non_mature_guardrail,
    _apply_analog_prior_fallback,
    _baseline_margin_shortfall_wmape_pct,
    _baseline_margin_tolerance_wmape_pct,
    _build_analog_daily_priors,
    _calibrate_confidence,
    _lead_time_days,
    _lead_time_operational_backtest,
    _load_sales_history,
    _load_stock_movements,
    _margin_threshold_for_tier,
    _parse_reason_tokens,
    _recommendation_action,
    _recommendation_gate_reason,
    _resolved_data_tier,
    _sales_recency_days,
)
from app.ml.model_registry import CandidateScore
from app.ml.predict import forecast_product_daily_units_with_diagnostics


# Keep audit output readable by suppressing per-fit cmdstan logs.
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)


def _parse_run_note_map(notes: str | None, key: str) -> dict[str, str]:
    if not notes:
        return {}
    sections = [section.strip() for section in notes.split("|") if section.strip()]
    key_prefix = f"{key}="
    payload = ""
    for section in sections:
        if section.startswith(key_prefix):
            payload = section[len(key_prefix):].strip()
            break
    if not payload or payload == "none":
        return {}
    mapping: dict[str, str] = {}
    for item in payload.split(";"):
        token = item.strip()
        if not token:
            continue
        if ":" not in token:
            mapping[token] = ""
            continue
        sku, reason = token.split(":", 1)
        mapping[sku.strip()] = reason.strip()
    return mapping


def _safe_round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _candidate_top(scores: list[CandidateScore], limit: int = 3) -> list[dict[str, Any]]:
    top = []
    for score in scores[:limit]:
        top.append(
            {
                "model": score.model_name,
                "wmape_pct": _safe_round(score.wmape_pct, 4),
                "lead_time_wmape_pct": _safe_round(score.lead_time_wmape_pct, 4),
                "windows": int(score.windows_evaluated),
            }
        )
    return top


def _default_output_paths(run_id: int) -> tuple[Path, Path]:
    data_dir = Path(__file__).resolve().parents[1] / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / f"forecast_plateau_audit_run{run_id}.csv"
    summary_path = data_dir / f"forecast_plateau_audit_run{run_id}.summary.json"
    return csv_path, summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit forecast fallback/gating root causes per SKU.")
    parser.add_argument("--run-id", type=int, default=None, help="Forecast run id to align persisted recommendations.")
    parser.add_argument("--output-csv", type=str, default=None, help="Output CSV path.")
    parser.add_argument("--output-summary", type=str, default=None, help="Output summary JSON path.")
    args = parser.parse_args()

    with SessionLocal() as db:
        run_id = args.run_id
        if run_id is None:
            run_id = db.scalar(select(ForecastRun.id).order_by(ForecastRun.id.desc()))
        if run_id is None:
            raise RuntimeError("No forecast runs found.")

        run = db.get(ForecastRun, int(run_id))
        if run is None:
            raise RuntimeError(f"Forecast run {run_id} not found.")

        output_csv, output_summary = _default_output_paths(run.id)
        if args.output_csv:
            output_csv = Path(args.output_csv)
        if args.output_summary:
            output_summary = Path(args.output_summary)
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        output_summary.parent.mkdir(parents=True, exist_ok=True)

        products = list(db.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.sku.asc())).all())
        sales_histories = {product.id: _load_sales_history(db, product.id) for product in products}
        stock_movements_map = {product.id: _load_stock_movements(db, product.id) for product in products}
        analog_daily_priors = _build_analog_daily_priors(products, sales_histories)

        rec_rows = db.execute(
            select(
                Product.sku,
                ReorderRecommendation.suggested_qty,
                ReorderRecommendation.confidence_score,
                ReorderRecommendation.predicted_stockout_date,
            )
            .join(ReorderRecommendation, ReorderRecommendation.product_id == Product.id)
            .where(ReorderRecommendation.run_id == run.id)
        ).all()
        rec_map: dict[str, dict[str, Any]] = {
            sku: {
                "suggested_qty": int(suggested_qty or 0),
                "confidence": float(confidence_score) if confidence_score is not None else None,
                "predicted_stockout_date": (
                    predicted_stockout_date.isoformat() if predicted_stockout_date is not None else None
                ),
            }
            for sku, suggested_qty, confidence_score, predicted_stockout_date in rec_rows
        }

        gated_map = _parse_run_note_map(run.notes, "gated")
        fallback_map = _parse_run_note_map(run.notes, "fallback")

        rows: list[dict[str, Any]] = []
        reason_counts: Counter[str] = Counter()
        action_counts: Counter[str] = Counter()
        model_counts: Counter[str] = Counter()
        tier_counts: Counter[str] = Counter()

        for product in products:
            sales_history = sales_histories.get(product.id, pd.DataFrame(columns=["date", "units"]))
            stock_movements = stock_movements_map.get(
                product.id,
                pd.DataFrame(columns=["occurred_at", "qty_delta", "movement_type"]),
            )
            analog_daily_prior = analog_daily_priors.get(product.id)
            lead_time_days = _lead_time_days(db, product)
            result = forecast_product_daily_units_with_diagnostics(
                sales_history,
                horizon_days=run.horizon_days,
                lead_time_days=lead_time_days,
                stock_movements=stock_movements,
            )
            quality = result.diagnostics.quality
            data_tier = _resolved_data_tier(quality)
            tier_counts[data_tier] += 1

            forecast_frame = result.forecast_frame.copy()
            analog_applied = _apply_analog_prior_fallback(
                forecast_frame,
                quality,
                analog_daily_prior,
            )
            (
                lead_wmape,
                baseline_wmape,
                lead_time_model_win_count,
                lead_time_windows_evaluated,
            ) = _lead_time_operational_backtest(
                sales_history,
                stock_movements,
                lead_time_days,
                analog_daily_prior=analog_daily_prior,
            )
            history_lag_days, days_since_last_sale = _sales_recency_days(sales_history)
            confidence = _calibrate_confidence(
                result.diagnostics.selected_score,
                quality,
                lead_time_wmape_pct=lead_wmape,
                lead_time_baseline_wmape_pct=baseline_wmape,
                lead_time_model_win_count=lead_time_model_win_count,
                lead_time_windows_evaluated=lead_time_windows_evaluated,
                history_lag_days=history_lag_days,
                days_since_last_sale=days_since_last_sale,
            )
            gate_reason = _recommendation_gate_reason(
                result.diagnostics.selected_score,
                quality,
                confidence,
                lead_time_wmape_pct=lead_wmape,
                lead_time_baseline_wmape_pct=baseline_wmape,
                lead_time_model_win_count=lead_time_model_win_count,
                lead_time_windows_evaluated=lead_time_windows_evaluated,
                history_lag_days=history_lag_days,
                days_since_last_sale=days_since_last_sale,
            )
            tokens = _parse_reason_tokens(gate_reason)
            action = _recommendation_action(tokens)
            tokens, action = _apply_champion_lock_guardrail(
                tokens,
                action=action,
                lead_time_model_win_count=lead_time_model_win_count,
                lead_time_windows_evaluated=lead_time_windows_evaluated,
            )
            tokens, action = _apply_non_mature_guardrail(
                tokens,
                action=action,
                quality=quality,
                sales_history=sales_history,
                history_lag_days=history_lag_days,
            )
            gate_reason = ",".join(sorted(tokens)) if tokens else None
            for token in tokens:
                reason_counts[token] += 1
            action_counts[action] += 1

            selected_model_name = result.diagnostics.selected_model_name
            model_counts[selected_model_name] += 1
            threshold_ratio = _margin_threshold_for_tier(data_tier)

            baseline_ratio = None
            baseline_win_ratio = None
            required_wmape = None
            shortfall_wmape = None
            tolerance_wmape = None
            if lead_wmape is not None and baseline_wmape is not None and baseline_wmape > 0:
                baseline_ratio = float(lead_wmape / baseline_wmape)
                if lead_time_windows_evaluated > 0:
                    baseline_win_ratio = float(lead_time_model_win_count / lead_time_windows_evaluated)
                required_wmape = float(baseline_wmape * threshold_ratio)
                shortfall_wmape = _baseline_margin_shortfall_wmape_pct(
                    float(lead_wmape),
                    float(baseline_wmape),
                    data_tier,
                )
                tolerance_wmape = _baseline_margin_tolerance_wmape_pct(float(baseline_wmape), data_tier)

            persisted = rec_map.get(product.sku, {})
            rows.append(
                {
                    "sku": product.sku,
                    "data_tier": data_tier,
                    "quality_status": quality.status,
                    "history_days": int(quality.history_days),
                    "non_zero_days": int(quality.non_zero_days),
                    "non_zero_ratio": _safe_round(quality.non_zero_ratio, 4),
                    "lead_time_days": int(lead_time_days),
                    "selected_model": selected_model_name,
                    "selected_score_wmape_pct": _safe_round(result.diagnostics.selected_score.wmape_pct, 4),
                    "selected_score_lead_time_wmape_pct": _safe_round(
                        result.diagnostics.selected_score.lead_time_wmape_pct, 4
                    ),
                    "lead_time_wmape_pct": _safe_round(lead_wmape, 4),
                    "lead_time_baseline_wmape_pct": _safe_round(baseline_wmape, 4),
                    "lead_time_model_wins": int(lead_time_model_win_count),
                    "lead_time_windows_evaluated": int(lead_time_windows_evaluated),
                    "lead_time_model_win_ratio": _safe_round(baseline_win_ratio, 4),
                    "baseline_ratio": _safe_round(baseline_ratio, 4),
                    "baseline_threshold_ratio": _safe_round(threshold_ratio, 4),
                    "required_wmape_pct": _safe_round(required_wmape, 4),
                    "baseline_shortfall_wmape_pct": _safe_round(shortfall_wmape, 4),
                    "baseline_tolerance_wmape_pct": _safe_round(tolerance_wmape, 4),
                    "computed_confidence": _safe_round(confidence, 4),
                    "computed_gate_reason": gate_reason,
                    "computed_action": action,
                    "persisted_suggested_qty": persisted.get("suggested_qty"),
                    "persisted_confidence": _safe_round(persisted.get("confidence"), 4),
                    "persisted_stockout_date": persisted.get("predicted_stockout_date"),
                    "persisted_fallback_reason": fallback_map.get(product.sku),
                    "persisted_gated_reason": gated_map.get(product.sku),
                    "analog_daily_prior": _safe_round(analog_daily_prior, 4),
                    "analog_prior_applied": bool(analog_applied),
                    "candidate_top3_json": json.dumps(_candidate_top(result.diagnostics.candidate_scores), separators=(",", ":")),
                }
            )

        frame = pd.DataFrame(rows).sort_values(
            by=["computed_action", "baseline_shortfall_wmape_pct", "sku"],
            ascending=[True, False, True],
        )
        frame.to_csv(output_csv, index=False)

        summary = {
            "run_id": run.id,
            "model_version": run.model_version,
            "notes": run.notes,
            "sku_count": len(rows),
            "computed_reason_counts": dict(sorted(reason_counts.items())),
            "computed_action_counts": dict(sorted(action_counts.items())),
            "selected_model_counts": dict(sorted(model_counts.items())),
            "data_tier_counts": dict(sorted(tier_counts.items())),
            "persisted_fallback_skus": sorted(fallback_map.keys()),
            "persisted_gated_skus": sorted(gated_map.keys()),
            "output_csv": str(output_csv),
        }
        output_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        print(f"run_id={run.id}")
        print(f"output_csv={output_csv}")
        print(f"output_summary={output_summary}")
        print("computed_reason_counts:")
        for key, value in sorted(reason_counts.items()):
            print(f"  {key}={value}")
        print("computed_action_counts:")
        for key, value in sorted(action_counts.items()):
            print(f"  {key}={value}")
        print("selected_model_counts:")
        for key, value in sorted(model_counts.items()):
            print(f"  {key}={value}")


if __name__ == "__main__":
    main()
