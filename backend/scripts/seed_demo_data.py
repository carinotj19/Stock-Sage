from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import random
import sys

from sqlalchemy import delete, or_, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.models import (  # noqa: E402
    CompetitorPriceSnapshot,
    CompetitorSource,
    InventoryBalance,
    Product,
    ReorderRecommendation,
    SalesItem,
    SalesTransaction,
    SkuForecast,
    StockMovement,
    Supplier,
)
from app.db.session import SessionLocal, init_db  # noqa: E402


BASE_PC_PARTS_CATALOG = [
    {
        "sku": "CPU-AMD-5600",
        "name": "AMD Ryzen 5 5600 6-Core Processor",
        "search_terms": "ryzen 5 5600",
        "category": "CPU",
        "supplier_name": "AMD Components Distributor",
        "lead_time_days": 4,
        "cost_price": Decimal("6200.00"),
        "sell_price": Decimal("6890.00"),
        "initial_stock": 32,
    },
    {
        "sku": "CPU-INT-I512400F",
        "name": "Intel Core i5-12400F 6-Core Processor",
        "search_terms": "intel i5 12400f",
        "category": "CPU",
        "supplier_name": "Intel Components Distributor",
        "lead_time_days": 5,
        "cost_price": Decimal("8100.00"),
        "sell_price": Decimal("8990.00"),
        "initial_stock": 26,
    },
    {
        "sku": "GPU-MSI-RTX4060",
        "name": "MSI GeForce RTX 4060 Ventus 2X 8G OC",
        "search_terms": "msi rtx 4060 ventus",
        "category": "GPU",
        "supplier_name": "GPU Distributor PH",
        "lead_time_days": 6,
        "cost_price": Decimal("18400.00"),
        "sell_price": Decimal("19990.00"),
        "initial_stock": 12,
    },
    {
        "sku": "RAM-KST-FURY16-3200",
        "name": "Kingston Fury Beast 16GB DDR4 3200",
        "search_terms": "kingston fury beast 16gb ddr4 3200",
        "category": "RAM",
        "supplier_name": "Memory Distributor PH",
        "lead_time_days": 3,
        "cost_price": Decimal("1725.00"),
        "sell_price": Decimal("1995.00"),
        "initial_stock": 60,
    },
    {
        "sku": "SSD-KST-NV2-1TB",
        "name": "Kingston NV2 1TB NVMe SSD",
        "search_terms": "kingston nv2 1tb",
        "category": "SSD",
        "supplier_name": "Storage Distributor PH",
        "lead_time_days": 4,
        "cost_price": Decimal("2780.00"),
        "sell_price": Decimal("3295.00"),
        "initial_stock": 42,
    },
    {
        "sku": "MB-MSI-B550M-VDH",
        "name": "MSI B550M PRO-VDH WIFI Motherboard",
        "search_terms": "msi b550m pro-vdh wifi",
        "category": "Motherboard",
        "supplier_name": "Motherboard Distributor PH",
        "lead_time_days": 6,
        "cost_price": Decimal("6180.00"),
        "sell_price": Decimal("6995.00"),
        "initial_stock": 22,
    },
    {
        "sku": "SSD-SAM-970EVO-1TB",
        "name": "Samsung 970 EVO Plus 1TB NVMe SSD",
        "search_terms": "samsung 970 evo plus 1tb",
        "category": "SSD",
        "supplier_name": "Storage Distributor PH",
        "lead_time_days": 4,
        "cost_price": Decimal("3950.00"),
        "sell_price": Decimal("4495.00"),
        "initial_stock": 16,
    },
    {
        "sku": "PSU-COR-CX650",
        "name": "Corsair CX650 650W 80+ Bronze Power Supply",
        "search_terms": "corsair cx650",
        "category": "PSU",
        "supplier_name": "Power Supply Distributor PH",
        "lead_time_days": 5,
        "cost_price": Decimal("2750.00"),
        "sell_price": Decimal("3195.00"),
        "initial_stock": 20,
    },
    {
        "sku": "CASE-TEC-NEXUS-M2",
        "name": "Tecware Nexus Air M2 Mesh TG mATX Case",
        "search_terms": "tecware nexus air m2",
        "category": "Case",
        "supplier_name": "Chassis Distributor PH",
        "lead_time_days": 5,
        "cost_price": Decimal("1450.00"),
        "sell_price": Decimal("1795.00"),
        "initial_stock": 18,
    },
    {
        "sku": "COOL-DEE-AK400",
        "name": "DeepCool AK400 CPU Air Cooler",
        "search_terms": "deepcool ak400",
        "category": "Cooler",
        "supplier_name": "Cooling Distributor PH",
        "lead_time_days": 4,
        "cost_price": Decimal("1300.00"),
        "sell_price": Decimal("1595.00"),
        "initial_stock": 24,
    },
]


