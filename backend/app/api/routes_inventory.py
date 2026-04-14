from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import AdminUser
from app.db.session import get_db
from app.schemas.inventory import (
    InventoryAdjustRequest,
    InventoryAdjustResponse,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    SupplierCreate,
    SupplierRead,
)
from app.services.auth_service import require_admin
from app.services.inventory_service import InventoryService


router = APIRouter(tags=["inventory"])


@router.post("/suppliers", response_model=SupplierRead)
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db)) -> SupplierRead:
    service = InventoryService(db)
    supplier = service.create_supplier(payload)
    return SupplierRead.model_validate(supplier)


@router.post("/products", response_model=ProductRead)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)) -> ProductRead:
    service = InventoryService(db)
    return service.create_product(payload)


@router.get("/products", response_model=list[ProductRead])
def list_products(db: Session = Depends(get_db)) -> list[ProductRead]:
    service = InventoryService(db)
    return service.list_products()


@router.patch("/products/{product_id}", response_model=ProductRead)
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)) -> ProductRead:
    service = InventoryService(db)
    return service.update_product(product_id, payload)


@router.delete("/products/{product_id}", response_model=ProductRead)
def delete_product(
    product_id: int,
    actor: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProductRead:
    service = InventoryService(db)
    return service.soft_delete_product(product_id, actor)


@router.post("/inventory/adjust", response_model=InventoryAdjustResponse)
def adjust_inventory(payload: InventoryAdjustRequest, db: Session = Depends(get_db)) -> InventoryAdjustResponse:
    service = InventoryService(db)
    return service.adjust_stock(payload)
