from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs.run_scraper_cycle import run_scraper_cycle
from app.schemas.pricing import ManualScrapeRunResult, PriceComparisonRow
from app.services.pricing_service import PricingService


router = APIRouter(prefix="/prices", tags=["pricing"])


@router.get("/compare", response_model=list[PriceComparisonRow])
def compare_prices(db: Session = Depends(get_db)) -> list[PriceComparisonRow]:
    service = PricingService(db)
    return service.compare_prices()


@router.post("/scrape", response_model=ManualScrapeRunResult)
def run_manual_scrape(db: Session = Depends(get_db)) -> ManualScrapeRunResult:
    inserted_rows = run_scraper_cycle(db=db, verbose=False)
    return ManualScrapeRunResult(
        inserted_rows=inserted_rows,
        ran_at=datetime.now(UTC),
        message=f"Manual web scraping completed with {inserted_rows} snapshots saved.",
    )