LATEST_TOP5_PC_PARTS = [
    {
        "sku": "CPU-AMD-9800X3D",
        "name": "AMD Ryzen 7 9800X3D 8-Core Processor",
        "search_terms": "ryzen 7 9800x3d",
        "category": "CPU",
        "supplier_name": "AMD Components Distributor",
        "lead_time_days": 5,
        "cost_price": Decimal("28900.00"),
        "sell_price": Decimal("31995.00"),
        "initial_stock": 8,
    },
    {
        "sku": "CPU-INT-U7265K",
        "name": "Intel Core Ultra 7 265K Desktop Processor",
        "search_terms": "intel core ultra 7 265k",
        "category": "CPU",
        "supplier_name": "Intel Components Distributor",
        "lead_time_days": 6,
        "cost_price": Decimal("24200.00"),
        "sell_price": Decimal("26995.00"),
        "initial_stock": 8,
    },
    {
        "sku": "GPU-NV-RTX5070",
        "name": "NVIDIA GeForce RTX 5070 12GB Graphics Card",
        "search_terms": "rtx 5070 12gb",
        "category": "GPU",
        "supplier_name": "GPU Distributor PH",
        "lead_time_days": 7,
        "cost_price": Decimal("39800.00"),
        "sell_price": Decimal("43995.00"),
        "initial_stock": 5,
    },
    {
        "sku": "GPU-NV-RTX5080",
        "name": "NVIDIA GeForce RTX 5080 16GB Graphics Card",
        "search_terms": "rtx 5080 16gb",
        "category": "GPU",
        "supplier_name": "GPU Distributor PH",
        "lead_time_days": 8,
        "cost_price": Decimal("61200.00"),
        "sell_price": Decimal("67995.00"),
        "initial_stock": 3,
    },
    {
        "sku": "MB-MSI-B850M-EDGE",
        "name": "MSI B850M EDGE WIFI AM5 Motherboard",
        "search_terms": "msi b850m edge wifi",
        "category": "Motherboard",
        "supplier_name": "Motherboard Distributor PH",
        "lead_time_days": 6,
        "cost_price": Decimal("11400.00"),
        "sell_price": Decimal("12995.00"),
        "initial_stock": 7,
    },
]


def _dedupe_catalog(parts: list[dict]) -> list[dict]:
    by_sku: dict[str, dict] = {}
    for part in parts:
        by_sku[part["sku"]] = part
    return list(by_sku.values())


PC_PARTS_CATALOG = _dedupe_catalog(BASE_PC_PARTS_CATALOG + LATEST_TOP5_PC_PARTS)


def _split_terms(text: str) -> list[str]:
    normalized = text.lower().replace("-", " ")
    return [token for token in normalized.split() if token]


