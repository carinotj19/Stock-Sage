from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.pricing import PriceComparisonRow
from app.services.pricing_service import PricingService


router = APIRouter(prefix="/prices", tags=["pricing"])


@router.get("/compare", response_model=list[PriceComparisonRow])
def compare_prices(db: Session = Depends(get_db)) -> list[PriceComparisonRow]:
    service = PricingService(db)
    return service.compare_prices()

