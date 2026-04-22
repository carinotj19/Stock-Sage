from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class CompetitorPricePoint(BaseModel):
    source_id: int
    source_name: str
    competitor_price: Decimal
    scraped_at: datetime
    in_stock: bool | None


class PriceComparisonRow(BaseModel):
    product_id: int
    sku: str
    name: str
    store_price: Decimal
    cheapest_competitor_price: Decimal | None
    price_gap: Decimal | None
    price_gap_pct: Decimal | None
    is_above_cheapest: bool
    competitor_prices: list[CompetitorPricePoint]


class ManualScrapeRunResult(BaseModel):
    inserted_rows: int
    ran_at: datetime
    message: str