def _build_name_contains_map(parts: list[dict]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for part in parts:
        sku = part["sku"]
        full_name = str(part["name"]).strip().lower()
        search_terms = str(part.get("search_terms") or part["name"]).strip().lower()
        mapping[full_name] = sku
        mapping[search_terms] = sku

        tokens = _split_terms(search_terms)
        numeric_terms = [token for token in tokens if any(ch.isdigit() for ch in token)]
        if numeric_terms:
            mapping[" ".join(numeric_terms[:2])] = sku

    return mapping


def _build_query_override_map(parts: list[dict]) -> dict[str, str]:
    return {part["sku"]: str(part.get("search_terms") or part["name"]) for part in parts}


def _build_required_terms_map(parts: list[dict]) -> dict[str, list[str]]:
    required_terms_map: dict[str, list[str]] = {}
    for part in parts:
        tokens = _split_terms(str(part.get("search_terms") or part["name"]))
        model_tokens = [token for token in tokens if any(ch.isdigit() for ch in token)]
        brand_tokens = [token for token in tokens if token.isalpha()]

        required_terms: list[str] = []
        if brand_tokens:
            required_terms.append(brand_tokens[0])
        required_terms.extend(model_tokens[:2])

        if not required_terms:
            required_terms = tokens[:2]
        required_terms_map[part["sku"]] = required_terms
    return required_terms_map


NAME_CONTAINS_MAP = _build_name_contains_map(PC_PARTS_CATALOG)
QUERY_OVERRIDE_MAP = _build_query_override_map(PC_PARTS_CATALOG)
REQUIRED_TERMS_MAP = _build_required_terms_map(PC_PARTS_CATALOG)

LEGACY_SEED_SKUS = {
    "SKU-DEMO-001",
    "SKU-DEMO-002",
    "SKU-DEMO-003",
    "PC-RAM-001",
    "PC-SSD-001",
    "PC-MB-001",
}
SEED_RECEIPT_PREFIXES = ("DEMO-", "SIM-")
DEMO_SALES_HISTORY_DAYS = 90
DEMO_RESTOCK_REASON = "demo_restock"
DEMO_PAYMENT_METHODS = ("cash", "gcash", "card")


COMPETITOR_SITE_DEFS = [
    {
        "name": "DynaQuest",
        "base_url": "https://dynaquestpc.com/search",
        "mode": "per_product_search",
        "search_url_template": "https://dynaquestpc.com/search?q={query}",
        "item_selector": ".card",
        "name_selector": ".card__title a",
        "price_selector": ".price__current",
        "link_selector": ".card__title a",
        "config_overrides": {
            "request_timeout_seconds": 25,
            "request_retries": 2,
            "request_retry_delay_seconds": 1.2,
            "enable_auto_product_url_discovery": True,
            "discovery_url_pattern": "/products/",
            "discovery_min_name_match_score": 0.80,
            "discovery_min_fuzzy_ratio": 0.55,
            "allow_variant_substitution_skus": [
                "CPU-INT-I512400F",
                "GPU-MSI-RTX4060",
                "MB-MSI-B850M-EDGE",
                "SSD-KST-NV2-1TB",
                "SSD-SAM-970EVO-1TB",
            ],
            "variant_min_name_match_score": 0.25,
            "variant_min_fuzzy_ratio": 0.25,
            "required_terms_map_overrides": {
                "CPU-INT-I512400F": ["intel", "i5", "12400"],
                "GPU-MSI-RTX4060": ["msi", "rtx", "4060"],
                "MB-MSI-B850M-EDGE": ["msi", "b850", "wifi"],
                "SSD-KST-NV2-1TB": ["kingston", "1tb", "nvme"],
                "SSD-SAM-970EVO-1TB": ["samsung", "970", "evo"],
            },
            "product_url_map": {
                "CPU-INT-I512400F": (
                    "https://dynaquestpc.com/collections/12th-gen-intel-core-processor/12400f"
                ),
                "GPU-MSI-RTX4060": (
                    "https://dynaquestpc.com/collections/graphics-card?page=7"
                ),
                "MB-MSI-B850M-EDGE": (
                    "https://dynaquestpc.com/products/"
                    "msi-b850-gaming-plus-wifi-ddr5-atx-am5-motherboard"
                ),
                "SSD-KST-NV2-1TB": (
                    "https://dynaquestpc.com/products/"
                    "kingston-nv3-pcie-4-0-nvme-m-2-internal-desktop-and-laptop-ssd-1tb-snv3s-1000g-2tb-snv3s-2000g"
                ),
                "SSD-SAM-970EVO-1TB": (
                    "https://dynaquestpc.com/products/samsung-970-evo-plus-500gb-m-2-nvme-mz-v7s500bw"
                ),
            },
            "product_page_item_selector": "body",
            "product_page_name_selector": "h1, .productView-title, .product_title",
            "product_page_price_selector": (
                ".price__current, .price, .priceView-hero-price, .productView-price, [class*='price']"
            ),
        },
    },
    {
        "name": "PCX",
        "base_url": "https://pcx.com.ph/search",
        "mode": "per_product_search",
        "search_url_template": "https://pcx.com.ph/search?q={query}",
        "item_selector": ".t4s-product",
        "name_selector": ".t4s-product-title a",
        "price_selector": ".t4s-product-price",
        "link_selector": ".t4s-product-title a",
        "config_overrides": {
            "request_timeout_seconds": 25,
            "request_retries": 2,
            "request_retry_delay_seconds": 1.2,
            "enable_auto_product_url_discovery": True,
            "discovery_url_pattern": "/products/",
            "discovery_min_name_match_score": 0.80,
            "discovery_min_fuzzy_ratio": 0.55,
            "allow_variant_substitution_skus": [
                "CPU-INT-I512400F",
                "CPU-AMD-5600",
                "SSD-KST-NV2-1TB",
                "SSD-SAM-970EVO-1TB",
                "CASE-TEC-NEXUS-M2",
                "MB-MSI-B850M-EDGE",
                "COOL-DEE-AK400",
                "PSU-COR-CX650",
            ],
            "required_terms_map_overrides": {
                "CPU-INT-I512400F": ["intel", "i5", "12400"],
                "SSD-KST-NV2-1TB": ["kingston", "1tb", "nvme"],
                "SSD-SAM-970EVO-1TB": ["samsung", "1tb", "evo", "nvme"],
                "CASE-TEC-NEXUS-M2": ["matx", "case"],
                "COOL-DEE-AK400": ["deepcool", "cpu", "cooler"],
                "CPU-AMD-5600": ["amd", "ryzen", "5"],
                "CPU-AMD-9800X3D": ["ryzen", "9800x3d"],
                "CPU-INT-U7265K": ["intel", "265k"],
                "MB-MSI-B850M-EDGE": ["msi", "edge", "wifi", "am5"],
                "PSU-COR-CX650": ["corsair", "power", "supply"],
                "RAM-KST-FURY16-3200": ["kingston", "fury", "16gb", "3200"],
            },
            "variant_min_name_match_score": 0.24,
            "variant_min_fuzzy_ratio": 0.22,
            "query_override_map_overrides": {
                "CASE-TEC-NEXUS-M2": "matx case",
                "COOL-DEE-AK400": "deepcool cooler",
                "CPU-AMD-5600": "ryzen 5 5600x",
                "MB-MSI-B850M-EDGE": "msi b850 wifi",
                "PSU-COR-CX650": "corsair power supply",
            },
            "product_url_map": {
                "CPU-INT-I512400F": (
                    "https://pcx.com.ph/products/intel-core-i5-12400-processor"
                ),
                "CASE-TEC-NEXUS-M2": (
                    "https://pcx.com.ph/products/msi-mag-forge-m100a-argb-tempered-glass-chassis-black"
                ),
                "COOL-DEE-AK400": (
                    "https://pcx.com.ph/products/deepcool-lq240-argb-w-lcd-screen-all-in-one-cpu-cooler-fan-black"
                ),
                "CPU-AMD-5600": (
                    "https://pcx.com.ph/products/amd-ryzen-5-5600x-3-7ghz-processor"
                ),
                "CPU-AMD-9800X3D": (
                    "https://pcx.com.ph/products/amd-ryzen-7-9800x3d-desktop-processor"
                ),
                "CPU-INT-U7265K": (
                    "https://pcx.com.ph/products/intel-core-ultra-7-265k-destop-processor"
                ),
                "MB-MSI-B850M-EDGE": (
                    "https://pcx.com.ph/products/msi-pro-b850-p-wifi-atx-motherboard"
                ),
                "PSU-COR-CX650": (
                    "https://pcx.com.ph/collections/power-supplies/corsair"
                ),
                "RAM-KST-FURY16-3200": (
                    "https://pcx.com.ph/products/kingston-16gb-ddr4-3200mhz-fury-beast-ram"
                ),
                "SSD-KST-NV2-1TB": (
                    "https://pcx.com.ph/products/"
                    "kingston-1tb-nv3-m-2-pcie-nvme-solid-state-drive"
                ),
                "SSD-SAM-970EVO-1TB": (
                    "https://pcx.com.ph/products/"
                    "samsung-1tb-990-evo-plus-gen4-nvme-solid-state-drive"
                ),
                "GPU-MSI-RTX4060": (
                    "https://pcx.com.ph/products/"
                    "msi-geforce-rtx-4060-ventus-2x-oc-8gb-gddr6-128-bit-graphics-card"
                ),
                "GPU-NV-RTX5070": (
                    "https://pcx.com.ph/products/"
                    "msi-geforce-rtx-5070-shadow-2x-oc-12gb-gddr7-192-bit-graphics-card"
                ),
            },
            "product_page_item_selector": "body",
            "product_page_name_selector": "h1.t4s-product__title, h1",
            "product_page_price_selector": ".t4s-product-price",
        },
    },
    {
        "name": "IT World PH",
        "base_url": "https://www.itworldph.com/shop",
        "mode": "per_product_search",
        "search_url_template": "https://www.itworldph.com/shop?search={query}",
        "item_selector": ".oe_product",
        "name_selector": ".oe_product_cart h6 a",
        "price_selector": ".oe_currency_value",
        "link_selector": ".oe_product_cart h6 a",
        "config_overrides": {
            "request_timeout_seconds": 25,
            "request_retries": 1,
            "request_retry_delay_seconds": 1.0,
            "enable_auto_product_url_discovery": True,
            "discovery_url_pattern": "/shop/",
            "discovery_min_name_match_score": 0.82,
            "discovery_min_fuzzy_ratio": 0.58,
            "allow_variant_substitution_skus": [
                "CPU-INT-I512400F",
                "CPU-AMD-9800X3D",
                "CPU-INT-U7265K",
                "GPU-MSI-RTX4060",
                "SSD-KST-NV2-1TB",
                "SSD-SAM-970EVO-1TB",
                "CASE-TEC-NEXUS-M2",
                "MB-MSI-B850M-EDGE",
            ],
            "required_terms_map_overrides": {
                "CPU-INT-I512400F": ["intel", "i5", "12400"],
                "CASE-TEC-NEXUS-M2": ["pc", "case"],
                "CPU-AMD-9800X3D": ["amd", "ryzen", "desktop", "processor"],
                "CPU-INT-U7265K": ["intel", "i5", "desktop", "processor"],
                "GPU-MSI-RTX4060": ["rtx", "4060"],
                "SSD-KST-NV2-1TB": ["1tb", "nvme", "ssd"],
                "SSD-SAM-970EVO-1TB": ["samsung", "1tb", "nvme"],
                "MB-MSI-B850M-EDGE": ["msi", "edge", "wifi", "am5"],
            },
            "query_override_map_overrides": {
                "CASE-TEC-NEXUS-M2": "pc case",
                "CPU-AMD-9800X3D": "ryzen",
                "CPU-INT-U7265K": "intel i5",
                "GPU-MSI-RTX4060": "rtx 4060",
                "SSD-KST-NV2-1TB": "nvme 1tb",
                "SSD-SAM-970EVO-1TB": "samsung 1tb nvme",
            },
            "variant_min_name_match_score": 0.25,
            "variant_min_fuzzy_ratio": 0.25,
            "product_url_map": {
                "CPU-INT-I512400F": (
                    "https://www.itworldph.com/shop/"
                    "i5-12400-intel-core-i5-12400-18mb-cache-up-to-4-40ghz-desktop-processor-10342"
                ),
                "CASE-TEC-NEXUS-M2": (
                    "https://www.itworldph.com/shop/"
                    "ph-ec200atg-dbk01-phanteks-eclipse-p200a-d-rgb-pc-case-ph-ec200atg-dbk01-11501?search=pc+case"
                ),
                "CPU-AMD-9800X3D": (
                    "https://www.itworldph.com/shop/"
                    "amd-ryzen-9-7900x-3y-ph-amd-ryzen-9-7900x-12-core-24-thread-desktop-processor-boxed-8084?search=ryzen"
                ),
                "CPU-INT-U7265K": (
                    "https://www.itworldph.com/shop/"
                    "i5-14400-tray-type-intel-core-desktop-processor-i5-14400-10-core-4-7ghz-tray-type-16875?search=intel+i5"
                ),
                "GPU-MSI-RTX4060": (
                    "https://www.itworldph.com/shop/"
                    "46isl8mdapoc-galax-rtx-4060-ti-1-click-oc-v2-8gb-gddr6-geforce-graphic-card-46isl8mdapoc-9945?search=rtx+4060"
                ),
                "SSD-KST-NV2-1TB": (
                    "https://www.itworldph.com/shop/"
                    "tm8fpk001t0c101-teamgroup-mp44l-m-2-pcie-nvme-4-0-with-graphene-label-internal-ssd-1tb-13288?search=nvme+1tb"
                ),
                "SSD-SAM-970EVO-1TB": (
                    "https://www.itworldph.com/shop/"
                    "mz-v9p1t0bw-samsung-990-pro-1tb-nvme-m-2-internal-ssd-mz-v9p1t0bw-12302?search=samsung+1tb+nvme"
                ),
                "MB-MSI-B850M-EDGE": (
                    "https://www.itworldph.com/shop/"
                    "b650-edge-wifi-msi-mpg-b650-edge-wifi-atx-am5-ddr5-motherboard-11084"
                ),
            },
            "product_page_item_selector": "body",
            "product_page_name_selector": "h1[itemprop='name'], h1",
            "product_page_price_selector": (
                ".oe_website_sale .oe_price .oe_currency_value, .oe_price .oe_currency_value, .oe_currency_value"
            ),
        },
    },
    {
        "name": "EasyPC",
        "base_url": "https://easypc.com.ph/search/suggest.json",
        "mode": "shopify_suggest_json",
        "search_url_template": (
            "https://easypc.com.ph/search/suggest.json"
            "?q={query}&resources[type]=product&resources[limit]=20"
        ),
        "config_overrides": {
            "request_timeout_seconds": 20,
            "request_retries": 1,
            "request_retry_delay_seconds": 1.0,
        },
    },
    {
        "name": "PCWorx",
        "base_url": "https://pcworx.ph/search/suggest.json",
        "mode": "shopify_suggest_json",
        "search_url_template": (
            "https://pcworx.ph/search/suggest.json"
            "?q={query}&resources[type]=product&resources[limit]=20"
        ),
        "config_overrides": {
            "request_timeout_seconds": 20,
            "request_retries": 1,
            "request_retry_delay_seconds": 1.0,
            "min_name_match_score": 0.40,
            "allow_variant_substitution_skus": [
                "CASE-TEC-NEXUS-M2",
                "CPU-AMD-9800X3D",
                "CPU-INT-U7265K",
                "MB-MSI-B550M-VDH",
                "MB-MSI-B850M-EDGE",
                "SSD-KST-NV2-1TB",
                "SSD-SAM-970EVO-1TB",
            ],
            "variant_min_name_match_score": 0.22,
            "variant_min_fuzzy_ratio": 0.20,
            "required_terms_map_overrides": {
                "CASE-TEC-NEXUS-M2": ["tecware", "m2"],
                "CPU-AMD-9800X3D": ["ryzen", "7"],
                "CPU-INT-U7265K": ["intel", "i5", "13400"],
                "MB-MSI-B550M-VDH": ["b550m"],
                "MB-MSI-B850M-EDGE": ["b850m"],
                "SSD-KST-NV2-1TB": ["nvme", "1tb"],
                "SSD-SAM-970EVO-1TB": ["samsung", "990", "evo", "1tb"],
            },
            "query_override_map_overrides": {
                "CASE-TEC-NEXUS-M2": "tecware m2",
                "CPU-AMD-9800X3D": "ryzen 7",
                "MB-MSI-B550M-VDH": "b550m",
                "MB-MSI-B850M-EDGE": "b850m",
                "SSD-KST-NV2-1TB": "nvme 1tb",
            },
            "product_url_map": {
                "CASE-TEC-NEXUS-M2": (
                    "https://pcworx.ph/products/tecware-neo-m2-2x-140mm-argb-120mm-matx-casing-black?_pos=4&_psq=tecware+m2&_ss=e&_v=1.0"
                ),
                "CPU-AMD-9800X3D": (
                    "https://pcworx.ph/products/amd-ryzen-7-5700g-3-8ghz-65w-am4-processor?_pos=1&_psq=ryzen+7&_ss=e&_v=1.0"
                ),
                "CPU-INT-U7265K": (
                    "https://pcworx.ph/collections/processor/products/"
                    "intel-i5-13400-2-50ghz-10-core-20mb-cache-lga1700-processor"
                ),
                "MB-MSI-B550M-VDH": (
                    "https://pcworx.ph/products/asus-prime-b550m-a-wifi-ll-am4-ddr4-matx?_pos=1&_psq=b550m&_ss=e&_v=1.0"
                ),
                "MB-MSI-B850M-EDGE": (
                    "https://pcworx.ph/products/gigabyte-ga-b850m-gaming-x-wf6e-ddr5-am5-m-atx?_pos=3&_psq=b850m&_ss=e&_v=1.0"
                ),
                "SSD-KST-NV2-1TB": (
                    "https://pcworx.ph/products/kingston-snv3s-2000g-1000g-500g-2tb-nv3-m-2-nvme-pcie-4-0-x4-ssd?_pos=3&_psq=nvme+1tb&_ss=e&_v=1.0&variant=51134537400533"
                ),
                "SSD-SAM-970EVO-1TB": (
                    "https://pcworx.ph/products/samsung-mz-v9e1t0bw-1tb-990-evo-m-2-nvme-ssd"
                ),
            },
            "product_page_item_selector": "body",
            "product_page_name_selector": "h1, .product__title, .product-single__title",
            "product_page_price_selector": (
                ".price-item--regular, .price .money, .price-item, .price"
            ),
        },
    },
    {
        "name": "DataBlitz eCommerce",
        "base_url": "https://ecommerce.datablitz.com.ph/search/suggest.json",
        "mode": "shopify_suggest_json",
        "search_url_template": (
            "https://ecommerce.datablitz.com.ph/search/suggest.json"
            "?q={query}&resources[type]=product&resources[limit]=20"
        ),
        "config_overrides": {
            "request_timeout_seconds": 20,
            "request_retries": 1,
            "request_retry_delay_seconds": 1.0,
            "min_name_match_score": 0.40,
        },
    },
]


def _merge_config_map_overrides(config: dict, key: str) -> None:
    override_key = f"{key}_overrides"
    raw_overrides = config.pop(override_key, None)
    if not isinstance(raw_overrides, dict):
        return

    current = config.get(key)
    merged: dict = {}
    if isinstance(current, dict):
        merged.update(current)
    for raw_key, raw_value in raw_overrides.items():
        merged[str(raw_key)] = raw_value
    config[key] = merged


def _build_competitor_source_defs() -> list[dict]:
    source_defs: list[dict] = []
    for site in COMPETITOR_SITE_DEFS:
        mode = str(site.get("mode") or "per_product_search").strip().lower()
        config: dict = {
            "mode": mode,
            "search_url_template": site["search_url_template"],
            "currency": "PHP",
            "query_override_map": QUERY_OVERRIDE_MAP,
            "required_terms_map": REQUIRED_TERMS_MAP,
            "name_contains_map": NAME_CONTAINS_MAP,
            "max_query_terms": 6,
            "min_name_match_score": 0.35,
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
            ),
        }
        if mode == "per_product_search":
            config["item_selector"] = site["item_selector"]
            config["name_selector"] = site["name_selector"]
            config["price_selector"] = site["price_selector"]
            if site.get("link_selector"):
                config["link_selector"] = site["link_selector"]
        if mode == "shopify_suggest_json":
            config["max_rows_per_query"] = int(site.get("max_rows_per_query", 20))
        if site.get("render_js"):
            config["render_js"] = True
        config.update(site.get("config_overrides", {}))
        _merge_config_map_overrides(config, "query_override_map")
        _merge_config_map_overrides(config, "required_terms_map")
        _merge_config_map_overrides(config, "name_contains_map")

        source_defs.append(
            {
                "name": f"{site['name']} - Inventory Search",
                "base_url": site["base_url"],
                "config": config,
            }
        )

    return source_defs


