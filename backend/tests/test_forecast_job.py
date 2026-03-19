from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Base,
    ForecastRun,
    InventoryBalance,
    Product,
    ReorderRecommendation,
    SalesItem,
    SalesTransaction,
    SkuForecast,
    Supplier,
)
from app.jobs.run_forecast_daily import (
    _apply_champion_lock_guardrail,
    _calibrate_confidence,
    _parse_reason_tokens,
    _recommendation_action,
    _recommendation_fallback_reason,
    _recommendation_gate_reason,
    run_daily_forecast,
)
from app.ml.model_registry import CandidateScore
from app.ml.predict import ForecastDataQuality


TEST_DATABASE_URL = "sqlite:///./data/test_forecast_job.db"


def _build_test_engine():
    return create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})


def _seed_sales_history(db: Session, product_id: int) -> None:
    base_date = datetime.now(timezone.utc) - timedelta(days=14)
    for i in range(14):
        tx = SalesTransaction(
            receipt_no=f"R-FC-{i}",
            sold_at=base_date + timedelta(days=i),
            total_amount=10.00,
            payment_method="cash",
        )
        db.add(tx)
        db.flush()
        db.add(
            SalesItem(
                sales_transaction_id=tx.id,
                product_id=product_id,
                qty=(i % 4) + 1,
                unit_sell_price=2.50,
                line_total=((i % 4) + 1) * 2.50,
            )
        )


def test_forecast_job_persists_forecasts_and_reorders() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        supplier = Supplier(name="Forecast Supplier", lead_time_days_default=5)
        db.add(supplier)
        db.flush()

        product = Product(
            sku="SKU-FC-1",
            name="Forecast Item",
            supplier_id=supplier.id,
            cost_price=1.0,
            sell_price=2.5,
            reorder_min_qty=5,
            reorder_multiple=5,
            safety_stock=2,
            active=True,
        )
        db.add(product)
        db.flush()

        db.add(InventoryBalance(product_id=product.id, on_hand_qty=40))
        _seed_sales_history(db, product.id)
        db.commit()

        run_id = run_daily_forecast(db=db, horizon_days=10)

        run_count = db.scalar(select(func.count()).select_from(ForecastRun))
        assert run_count == 1
        assert run_id is not None

        forecast_count = db.scalar(select(func.count()).select_from(SkuForecast))
        assert forecast_count == 10

        recommendation_count = db.scalar(select(func.count()).select_from(ReorderRecommendation))
        assert recommendation_count == 1

        recommendation = db.scalars(select(ReorderRecommendation)).first()
        assert recommendation is not None
        assert recommendation.reorder_point >= 0
        assert recommendation.suggested_qty >= 0

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_forecast_job_gates_low_quality_recommendations() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        supplier = Supplier(name="Gate Supplier", lead_time_days_default=5)
        db.add(supplier)
        db.flush()

        product = Product(
            sku="SKU-GATE-1",
            name="Sparse Demand Item",
            supplier_id=supplier.id,
            cost_price=1.0,
            sell_price=2.5,
            reorder_min_qty=5,
            reorder_multiple=5,
            safety_stock=2,
            active=True,
        )
        db.add(product)
        db.flush()

        db.add(InventoryBalance(product_id=product.id, on_hand_qty=1))
        _seed_sales_history(db, product.id)  # 14-day sample should trigger quality gate
        db.commit()

        run_id = run_daily_forecast(db=db, horizon_days=10)
        assert run_id is not None

        recommendation = db.scalars(select(ReorderRecommendation)).first()
        assert recommendation is not None
        assert recommendation.suggested_qty == 0
        assert recommendation.predicted_stockout_date is None
        assert recommendation.confidence_score is not None
        assert recommendation.confidence_score < 0.5

        run = db.scalars(select(ForecastRun).where(ForecastRun.id == run_id)).first()
        assert run is not None
        assert run.notes is not None
        assert "gated=" in run.notes

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_confidence_calibration_uses_backtest_error_and_stability() -> None:
    quality = ForecastDataQuality(
        status="ok",
        history_days=90,
        non_zero_days=45,
        non_zero_ratio=0.5,
        capped_outlier_days=0,
        suspected_stockout_days=0,
        notes=[],
    )
    strong = CandidateScore(
        model_name="Stable",
        mae=0.4,
        mape_pct=18.0,
        wmape_pct=20.0,
        windows_evaluated=4,
        mae_std=0.1,
        mape_std_pct=1.0,
        wmape_std_pct=1.5,
    )
    weak = CandidateScore(
        model_name="Unstable",
        mae=1.4,
        mape_pct=85.0,
        wmape_pct=95.0,
        windows_evaluated=1,
        mae_std=0.8,
        mape_std_pct=20.0,
        wmape_std_pct=25.0,
    )

    strong_conf = _calibrate_confidence(strong, quality)
    weak_conf = _calibrate_confidence(weak, quality)

    assert strong_conf > weak_conf
    assert strong_conf >= 0.55
    assert weak_conf < 0.5


