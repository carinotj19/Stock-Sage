from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.dashboard import (
    DashboardKpis,
    ForecastRunComparisonResponse,
    ForecastReportResponse,
    ItemForecastDetail,
    LowStockRow,
    ScraperSourceQualityRow,
    SalesTrendPoint,
    StockoutPredictionRow,
)
from app.services.dashboard_service import DashboardService


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/low-stock", response_model=list[LowStockRow])
def get_low_stock(db: Session = Depends(get_db)) -> list[LowStockRow]:
    service = DashboardService(db)
    return service.get_low_stock()


@router.get("/sales-trend", response_model=list[SalesTrendPoint])
def get_sales_trend(days: int = Query(default=30, ge=1, le=365), db: Session = Depends(get_db)) -> list[SalesTrendPoint]:
    service = DashboardService(db)
    return service.get_sales_trend(days=days)


@router.get("/kpis", response_model=DashboardKpis)
def get_kpis(db: Session = Depends(get_db)) -> DashboardKpis:
    service = DashboardService(db)
    return service.get_kpis()


@router.get("/scraper-source-quality", response_model=list[ScraperSourceQualityRow])
def get_scraper_source_quality(
    window_hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
) -> list[ScraperSourceQualityRow]:
    service = DashboardService(db)
    return service.get_scraper_source_quality(window_hours=window_hours)


@router.get("/stockout-dates", response_model=list[StockoutPredictionRow])
def get_stockout_dates(db: Session = Depends(get_db)) -> list[StockoutPredictionRow]:
    service = DashboardService(db)
    return service.get_stockout_predictions()


@router.get("/forecast-report", response_model=ForecastReportResponse)
def get_forecast_report(
    include_details: bool = Query(default=False),
    evaluation_days: int = Query(default=7, ge=3, le=30),
    run_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> ForecastReportResponse:
    service = DashboardService(db)
    try:
        return service.get_forecast_report(
            include_details=include_details,
            evaluation_days=evaluation_days,
            run_id=run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/forecast-report/compare", response_model=ForecastRunComparisonResponse)
def get_forecast_report_compare(
    baseline_run_id: int | None = Query(default=None, ge=1),
    candidate_run_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> ForecastRunComparisonResponse:
    service = DashboardService(db)
    try:
        return service.get_forecast_report_comparison(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/item-forecast/{product_id}", response_model=ItemForecastDetail)
def get_item_forecast(
    product_id: int,
    history_days: int = Query(default=365, ge=30, le=365),
    db: Session = Depends(get_db),
) -> ItemForecastDetail:
    service = DashboardService(db)
    try:
        return service.get_item_forecast_detail(product_id, history_days=history_days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
