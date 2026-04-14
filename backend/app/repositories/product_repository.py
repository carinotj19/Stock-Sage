from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import InventoryBalance, Product
from app.schemas.inventory import ProductCreate, ProductUpdate


class ProductRepository:
    def create_product(self, db: Session, payload: ProductCreate) -> Product:
        product = Product(
            sku=payload.sku,
            name=payload.name,
            category=payload.category,
            supplier_id=payload.supplier_id,
            cost_price=payload.cost_price,
            sell_price=payload.sell_price,
            reorder_min_qty=payload.reorder_min_qty,
            reorder_multiple=payload.reorder_multiple,
            safety_stock=payload.safety_stock,
            active=payload.active,
        )
        db.add(product)
        db.flush()
        return product

    def create_inventory_balance(self, db: Session, product_id: int, on_hand_qty: int) -> InventoryBalance:
        balance = InventoryBalance(product_id=product_id, on_hand_qty=on_hand_qty)
        db.add(balance)
        db.flush()
        return balance

    def update_product(self, db: Session, product: Product, payload: ProductUpdate) -> Product:
        product.sku = payload.sku
        product.name = payload.name
        product.sell_price = payload.sell_price
        product.safety_stock = payload.safety_stock
        db.flush()
        return product

    def list_products(self, db: Session, *, active_only: bool = True) -> list[Product]:
        statement = select(Product).order_by(Product.name.asc())
        if active_only:
            statement = statement.where(Product.active.is_(True))
        return list(db.scalars(statement).all())

    def list_recycled_products(self, db: Session) -> list[Product]:
        statement = select(Product).where(Product.active.is_(False)).order_by(Product.updated_at.desc(), Product.name.asc())
        return list(db.scalars(statement).all())

    def get_product(self, db: Session, product_id: int) -> Product | None:
        return db.get(Product, product_id)

    def get_inventory_balance(self, db: Session, product_id: int) -> InventoryBalance | None:
        return db.get(InventoryBalance, product_id)