def test_confidence_calibration_penalizes_when_lead_time_model_fails_baseline() -> None:
    quality = ForecastDataQuality(
        status="ok",
        history_days=90,
        non_zero_days=45,
        non_zero_ratio=0.5,
        capped_outlier_days=0,
        suspected_stockout_days=0,
        data_tier="mature",
        effective_history_days=90,
        notes=[],
    )
    score = CandidateScore(
        model_name="Stable",
        mae=0.5,
        mape_pct=22.0,
        wmape_pct=24.0,
        windows_evaluated=4,
        mae_std=0.1,
        mape_std_pct=1.2,
        wmape_std_pct=1.3,
    )

    better_than_baseline = _calibrate_confidence(
        score,
        quality,
        lead_time_wmape_pct=24.0,
        lead_time_baseline_wmape_pct=40.0,
    )
    worse_than_baseline = _calibrate_confidence(
        score,
        quality,
        lead_time_wmape_pct=42.0,
        lead_time_baseline_wmape_pct=30.0,
    )

    assert better_than_baseline > worse_than_baseline
    assert worse_than_baseline < 0.70


def test_confidence_calibration_uses_multi_window_baseline_win_rate() -> None:
    quality = ForecastDataQuality(
        status="ok",
        history_days=90,
        non_zero_days=45,
        non_zero_ratio=0.5,
        capped_outlier_days=0,
        suspected_stockout_days=0,
        data_tier="mature",
        effective_history_days=90,
        notes=[],
    )
    score = CandidateScore(
        model_name="Stable",
        mae=0.5,
        mape_pct=22.0,
        wmape_pct=24.0,
        windows_evaluated=4,
        mae_std=0.1,
        mape_std_pct=1.2,
        wmape_std_pct=1.3,
    )

    mixed_results = _calibrate_confidence(
        score,
        quality,
        lead_time_wmape_pct=42.0,
        lead_time_baseline_wmape_pct=30.0,
        lead_time_model_win_count=2,
        lead_time_windows_evaluated=4,
    )
    strong_loss_results = _calibrate_confidence(
        score,
        quality,
        lead_time_wmape_pct=42.0,
        lead_time_baseline_wmape_pct=30.0,
        lead_time_model_win_count=0,
        lead_time_windows_evaluated=4,
    )

    assert mixed_results > strong_loss_results


def test_confidence_high_only_with_clear_tier_margin_win() -> None:
    quality = ForecastDataQuality(
        status="ok",
        history_days=120,
        non_zero_days=80,
        non_zero_ratio=0.67,
        capped_outlier_days=0,
        suspected_stockout_days=0,
        data_tier="mature",
        effective_history_days=120,
        notes=[],
    )
    score = CandidateScore(
        model_name="Stable",
        mae=0.2,
        mape_pct=12.0,
        wmape_pct=14.0,
        windows_evaluated=5,
        mae_std=0.05,
        mape_std_pct=0.8,
        wmape_std_pct=0.9,
    )

    no_clear_win = _calibrate_confidence(
        score,
        quality,
        lead_time_wmape_pct=29.0,
        lead_time_baseline_wmape_pct=30.0,
    )
    clear_win = _calibrate_confidence(
        score,
        quality,
        lead_time_wmape_pct=24.0,
        lead_time_baseline_wmape_pct=30.0,
    )

    assert no_clear_win < 0.70
    assert clear_win >= 0.70


def test_gate_reason_adds_baseline_not_beaten_signal() -> None:
    quality = ForecastDataQuality(
        status="ok",
        history_days=90,
        non_zero_days=45,
        non_zero_ratio=0.5,
        capped_outlier_days=0,
        suspected_stockout_days=0,
        data_tier="mature",
        effective_history_days=90,
        notes=[],
    )
    score = CandidateScore(
        model_name="Stable",
        mae=0.5,
        mape_pct=22.0,
        wmape_pct=24.0,
        windows_evaluated=4,
        mae_std=0.1,
        mape_std_pct=1.2,
        wmape_std_pct=1.3,
    )

    reason = _recommendation_gate_reason(
        score,
        quality,
        confidence=0.85,
        lead_time_wmape_pct=40.0,
        lead_time_baseline_wmape_pct=30.0,
    )

    assert reason is not None
    assert "baseline_not_beaten" in reason


