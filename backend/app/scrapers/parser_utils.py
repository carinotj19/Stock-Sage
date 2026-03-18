from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def normalize_price(raw_price: str) -> Decimal:
    text = raw_price.strip()
    numeric_chunks = re.findall(r"-?\d[\d,]*\.?\d*", text)
    values: list[Decimal] = []

    for chunk in numeric_chunks:
        cleaned = chunk.replace(",", "")
        if not cleaned:
            continue
        try:
            values.append(Decimal(cleaned))
        except (InvalidOperation, ValueError):
            continue

    if not values:
        raise ValueError(f"Unable to parse price value from '{raw_price}'")

    # Product cards may include "save" amounts or installment snippets in the same node.
    # Keep values within a reasonable band of the highest candidate, then pick the lowest.
    max_value = max(values)
    if len(values) > 1 and max_value > 0:
        floor = max_value * Decimal("0.50")
        clustered = [value for value in values if value >= floor]
        if clustered:
            values = clustered

    # For original+discounted pairs, this keeps the discounted price.
    return min(values).quantize(Decimal("0.01"))


def parse_price_rows(html: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    item_selector = config.get("item_selector")
    if not item_selector:
        raise ValueError("Missing required 'item_selector' in scrape config")

    name_selector = config.get("name_selector")
    sku_selector = config.get("sku_selector")
    price_selector = config.get("price_selector")
    link_selector = config.get("link_selector")
    link_attribute = str(config.get("link_attribute", "href"))
    in_stock_selector = config.get("in_stock_selector")
    in_stock_text = str(config.get("in_stock_text", "in stock")).strip().lower()
    base_url = str(config.get("base_url") or config.get("_request_url") or "")

    rows: list[dict[str, Any]] = []
    for item in soup.select(item_selector):
        name_node = item.select_one(name_selector) if name_selector else None
        name = name_node.get_text(strip=True) if name_node else None

        sku_node = item.select_one(sku_selector) if sku_selector else None
        sku = sku_node.get_text(strip=True) if sku_node else None

        price_node = item.select_one(price_selector) if price_selector else None
        price_text = price_node.get_text(strip=True) if price_node else None
        if not price_text:
            continue

        link_node = None
        if name_node is not None:
            if name_node.has_attr(link_attribute):
                link_node = name_node
            else:
                parent_link = name_node.find_parent("a", href=True)
                if parent_link is not None:
                    link_node = parent_link
            if link_node is None:
                nested_link = name_node.select_one("a[href]")
                if nested_link is not None:
                    link_node = nested_link
        if link_node is None and link_selector:
            link_node = item.select_one(link_selector)
        raw_url = (
            str(link_node.get(link_attribute)).strip()
            if link_node is not None and link_node.has_attr(link_attribute)
            else ""
        )
        url = urljoin(base_url, raw_url) if raw_url else None

        stock_text = (
            item.select_one(in_stock_selector).get_text(strip=True).lower()
            if in_stock_selector and item.select_one(in_stock_selector)
            else ""
        )
        in_stock = True if not in_stock_selector else in_stock_text in stock_text

        try:
            normalized_price = normalize_price(price_text)
        except ValueError:
            continue

        rows.append(
            {
                "name": name,
                "sku": sku,
                "price_text": price_text,
                "price": normalized_price,
                "in_stock": in_stock,
                "url": url,
            }
        )

    return rows