COMPETITOR_SOURCE_DEFS = _build_competitor_source_defs()


def _get_or_create_supplier(session, name: str, lead_time_days: int) -> Supplier:
    supplier = session.scalars(select(Supplier).where(Supplier.name == name)).first()
    if supplier:
        supplier.lead_time_days_default = lead_time_days
        return supplier

    supplier = Supplier(name=name, lead_time_days_default=lead_time_days)
    session.add(supplier)
    session.flush()
    return supplier


def _upsert_product(session, payload: dict) -> Product:
    supplier = _get_or_create_supplier(session, payload["supplier_name"], payload["lead_time_days"])
    product = session.scalars(select(Product).where(Product.sku == payload["sku"])).first()

    if product is None:
        product = Product(
            sku=payload["sku"],
            name=payload["name"],
            category=payload["category"],
            supplier_id=supplier.id,
            cost_price=payload["cost_price"],
            sell_price=payload["sell_price"],
            reorder_min_qty=5,
            reorder_multiple=1,
            safety_stock=3,
            active=True,
        )
        session.add(product)
        session.flush()
    else:
        product.name = payload["name"]
        product.category = payload["category"]
        product.supplier_id = supplier.id
        product.cost_price = payload["cost_price"]
        product.sell_price = payload["sell_price"]
        product.active = True

    balance = session.get(InventoryBalance, product.id)
    if balance is None:
        session.add(InventoryBalance(product_id=product.id, on_hand_qty=payload["initial_stock"]))
    else:
        balance.on_hand_qty = payload["initial_stock"]

    return product