def test_gate_reason_ignores_baseline_not_beaten_when_multi_window_results_are_mixed() -> None:
    quality = ForecastDataQuality(
        status="ok",
        history_days=90,
        non_zero_days=45,
        non_zero_ratio=0.5,
        capped_outlier_days=0,
        suspected_stockout_days=0,
        data_tier="mature",
        effective_history_days=90,
        notes=[],
    )
    score = CandidateScore(
        model_name="Stable",
        mae=0.5,
        mape_pct=22.0,
        wmape_pct=24.0,
        windows_evaluated=4,
        mae_std=0.1,
        mape_std_pct=1.2,
        wmape_std_pct=1.3,
    )

    reason = _recommendation_gate_reason(
        score,
        quality,
        confidence=0.85,
        lead_time_wmape_pct=40.0,
        lead_time_baseline_wmape_pct=30.0,
        lead_time_model_win_count=2,
        lead_time_windows_evaluated=4,
    )

    assert reason is None


def test_gate_reason_ignores_near_tie_against_tier_margin_target() -> None:
    quality = ForecastDataQuality(
        status="ok",
        history_days=90,
        non_zero_days=45,
        non_zero_ratio=0.5,
        capped_outlier_days=0,
        suspected_stockout_days=0,
        data_tier="mature",
        effective_history_days=90,
        notes=[],
    )
    score = CandidateScore(
        model_name="Stable",
        mae=0.5,
        mape_pct=22.0,
        wmape_pct=24.0,
        windows_evaluated=4,
        mae_std=0.1,
        mape_std_pct=1.2,
        wmape_std_pct=1.3,
    )

    # Mature tier requires <= 0.90 ratio versus baseline.
    # This sample misses the target slightly, but only by 1.9 wMAPE points
    # (within tolerance), so it should not trigger baseline fallback.
    reason = _recommendation_gate_reason(
        score,
        quality,
        confidence=0.65,
        lead_time_wmape_pct=28.9,
        lead_time_baseline_wmape_pct=30.0,
    )

    assert reason is None


def test_gate_reason_ignores_small_mature_shortfall_with_tier_floor_tolerance() -> None:
    quality = ForecastDataQuality(
        status="ok",
        history_days=120,
        non_zero_days=70,
        non_zero_ratio=0.58,
        capped_outlier_days=0,
        suspected_stockout_days=0,
        data_tier="mature",
        effective_history_days=120,
        notes=[],
    )
    score = CandidateScore(
        model_name="Stable",
        mae=0.5,
        mape_pct=22.0,
        wmape_pct=24.0,
        windows_evaluated=4,
        mae_std=0.1,
        mape_std_pct=1.2,
        wmape_std_pct=1.3,
    )

    # Mature threshold target is 34.2 when baseline is 38.0.
    # Shortfall is 3.2, which should stay within mature floor tolerance (3.5).
    reason = _recommendation_gate_reason(
        score,
        quality,
        confidence=0.65,
        lead_time_wmape_pct=37.4,
        lead_time_baseline_wmape_pct=38.0,
    )

    assert reason is None


def test_gate_reason_uses_scaled_tolerance_for_high_baseline_wmape() -> None:
    quality = ForecastDataQuality(
        status="ok",
        history_days=120,
        non_zero_days=70,
        non_zero_ratio=0.58,
        capped_outlier_days=0,
        suspected_stockout_days=0,
        data_tier="mature",
        effective_history_days=120,
        notes=[],
    )
    score = CandidateScore(
        model_name="Stable",
        mae=0.5,
        mape_pct=22.0,
        wmape_pct=24.0,
        windows_evaluated=4,
        mae_std=0.1,
        mape_std_pct=1.2,
        wmape_std_pct=1.3,
    )

    # Mature threshold target is 90.0 when baseline is 100.0.
    # Shortfall is 2.5, which stays inside scaled tolerance (3.0), so no fallback.
    reason = _recommendation_gate_reason(
        score,
        quality,
        confidence=0.65,
        lead_time_wmape_pct=92.5,
        lead_time_baseline_wmape_pct=100.0,
    )

    assert reason is not None
    assert "baseline_not_beaten" not in reason
    assert "wmape_high" in reason


