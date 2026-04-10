from collections import Counter

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, InventoryBalance, SalesTransaction, StockMovement
from scripts.seed_demo_data import PC_PARTS_CATALOG, _seed_sales_history, _upsert_product


TEST_DATABASE_URL = "sqlite:///./data/test_seed_demo_data.db"


def _build_test_engine():
    return create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})


def test_demo_seed_creates_richer_transaction_history() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        products = [_upsert_product(db, payload) for payload in PC_PARTS_CATALOG[:5]]
        db.flush()

        _seed_sales_history(db, products, days=90)
        db.commit()

        transactions = db.scalars(select(SalesTransaction).order_by(SalesTransaction.sold_at.asc())).all()
        daily_counts = Counter(transaction.sold_at.date() for transaction in transactions)

        transaction_count = db.scalar(select(func.count()).select_from(SalesTransaction))
        sale_movement_count = db.scalar(
            select(func.count()).select_from(StockMovement).where(StockMovement.movement_type == "sale")
        )
        positive_movement_count = db.scalar(
            select(func.count()).select_from(StockMovement).where(StockMovement.qty_delta > 0)
        )
        balances = db.scalars(select(InventoryBalance)).all()

        assert transaction_count is not None
        assert transaction_count > 90
        assert len(daily_counts) >= 60
        assert max(daily_counts.values()) >= 2
        assert sale_movement_count is not None
        assert sale_movement_count > 0
        assert positive_movement_count is not None
        assert positive_movement_count > 0
        assert any(balance.on_hand_qty > 0 for balance in balances)

    Base.metadata.drop_all(bind=engine)
    engine.dispose()