def _delete_sales_transactions(session, transaction_ids: list[int]) -> None:
    if not transaction_ids:
        return

    session.execute(delete(SalesItem).where(SalesItem.sales_transaction_id.in_(transaction_ids)))
    session.execute(delete(SalesTransaction).where(SalesTransaction.id.in_(transaction_ids)))
    session.execute(
        delete(StockMovement).where(
            StockMovement.reference_type == "sales_transaction",
            StockMovement.reference_id.in_(transaction_ids),
        )
    )


def _clear_seeded_sales(session) -> None:
    seeded_transaction_ids = list(
        session.scalars(
            select(SalesTransaction.id).where(
                or_(
                    *[
                        SalesTransaction.receipt_no.like(f"{prefix}%")
                        for prefix in SEED_RECEIPT_PREFIXES
                    ]
                )
            )
        ).all()
    )

    _delete_sales_transactions(session, seeded_transaction_ids)
    session.execute(delete(StockMovement).where(StockMovement.reason == DEMO_RESTOCK_REASON))


def _purge_legacy_demo_products(session) -> int:
    legacy_product_ids = list(session.scalars(select(Product.id).where(Product.sku.in_(LEGACY_SEED_SKUS))).all())
    if not legacy_product_ids:
        return 0

    related_transaction_ids = list(
        session.scalars(select(SalesItem.sales_transaction_id).where(SalesItem.product_id.in_(legacy_product_ids))).all()
    )
    _delete_sales_transactions(session, related_transaction_ids)

    session.execute(delete(SkuForecast).where(SkuForecast.product_id.in_(legacy_product_ids)))
    session.execute(delete(ReorderRecommendation).where(ReorderRecommendation.product_id.in_(legacy_product_ids)))
    session.execute(delete(CompetitorPriceSnapshot).where(CompetitorPriceSnapshot.product_id.in_(legacy_product_ids)))
    session.execute(delete(StockMovement).where(StockMovement.product_id.in_(legacy_product_ids)))
    session.execute(delete(InventoryBalance).where(InventoryBalance.product_id.in_(legacy_product_ids)))
    session.execute(delete(SalesItem).where(SalesItem.product_id.in_(legacy_product_ids)))
    session.execute(delete(Product).where(Product.id.in_(legacy_product_ids)))
    return len(legacy_product_ids)