def test_recommendation_action_hard_gate_only_for_configured_reasons() -> None:
    hard_tokens = _parse_reason_tokens("sparse_sales,confidence_low")
    assert _recommendation_action(hard_tokens) == "hard_gate"

    stale_hard_tokens = _parse_reason_tokens("no_recent_sales_30d,confidence_low")
    assert _recommendation_action(stale_hard_tokens) == "hard_gate"

    soft_tokens = _parse_reason_tokens("baseline_not_beaten,confidence_low")
    assert _recommendation_action(soft_tokens) == "baseline_fallback"

    neutral_tokens = _parse_reason_tokens("wmape_high,confidence_low")
    assert _recommendation_action(neutral_tokens) == "baseline_fallback"

    stale_soft_tokens = _parse_reason_tokens("stale_history,confidence_low")
    assert _recommendation_action(stale_soft_tokens) == "baseline_fallback"

    non_mature_tokens = _parse_reason_tokens("non_mature_guardrail,confidence_low")
    assert _recommendation_action(non_mature_tokens) == "baseline_fallback"


def test_champion_lock_guardrail_forces_baseline_fallback_for_chronic_loser() -> None:
    tokens, action = _apply_champion_lock_guardrail(
        set(),
        action="none",
        lead_time_model_win_count=1,
        lead_time_windows_evaluated=4,
    )
    assert action == "baseline_fallback"
    assert "baseline_champion_locked" in tokens


def test_champion_lock_guardrail_skips_when_results_are_not_chronic_loss() -> None:
    tokens, action = _apply_champion_lock_guardrail(
        set(),
        action="none",
        lead_time_model_win_count=2,
        lead_time_windows_evaluated=4,
    )
    assert action == "none"
    assert "baseline_champion_locked" not in tokens


def test_champion_lock_guardrail_does_not_override_existing_action() -> None:
    existing_tokens = {"sparse_sales"}
    tokens, action = _apply_champion_lock_guardrail(
        existing_tokens,
        action="hard_gate",
        lead_time_model_win_count=0,
        lead_time_windows_evaluated=4,
    )
    assert action == "hard_gate"
    assert tokens == existing_tokens


def test_recommendation_fallback_reason_prefers_baseline_signal() -> None:
    champion_tokens = _parse_reason_tokens("baseline_champion_locked,baseline_not_beaten,confidence_low")
    assert _recommendation_fallback_reason(champion_tokens) == "baseline_champion_locked"

    both_tokens = _parse_reason_tokens("wmape_high,baseline_not_beaten,confidence_low")
    assert _recommendation_fallback_reason(both_tokens) == "baseline_not_beaten"

    wmape_only_tokens = _parse_reason_tokens("wmape_high,confidence_low")
    assert _recommendation_fallback_reason(wmape_only_tokens) == "wmape_high"

    stale_only_tokens = _parse_reason_tokens("stale_history,confidence_low")
    assert _recommendation_fallback_reason(stale_only_tokens) == "stale_history"

    non_mature_tokens = _parse_reason_tokens("non_mature_guardrail,confidence_low")
    assert _recommendation_fallback_reason(non_mature_tokens) == "non_mature_guardrail"


def test_gate_reason_adds_stale_history_and_no_recent_sales_signals() -> None:
    quality = ForecastDataQuality(
        status="ok",
        history_days=120,
        non_zero_days=70,
        non_zero_ratio=0.58,
        capped_outlier_days=0,
        suspected_stockout_days=0,
        data_tier="mature",
        effective_history_days=120,
        notes=[],
    )
    score = CandidateScore(
        model_name="Stable",
        mae=0.4,
        mape_pct=18.0,
        wmape_pct=20.0,
        windows_evaluated=4,
        mae_std=0.1,
        mape_std_pct=1.0,
        wmape_std_pct=1.2,
    )

    stale_reason = _recommendation_gate_reason(
        score,
        quality,
        confidence=0.72,
        history_lag_days=16,
        days_since_last_sale=16,
    )
    assert stale_reason is not None
    assert "stale_history" in stale_reason

    stale_hard_reason = _recommendation_gate_reason(
        score,
        quality,
        confidence=0.72,
        history_lag_days=35,
        days_since_last_sale=35,
    )
    assert stale_hard_reason is not None
    assert "no_recent_sales_30d" in stale_hard_reason
