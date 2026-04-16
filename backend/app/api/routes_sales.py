from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.sales import SaleCreate, SaleRead, SaleTransactionPageRead
from app.services.sales_service import SalesService


router = APIRouter(tags=["sales"])


@router.get("/sales", response_model=SaleTransactionPageRead)
def get_sales(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    sort: Literal["asc", "desc"] = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> SaleTransactionPageRead:
    service = SalesService(db)
    return service.list_sales(date_from=date_from, date_to=date_to, sort=sort, page=page, page_size=page_size)


@router.post("/sales", response_model=SaleRead)
def post_sale(payload: SaleCreate, db: Session = Depends(get_db)) -> SaleRead:
    service = SalesService(db)
    return service.create_sale(payload)
