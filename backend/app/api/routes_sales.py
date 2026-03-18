from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.sales import SaleCreate, SaleRead
from app.services.sales_service import SalesService


router = APIRouter(tags=["sales"])


@router.post("/sales", response_model=SaleRead)
def post_sale(payload: SaleCreate, db: Session = Depends(get_db)) -> SaleRead:
    service = SalesService(db)
    return service.create_sale(payload)

