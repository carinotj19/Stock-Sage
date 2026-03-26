from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CompetitorPriceSnapshot, CompetitorSource, Product
from app.schemas.pricing import CompetitorPricePoint, PriceComparisonRow


class PricingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def compare_prices(self) -> list[PriceComparisonRow]:
        products = list(self.db.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.sku.asc())).all())
        if not products:
            return []

        product_ids = [product.id for product in products]
        snapshots_stmt = (
            select(
                CompetitorPriceSnapshot.product_id,
                CompetitorPriceSnapshot.source_id,
                CompetitorPriceSnapshot.competitor_price,
                CompetitorPriceSnapshot.scraped_at,
                CompetitorPriceSnapshot.in_stock,
                CompetitorSource.name,
            )
            .join(CompetitorSource, CompetitorSource.id == CompetitorPriceSnapshot.source_id)
            .where(CompetitorPriceSnapshot.product_id.in_(product_ids))
            .order_by(
                CompetitorPriceSnapshot.product_id.asc(),
                CompetitorPriceSnapshot.source_id.asc(),
                CompetitorPriceSnapshot.scraped_at.desc(),
            )
        )
        snapshot_rows = self.db.execute(snapshots_stmt).all()

        latest_by_product: dict[int, dict[int, CompetitorPricePoint]] = {}
        for row in snapshot_rows:
            product_map = latest_by_product.setdefault(row.product_id, {})
            if row.source_id in product_map:
                continue
            product_map[row.source_id] = CompetitorPricePoint(
                source_id=row.source_id,
                source_name=row.name,
                competitor_price=row.competitor_price,
                scraped_at=row.scraped_at,
                in_stock=row.in_stock,
            )

        results: list[PriceComparisonRow] = []
        for product in products:
            competitor_points = list(latest_by_product.get(product.id, {}).values())
            benchmark_points = [point for point in competitor_points if point.in_stock is not False]
            cheapest = (
                min((point.competitor_price for point in benchmark_points), default=None)
                if benchmark_points
                else None
            )

            if cheapest is None or cheapest == 0:
                gap = None
                gap_pct = None
                above = False
            else:
                gap = (product.sell_price - cheapest).quantize(Decimal("0.01"))
                gap_pct = ((gap / cheapest) * Decimal("100")).quantize(Decimal("0.01"))
                above = gap > 0

            results.append(
                PriceComparisonRow(
                    product_id=product.id,
                    sku=product.sku,
                    name=product.name,
                    store_price=product.sell_price,
                    cheapest_competitor_price=cheapest,
                    price_gap=gap,
                    price_gap_pct=gap_pct,
                    is_above_cheapest=above,
                    competitor_prices=sorted(competitor_points, key=lambda item: item.source_name.lower()),
                )
            )

        return results
