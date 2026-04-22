from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


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


class ManualScrapeJobRead(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    progress_pct: int = Field(ge=0, le=100)
    current_source: str | None = None
    inserted_rows: int = 0
    total_sources: int = 0
    completed_sources: int = 0
    started_at: datetime
    finished_at: datetime | None = None
    message: str
    error: str | None = None
    logs: list[str] = []