def _seed_sales_history(session, products: list[Product], days: int = DEMO_SALES_HISTORY_DAYS) -> None:
    _clear_seeded_sales(session)

    def sales_profile(product: Product) -> tuple[float, int]:
        name = product.name.lower()
        category = (product.category or "").lower()

        if "rtx 5080" in name:
            return (0.45, 1)
        if "rtx" in name or category == "gpu":
            return (0.65, 1)
        if "motherboard" in name or category == "motherboard":
            return (0.8, 1)
        if "nv2" in name or "fury" in name or category in {"ram", "ssd"}:
            return (1.8, 3)
        if category in {"cpu", "cooler", "psu", "case"}:
            return (1.2, 2)
        return (1.0, 2)

    def weighted_sample(candidates: list[Product], weights: list[float], sample_size: int, rng: random.Random) -> list[Product]:
        pool = list(zip(candidates, weights))
        chosen: list[Product] = []

        while pool and len(chosen) < sample_size:
            total_weight = sum(weight for _, weight in pool)
            pick = rng.random() * total_weight
            running_weight = 0.0

            for index, (candidate, weight) in enumerate(pool):
                running_weight += weight
                if running_weight >= pick:
                    chosen.append(candidate)
                    pool.pop(index)
                    break

        return chosen

    def restock_inventory(
        sold_at: datetime,
        target_levels: dict[int, int],
        last_restock_dates: dict[int, date],
        rng: random.Random,
    ) -> None:
        for product in products:
            balance = session.get(InventoryBalance, product.id)
            if balance is None:
                continue

            target_level = target_levels.get(product.id, balance.on_hand_qty)
            threshold = max(product.safety_stock + product.reorder_min_qty, max(2, int(target_level * 0.35)))
            if balance.on_hand_qty > threshold or last_restock_dates.get(product.id) == sold_at.date():
                continue

            restock_buffer = max(2, target_level // 4)
            restock_qty = max(0, target_level + rng.randint(1, restock_buffer) - balance.on_hand_qty)
            if restock_qty <= 0:
                continue

            occurred_at = sold_at + timedelta(hours=8)
            balance.on_hand_qty += restock_qty
            balance.last_movement_at = occurred_at
            session.add(
                StockMovement(
                    product_id=product.id,
                    movement_type="restock",
                    qty_delta=restock_qty,
                    unit_price=product.cost_price,
                    reason=DEMO_RESTOCK_REASON,
                    reference_type="demo_seed",
                    occurred_at=occurred_at,
                )
            )
            last_restock_dates[product.id] = sold_at.date()

    rng = random.Random(42)
    start_date = (datetime.now(timezone.utc) - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    target_levels: dict[int, int] = {}
    for product in products:
        balance = session.get(InventoryBalance, product.id)
        target_levels[product.id] = max(1, int(balance.on_hand_qty if balance else 0))

    last_restock_dates: dict[int, date] = {}
    tx_counter = 0

    for day_offset in range(days):
        day_start = start_date + timedelta(days=day_offset)
        restock_inventory(day_start, target_levels, last_restock_dates, rng)

        transaction_slots = 1 + rng.randint(0, 1)
        if day_start.weekday() in {4, 5}:
            transaction_slots += 1
        if day_start.day in {15, 30}:
            transaction_slots += 1

        for slot in range(transaction_slots):
            available_products: list[Product] = []
            weights: list[float] = []

            for product in products:
                balance = session.get(InventoryBalance, product.id)
                if balance is None or balance.on_hand_qty <= 0:
                    continue

                weight, _ = sales_profile(product)
                target_level = max(target_levels.get(product.id, balance.on_hand_qty), 1)
                availability_ratio = balance.on_hand_qty / target_level
                available_products.append(product)
                weights.append(weight * max(0.35, availability_ratio))

            if not available_products:
                break

            basket_weights = [0.5, 0.35, 0.15]
            if day_start.weekday() in {4, 5}:
                basket_weights = [0.35, 0.45, 0.20]
            basket_size = min(len(available_products), rng.choices([1, 2, 3], weights=basket_weights, k=1)[0])
            basket = weighted_sample(available_products, weights, basket_size, rng)

            line_items: list[tuple[Product, int]] = []
            for product in basket:
                balance = session.get(InventoryBalance, product.id)
                if balance is None or balance.on_hand_qty <= 0:
                    continue

                _, max_qty = sales_profile(product)
                weekend_bonus = 1 if day_start.weekday() in {4, 5} and max_qty < 4 else 0
                qty_cap = min(balance.on_hand_qty, max_qty + weekend_bonus)
                qty = 1 if qty_cap <= 1 else rng.randint(1, qty_cap)
                if qty > 0:
                    line_items.append((product, qty))

            if not line_items:
                continue

            sold_at = day_start + timedelta(hours=10 + (slot * 3) + rng.randint(0, 1), minutes=rng.randint(0, 59))
            tx = SalesTransaction(
                receipt_no=f"SIM-{tx_counter:05d}",
                sold_at=sold_at,
                total_amount=Decimal("0.00"),
                payment_method=rng.choice(DEMO_PAYMENT_METHODS),
            )
            session.add(tx)
            session.flush()

            total = Decimal("0.00")
            for product, qty in line_items:
                line_total = product.sell_price * qty
                session.add(
                    SalesItem(
                        sales_transaction_id=tx.id,
                        product_id=product.id,
                        qty=qty,
                        unit_sell_price=product.sell_price,
                        line_total=line_total,
                    )
                )
                session.add(
                    StockMovement(
                        product_id=product.id,
                        movement_type="sale",
                        qty_delta=-qty,
                        unit_price=product.sell_price,
                        reason="sale",
                        reference_type="sales_transaction",
                        reference_id=tx.id,
                        occurred_at=sold_at,
                    )
                )
                total += line_total

                balance = session.get(InventoryBalance, product.id)
                if balance:
                    balance.on_hand_qty = max(balance.on_hand_qty - qty, 0)
                    balance.last_movement_at = sold_at

            tx.total_amount = total
            tx_counter += 1


def _upsert_competitor_source(session, name: str, base_url: str, config: dict) -> None:
    source = session.scalars(select(CompetitorSource).where(CompetitorSource.name == name)).first()
    config_json = json.dumps(config)

    if source is None:
        session.add(
            CompetitorSource(
                name=name,
                base_url=base_url,
                scrape_config_json=config_json,
                enabled=True,
            )
        )
        return

    source.base_url = base_url
    source.scrape_config_json = config_json
    source.enabled = True


def _seed_competitor_sources(session) -> int:
    desired_names = {payload["name"] for payload in COMPETITOR_SOURCE_DEFS}
    for source_payload in COMPETITOR_SOURCE_DEFS:
        _upsert_competitor_source(
            session,
            source_payload["name"],
            source_payload["base_url"],
            source_payload["config"],
        )

    existing_sources = list(session.scalars(select(CompetitorSource)).all())
    for source in existing_sources:
        if source.name not in desired_names:
            source.enabled = False

    return len(COMPETITOR_SOURCE_DEFS)


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        removed_legacy = _purge_legacy_demo_products(session)
        products = [_upsert_product(session, payload) for payload in PC_PARTS_CATALOG]
        _seed_sales_history(session, products, days=DEMO_SALES_HISTORY_DAYS)
        source_count = _seed_competitor_sources(session)
        session.commit()
        print(f"legacy_demo_products_removed={removed_legacy}")
        print(f"seeded_products={len(products)}")
        print(f"seeded_competitor_sources={source_count}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
