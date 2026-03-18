from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from time import perf_counter
from typing import Any, Callable
from urllib.parse import quote_plus, urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import CompetitorPriceSnapshot, CompetitorSource, Product
from app.db.session import SessionLocal
from app.scrapers.bs4_scraper import fetch_html
from app.scrapers.parser_utils import normalize_price, parse_price_rows
from app.scrapers.playwright_scraper import fetch_html_with_playwright


FetchHtmlFn = Callable[[CompetitorSource, dict[str, Any]], str]

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_TOKENS = {"with", "and", "for", "the", "series", "processor", "graphics", "card", "motherboard"}
UNIT_TOKEN_PATTERN = re.compile(r"^(\d+)(tb|gb|mb|mhz|w)$")
ALIAS_TOKEN_MAP = {
    "geforce": "rtx",
    "nvidia": "rtx",
    "rtxtm": "rtx",
    "nvme2": "nvme",
    "wifi6": "wifi",
    "d4": "ddr4",
    "d5": "ddr5",
    "psu": "powersupply",
}


def _log(verbose: bool, message: str) -> None:
    if verbose:
        _emit(message)


def _emit(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = (getattr(sys.stdout, "encoding", None) or "utf-8").lower()
        safe = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe)


def _normalize_filters(filters: list[str] | None) -> list[str]:
    if not filters:
        return []
    normalized: list[str] = []
    for token in filters:
        value = str(token).strip().lower()
        if value:
            normalized.append(value)
    return normalized


def _filter_sources(
    sources: list[CompetitorSource],
    *,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> list[CompetitorSource]:
    include = _normalize_filters(include_patterns)
    exclude = _normalize_filters(exclude_patterns)

    filtered: list[CompetitorSource] = []
    for source in sources:
        source_name = source.name.lower()
        if include and not any(pattern in source_name for pattern in include):
            continue
        if exclude and any(pattern in source_name for pattern in exclude):
            continue
        filtered.append(source)

    return filtered


def _default_fetcher(source: CompetitorSource, config: dict[str, Any]) -> str:
    request_url = str(config.get("_request_url") or source.base_url)
    request_timeout = int(config.get("request_timeout_seconds", 20))
    request_retries = int(config.get("request_retries", 1))
    request_retry_delay = float(config.get("request_retry_delay_seconds", 1.0))
    user_agent = str(config.get("user_agent", "")).strip() or None
    use_playwright = bool(config.get("render_js"))
    if use_playwright:
        render_timeout_ms = int(config.get("render_timeout_ms", 30000))
        render_wait_until = str(config.get("render_wait_until", "networkidle"))
        render_retries = int(config.get("render_retries", 1))
        render_retry_delay_ms = int(config.get("render_retry_delay_ms", 1000))
        render_extra_wait_ms = int(config.get("render_extra_wait_ms", 0))
        try:
            return fetch_html_with_playwright(
                request_url,
                timeout_ms=render_timeout_ms,
                wait_until=render_wait_until,
                retries=render_retries,
                retry_delay_ms=render_retry_delay_ms,
                extra_wait_ms=render_extra_wait_ms,
                user_agent=user_agent,
            )
        except RuntimeError as exc:
            _emit(f"scraper_source_warning source={source.name} detail={exc}; falling_back=requests")
    return fetch_html(
        request_url,
        timeout_seconds=request_timeout,
        retries=request_retries,
        retry_delay_seconds=request_retry_delay,
        user_agent=user_agent,
    )


def _load_config(source: CompetitorSource) -> dict[str, Any]:
    if not source.scrape_config_json:
        return {}
    try:
        return json.loads(source.scrape_config_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid scrape_config_json for source {source.name}") from exc


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _update_runtime_state(
    config: dict[str, Any],
    *,
    attempted_products: int,
    inserted: int,
) -> bool:
    runtime_raw = config.get("runtime_state")
    runtime_state: dict[str, Any] = dict(runtime_raw) if isinstance(runtime_raw, dict) else {}
    previous_state = dict(runtime_state)

    consecutive_zero = _safe_int(runtime_state.get("consecutive_zero_insert_runs"), 0)
    if attempted_products > 0 and inserted == 0:
        consecutive_zero += 1
    elif inserted > 0:
        consecutive_zero = 0

    runtime_state["last_run_inserted"] = int(inserted)
    runtime_state["last_run_attempted_products"] = int(max(0, attempted_products))
    runtime_state["last_run_finished_at"] = datetime.now(timezone.utc).isoformat()
    runtime_state["consecutive_zero_insert_runs"] = int(max(0, consecutive_zero))

    if attempted_products > 0 and inserted == 0 and consecutive_zero >= 2:
        runtime_state["degraded_reason"] = "repeated_zero_insert_runs"
    else:
        runtime_state.pop("degraded_reason", None)

    config["runtime_state"] = runtime_state
    return runtime_state != previous_state


def _find_product(session: Session, row: dict[str, Any]) -> Product | None:
    if row.get("sku"):
        sku = str(row["sku"]).strip().lower()
        stmt = select(Product).where(func.lower(Product.sku) == sku)
        product = session.scalars(stmt).first()
        if product:
            return product

    if row.get("name"):
        name = str(row["name"]).strip().lower()
        stmt = select(Product).where(func.lower(Product.name) == name)
        return session.scalars(stmt).first()

    return None


def _merge_alias_map(config: dict[str, Any]) -> dict[str, str]:
    merged = dict(ALIAS_TOKEN_MAP)
    source_map = config.get("token_alias_map")
    if isinstance(source_map, dict):
        for key, value in source_map.items():
            token_key = str(key).strip().lower()
            token_value = str(value).strip().lower()
            if token_key and token_value:
                merged[token_key] = token_value
    return merged


def _normalize_token(token: str, alias_map: dict[str, str]) -> list[str]:
    base = alias_map.get(token, token)
    normalized = [base]

    # Normalize capacity/power/speed style tokens for better cross-site matching.
    match = UNIT_TOKEN_PATTERN.match(base)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        normalized.append(f"{value}{unit}")
        if unit == "tb":
            normalized.append(f"{value * 1024}gb")
    elif re.match(r"^\d+g$", base):
        normalized.append(f"{base}b")

    # Keep tail numeric model signatures (e.g., b550m -> 550m, i512400f -> 12400f).
    tail = re.sub(r"^[a-z]+", "", base)
    if tail and tail != base:
        normalized.append(tail)
    head = re.sub(r"\d.*$", "", base)
    if head and head != base:
        normalized.append(head)

    return normalized


def _tokenize(value: str, alias_map: dict[str, str] | None = None) -> list[str]:
    alias = alias_map or ALIAS_TOKEN_MAP
    raw_tokens = TOKEN_PATTERN.findall(value.lower())
    expanded: list[str] = []
    for token in raw_tokens:
        expanded.extend(_normalize_token(token, alias))
    return _unique_preserve_order(expanded)


def _unique_preserve_order(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _default_required_terms(product: Product) -> list[str]:
    alias_map = ALIAS_TOKEN_MAP
    tokens = [token for token in _tokenize(product.name, alias_map) if token not in STOP_TOKENS]
    tokens = _unique_preserve_order(tokens)
    model_tokens = [token for token in tokens if any(ch.isdigit() for ch in token)]
    required = model_tokens[:3]
    if not required:
        required = [token for token in tokens if token not in STOP_TOKENS][:2]
    return _unique_preserve_order([term for term in required if len(term) >= 2])


def _required_terms_for_product(product: Product, config: dict[str, Any]) -> list[str]:
    alias_map = _merge_alias_map(config)
    required_terms_map = config.get("required_terms_map", {})
    if isinstance(required_terms_map, dict):
        mapped = required_terms_map.get(product.sku) or required_terms_map.get(product.sku.lower())
        if isinstance(mapped, list):
            mapped_terms = [
                token
                for term in mapped
                for token in _tokenize(str(term).strip().lower(), alias_map)
                if token
            ]
            return _unique_preserve_order(mapped_terms)

    required = _default_required_terms(product)
    sku_alias_map = config.get("sku_alias_map", {})
    if isinstance(sku_alias_map, dict):
        alias_terms = sku_alias_map.get(product.sku) or sku_alias_map.get(product.sku.lower())
        if isinstance(alias_terms, list):
            for term in alias_terms:
                required.extend(_tokenize(str(term), alias_map))
    return _unique_preserve_order(required)


def _name_contains_all_terms(name: str, required_terms: list[str], config: dict[str, Any]) -> bool:
    if not required_terms:
        return True
    alias_map = _merge_alias_map(config)
    normalized_tokens = set(_tokenize(name, alias_map))
    return all(term in normalized_tokens for term in required_terms)


def _name_match_score(product: Product, row_name: str, config: dict[str, Any]) -> tuple[float, float, float, float]:
    alias_map = _merge_alias_map(config)
    row_tokens = set(_tokenize(row_name, alias_map))
    product_tokens = set(_tokenize(product.name, alias_map))
    if not row_tokens or not product_tokens:
        return (0.0, 0.0, 0.0, 0.0)

    overlap = row_tokens.intersection(product_tokens)
    token_coverage = len(overlap) / max(len(product_tokens), 1)
    row_numeric = {token for token in row_tokens if any(ch.isdigit() for ch in token)}
    product_numeric = {token for token in product_tokens if any(ch.isdigit() for ch in token)}
    numeric_overlap = row_numeric.intersection(product_numeric)
    numeric_coverage = (
        len(numeric_overlap) / max(len(product_numeric), 1)
        if product_numeric
        else 0.5
    )
    product_phrase = " ".join(sorted(product_tokens))
    row_phrase = " ".join(sorted(row_tokens))
    fuzzy_ratio = SequenceMatcher(None, product_phrase, row_phrase).ratio()

    score = (0.50 * token_coverage) + (0.35 * fuzzy_ratio) + (0.15 * numeric_coverage)
    return (min(max(score, 0.0), 1.0), fuzzy_ratio, token_coverage, numeric_coverage)


def _build_product_query(product: Product, config: dict[str, Any]) -> str:
    query_map = config.get("query_override_map", {})
    if isinstance(query_map, dict):
        override = query_map.get(product.sku) or query_map.get(product.sku.lower())
        if isinstance(override, str) and override.strip():
            return override.strip()

    max_terms = int(config.get("max_query_terms", 6))
    tokens = [token for token in _tokenize(product.name, _merge_alias_map(config)) if token not in STOP_TOKENS]
    tokens = _unique_preserve_order(tokens)
    if not tokens:
        return product.name
    return " ".join(tokens[:max(max_terms, 1)])


def _find_best_row_for_product(rows: list[dict[str, Any]], product: Product, config: dict[str, Any]) -> dict[str, Any] | None:
    min_score = float(config.get("min_name_match_score", 0.35))
    min_fuzzy_ratio = float(config.get("min_fuzzy_ratio", 0.40))
    allow_variant_substitution_skus = config.get("allow_variant_substitution_skus", [])
    allow_variant = False
    if isinstance(allow_variant_substitution_skus, list):
        sku_l = product.sku.lower()
        allow_variant = any(str(candidate).strip().lower() == sku_l for candidate in allow_variant_substitution_skus)
    if allow_variant:
        min_score = float(config.get("variant_min_name_match_score", min(min_score, 0.30)))
        min_fuzzy_ratio = float(config.get("variant_min_fuzzy_ratio", min(min_fuzzy_ratio, 0.30)))
    required_terms = _required_terms_for_product(product, config)

    best_row: dict[str, Any] | None = None
    best_price: Decimal | None = None
    best_score = 0.0

    for row in rows:
        row_name = str(row.get("name") or "").strip()
        if not row_name:
            continue

        if required_terms and not _name_contains_all_terms(row_name, required_terms, config):
            continue

        score, fuzzy_ratio, token_coverage, numeric_coverage = _name_match_score(product, row_name, config)
        if score < min_score:
            continue
        if fuzzy_ratio < min_fuzzy_ratio and token_coverage < min_score:
            continue

        price = Decimal(str(row["price"]))
        scored_row = row | {
            "_match_score": round(score, 4),
            "_fuzzy_ratio": round(fuzzy_ratio, 4),
            "_token_coverage": round(token_coverage, 4),
            "_numeric_coverage": round(numeric_coverage, 4),
        }
        if best_row is None:
            best_row = scored_row
            best_price = price
            best_score = score
            continue

        assert best_price is not None
        # Prioritize better match quality; use cheaper price only as tie-breaker.
        if score > (best_score + 0.02) or (abs(score - best_score) <= 0.02 and price < best_price):
            best_row = scored_row
            best_price = price
            best_score = score

    return best_row


def _find_product_by_internal_sku(session: Session, internal_sku: str) -> Product | None:
    sku = internal_sku.strip().lower()
    if not sku:
        return None
    stmt = select(Product).where(func.lower(Product.sku) == sku)
    return session.scalars(stmt).first()


def _resolve_product(session: Session, row: dict[str, Any], config: dict[str, Any]) -> Product | None:
    target_sku = config.get("target_sku")
    if isinstance(target_sku, str) and target_sku.strip():
        product = _find_product_by_internal_sku(session, target_sku)
        if product:
            required_terms = _required_terms_for_product(product, config)
            row_name = str(row.get("name") or "")
            if not required_terms or _name_contains_all_terms(row_name, required_terms):
                return product

    sku_map = config.get("sku_map", {})
    if isinstance(sku_map, dict):
        competitor_sku = str(row.get("sku") or "").strip().lower()
        mapped_internal_sku = sku_map.get(competitor_sku)
        if mapped_internal_sku:
            product = _find_product_by_internal_sku(session, str(mapped_internal_sku))
            if product:
                return product

    name_contains_map = config.get("name_contains_map", {})
    if isinstance(name_contains_map, dict):
        name = str(row.get("name") or "").strip().lower()
        if name:
            for phrase, internal_sku in name_contains_map.items():
                if str(phrase).strip().lower() in name:
                    product = _find_product_by_internal_sku(session, str(internal_sku))
                    if product:
                        return product

    return _find_product(session, row)


def _insert_snapshot(session: Session, source: CompetitorSource, product: Product, row: dict[str, Any], config: dict[str, Any]) -> None:
    competitor_sku = row.get("sku")
    if competitor_sku is not None:
        competitor_sku = str(competitor_sku).strip() or None
    if competitor_sku and len(competitor_sku) > 120:
        competitor_sku = competitor_sku[:120]

    snapshot = CompetitorPriceSnapshot(
        source_id=source.id,
        product_id=product.id,
        competitor_sku=competitor_sku,
        competitor_price=Decimal(str(row["price"])),
        currency=str(config.get("currency", "PHP")),
        in_stock=row.get("in_stock"),
        scraped_at=datetime.now(timezone.utc),
        raw_payload_json=json.dumps(
            {
                "name": row.get("name"),
                "sku": row.get("sku"),
                "price_text": row.get("price_text"),
                "in_stock": row.get("in_stock"),
                "request_url": config.get("_request_url"),
                "match_score": row.get("_match_score"),
                "fuzzy_ratio": row.get("_fuzzy_ratio"),
                "token_coverage": row.get("_token_coverage"),
                "numeric_coverage": row.get("_numeric_coverage"),
                "url": row.get("url"),
            }
        ),
    )
    session.add(snapshot)


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _should_auto_discover_url(
    *,
    candidate_url: str,
    score: float,
    fuzzy_ratio: float,
    config: dict[str, Any],
) -> bool:
    if not candidate_url:
        return False

    parsed = urlparse(candidate_url)
    lowered = candidate_url.lower()
    path = parsed.path.lower().strip()
    if not path:
        return False
    if path.startswith("/search"):
        return False
    if path == "/shop":
        return False

    required_pattern = str(config.get("discovery_url_pattern", "")).strip().lower()
    if required_pattern and required_pattern not in lowered:
        return False

    min_score = float(config.get("discovery_min_name_match_score", 0.78))
    min_fuzzy = float(config.get("discovery_min_fuzzy_ratio", 0.55))
    return score >= min_score and fuzzy_ratio >= min_fuzzy


def _extract_shopify_suggest_rows(payload: dict[str, Any], *, max_rows: int = 20) -> list[dict[str, Any]]:
    resources = payload.get("resources")
    if not isinstance(resources, dict):
        return []

    results = resources.get("results")
    if not isinstance(results, dict):
        return []

    products = results.get("products")
    if not isinstance(products, list):
        return []

    rows: list[dict[str, Any]] = []
    for product_payload in products[: max(max_rows, 1)]:
        if not isinstance(product_payload, dict):
            continue

        name = str(product_payload.get("title") or "").strip()
        if not name:
            continue

        raw_price = (
            product_payload.get("price")
            or product_payload.get("price_min")
            or product_payload.get("price_max")
        )
        price_text = str(raw_price or "").strip()
        if not price_text:
            continue

        try:
            normalized_price = normalize_price(price_text)
        except ValueError:
            continue

        competitor_sku: str | None = None
        variants = product_payload.get("variants")
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                variant_sku = str(variant.get("sku") or "").strip()
                if variant_sku:
                    competitor_sku = variant_sku
                    break
        if competitor_sku is None:
            handle = str(product_payload.get("handle") or "").strip()
            competitor_sku = handle or None

        rows.append(
            {
                "name": name,
                "sku": competitor_sku,
                "price_text": price_text,
                "price": normalized_price,
                "in_stock": bool(product_payload.get("available")),
                "url": product_payload.get("url"),
            }
        )

    return rows


def _run_standard_source(
    session: Session,
    source: CompetitorSource,
    config: dict[str, Any],
    active_fetcher: FetchHtmlFn,
    *,
    verbose: bool = False,
) -> int:
    html = active_fetcher(source, config)
    rows = parse_price_rows(html, config)
    _log(verbose, f"scraper_source_parsed source={source.name} parsed_rows={len(rows)} mode=standard")
    best_by_product: dict[int, dict[str, Any]] = {}

    for row in rows:
        product = _resolve_product(session, row, config)
        if product is None:
            continue

        current = best_by_product.get(product.id)
        if current is None or Decimal(str(row["price"])) < Decimal(str(current["price"])):
            best_by_product[product.id] = row | {"_product": product}

    for row in best_by_product.values():
        product = row["_product"]
        _insert_snapshot(session, source, product, row, config)

    return len(best_by_product)


def _run_per_product_source(
    session: Session,
    source: CompetitorSource,
    config: dict[str, Any],
    active_fetcher: FetchHtmlFn,
    active_products: list[Product],
    *,
    verbose: bool = False,
) -> tuple[int, bool]:
    search_template = str(config.get("search_url_template", "")).strip()
    if not search_template:
        raise ValueError(f"Missing required 'search_url_template' for source {source.name}")

    product_url_map_config = config.get("product_url_map", {})
    product_url_map: dict[str, str] = {}
    if isinstance(product_url_map_config, dict):
        product_url_map = {
            str(key): str(value).strip()
            for key, value in product_url_map_config.items()
            if str(value).strip()
        }

    auto_discovery_enabled = _as_bool(config.get("enable_auto_product_url_discovery"), default=False)
    config_changed = False
    inserted = 0
    for product in active_products:
        query_text = _build_product_query(product, config)
        direct_product_url = None
        direct_product_url = product_url_map.get(product.sku) or product_url_map.get(product.sku.lower())
        if isinstance(direct_product_url, str):
            direct_product_url = direct_product_url.strip() or None
        else:
            direct_product_url = None

        search_url = search_template.format(query=quote_plus(query_text), raw_query=query_text, sku=product.sku)
        request_candidates: list[tuple[str, str, bool]] = []
        if direct_product_url:
            request_candidates.append(("direct_product_url", direct_product_url, True))
        request_candidates.append(("search", search_url, False))

        best_row: dict[str, Any] | None = None
        request_config: dict[str, Any] | None = None
        used_mode = "search"
        for mode, request_url, is_direct in request_candidates:
            _log(
                verbose,
                (
                    f"scraper_product_query source={source.name} sku={product.sku} "
                    f"query={query_text} url={request_url} mode={mode}"
                ),
            )

            candidate_config = dict(config)
            candidate_config["_request_url"] = request_url
            if is_direct:
                # Product pages may need different selectors than listing/search pages.
                candidate_config["item_selector"] = str(
                    config.get("product_page_item_selector", config.get("item_selector", ""))
                )
                candidate_config["name_selector"] = str(
                    config.get("product_page_name_selector", config.get("name_selector", ""))
                )
                candidate_config["price_selector"] = str(
                    config.get("product_page_price_selector", config.get("price_selector", ""))
                )
                if "product_page_sku_selector" in config:
                    candidate_config["sku_selector"] = str(config.get("product_page_sku_selector") or "")
                if "product_page_in_stock_selector" in config:
                    candidate_config["in_stock_selector"] = str(config.get("product_page_in_stock_selector") or "")
                if "product_page_in_stock_text" in config:
                    candidate_config["in_stock_text"] = str(config.get("product_page_in_stock_text") or "")

            try:
                html = active_fetcher(source, candidate_config)
                rows = parse_price_rows(html, candidate_config)
            except Exception as exc:  # pragma: no cover - exercised via job runs
                _log(
                    verbose,
                    (
                        f"scraper_product_request_error source={source.name} sku={product.sku} "
                        f"mode={mode} detail={exc}"
                    ),
                )
                continue
            _log(
                verbose,
                (
                    f"scraper_product_parsed source={source.name} sku={product.sku} "
                    f"parsed_rows={len(rows)} mode={mode}"
                ),
            )
            candidate_best = _find_best_row_for_product(rows, product, candidate_config)
            if candidate_best is None:
                _log(
                    verbose,
                    f"scraper_product_no_match_attempt source={source.name} sku={product.sku} mode={mode}",
                )
                continue

            best_row = candidate_best
            request_config = candidate_config
            used_mode = mode
            break

        if best_row is None or request_config is None:
            _log(verbose, f"scraper_product_no_match source={source.name} sku={product.sku}")
            continue

        if auto_discovery_enabled and used_mode == "search":
            candidate_url = str(best_row.get("url") or "").strip()
            candidate_score = float(best_row.get("_match_score") or 0.0)
            candidate_fuzzy = float(best_row.get("_fuzzy_ratio") or 0.0)
            if _should_auto_discover_url(
                candidate_url=candidate_url,
                score=candidate_score,
                fuzzy_ratio=candidate_fuzzy,
                config=request_config,
            ):
                current_mapped_url = product_url_map.get(product.sku)
                if current_mapped_url != candidate_url:
                    product_url_map[product.sku] = candidate_url
                    config_changed = True
                    _log(
                        verbose,
                        (
                            f"scraper_product_url_discovered source={source.name} sku={product.sku} "
                            f"url={candidate_url} score={candidate_score:.4f} fuzzy={candidate_fuzzy:.4f}"
                        ),
                    )

        _insert_snapshot(session, source, product, best_row, request_config)
        _log(
            verbose,
            (
                f"scraper_product_match source={source.name} sku={product.sku} "
                f"mode={used_mode} price={best_row['price']} score={best_row.get('_match_score')} "
                f"fuzzy={best_row.get('_fuzzy_ratio')} name={best_row.get('name')}"
            ),
        )
        inserted += 1

    if config_changed:
        config["product_url_map"] = product_url_map

    return inserted, config_changed


def _run_shopify_suggest_source(
    session: Session,
    source: CompetitorSource,
    config: dict[str, Any],
    active_fetcher: FetchHtmlFn,
    active_products: list[Product],
    *,
    verbose: bool = False,
) -> int:
    search_template = str(config.get("search_url_template", "")).strip()
    if not search_template:
        raise ValueError(f"Missing required 'search_url_template' for source {source.name}")

    max_rows_per_query = int(config.get("max_rows_per_query", 20))
    product_url_map_config = config.get("product_url_map", {})
    product_url_map: dict[str, str] = {}
    if isinstance(product_url_map_config, dict):
        product_url_map = {
            str(key): str(value).strip()
            for key, value in product_url_map_config.items()
            if str(value).strip()
        }

    inserted = 0

    for product in active_products:
        query_text = _build_product_query(product, config)
        direct_product_url = product_url_map.get(product.sku) or product_url_map.get(product.sku.lower())
        if isinstance(direct_product_url, str):
            direct_product_url = direct_product_url.strip() or None
        else:
            direct_product_url = None

        best_row: dict[str, Any] | None = None
        request_config: dict[str, Any] | None = None
        used_mode = "shopify_suggest_json"

        if direct_product_url:
            _log(
                verbose,
                (
                    f"scraper_product_query source={source.name} sku={product.sku} "
                    f"query={query_text} url={direct_product_url} mode=direct_product_url"
                ),
            )
            direct_config = dict(config)
            direct_config["_request_url"] = direct_product_url
            direct_config["item_selector"] = str(
                config.get("product_page_item_selector", config.get("item_selector", "body"))
            )
            direct_config["name_selector"] = str(
                config.get("product_page_name_selector", config.get("name_selector", "h1"))
            )
            direct_config["price_selector"] = str(
                config.get("product_page_price_selector", config.get("price_selector", ".price"))
            )
            if "product_page_sku_selector" in config:
                direct_config["sku_selector"] = str(config.get("product_page_sku_selector") or "")
            if "product_page_in_stock_selector" in config:
                direct_config["in_stock_selector"] = str(config.get("product_page_in_stock_selector") or "")
            if "product_page_in_stock_text" in config:
                direct_config["in_stock_text"] = str(config.get("product_page_in_stock_text") or "")

            try:
                direct_html = active_fetcher(source, direct_config)
                direct_rows = parse_price_rows(direct_html, direct_config)
            except Exception as exc:  # pragma: no cover - exercised via job runs
                _log(
                    verbose,
                    (
                        f"scraper_product_request_error source={source.name} sku={product.sku} "
                        f"mode=direct_product_url detail={exc}"
                    ),
                )
                direct_rows = []
            _log(
                verbose,
                (
                    f"scraper_product_parsed source={source.name} sku={product.sku} "
                    f"parsed_rows={len(direct_rows)} mode=direct_product_url"
                ),
            )
            direct_best = _find_best_row_for_product(direct_rows, product, direct_config)
            if direct_best is not None:
                best_row = direct_best
                request_config = direct_config
                used_mode = "direct_product_url"
            else:
                _log(
                    verbose,
                    f"scraper_product_no_match_attempt source={source.name} sku={product.sku} mode=direct_product_url",
                )

        if best_row is None or request_config is None:
            request_url = search_template.format(query=quote_plus(query_text), raw_query=query_text, sku=product.sku)
            _log(
                verbose,
                (
                    f"scraper_product_query source={source.name} sku={product.sku} "
                    f"query={query_text} url={request_url} mode=shopify_suggest_json"
                ),
            )

            request_config = dict(config)
            request_config["_request_url"] = request_url

            try:
                payload_text = active_fetcher(source, request_config)
            except Exception as exc:  # pragma: no cover - exercised via job runs
                _log(
                    verbose,
                    (
                        f"scraper_product_request_error source={source.name} sku={product.sku} "
                        f"mode=shopify_suggest_json detail={exc}"
                    ),
                )
                continue
            try:
                payload = json.loads(payload_text)
            except json.JSONDecodeError:
                _log(verbose, f"scraper_product_parse_error source={source.name} sku={product.sku} format=json")
                continue

            rows = _extract_shopify_suggest_rows(payload, max_rows=max_rows_per_query)
            _log(
                verbose,
                (
                    f"scraper_product_parsed source={source.name} sku={product.sku} "
                    f"parsed_rows={len(rows)} mode=shopify_suggest_json"
                ),
            )
            best_row = _find_best_row_for_product(rows, product, request_config)
            if best_row is None:
                _log(verbose, f"scraper_product_no_match source={source.name} sku={product.sku}")
                continue

        _insert_snapshot(session, source, product, best_row, request_config)
        _log(
            verbose,
            (
                f"scraper_product_match source={source.name} sku={product.sku} "
                f"mode={used_mode} price={best_row['price']} score={best_row.get('_match_score')} "
                f"fuzzy={best_row.get('_fuzzy_ratio')} name={best_row.get('name')}"
            ),
        )
        inserted += 1

    return inserted


def run_scraper_cycle(
    db: Session | None = None,
    fetcher: FetchHtmlFn | None = None,
    *,
    verbose: bool = False,
    source_name_filters: list[str] | None = None,
    exclude_source_name_filters: list[str] | None = None,
) -> int:
    own_session = db is None
    session = db or SessionLocal()
    active_fetcher = fetcher or _default_fetcher
    inserted_rows = 0

    try:
        all_sources = list(session.scalars(select(CompetitorSource).where(CompetitorSource.enabled.is_(True))).all())
        sources = _filter_sources(
            all_sources,
            include_patterns=source_name_filters,
            exclude_patterns=exclude_source_name_filters,
        )
        active_products = list(session.scalars(select(Product).where(Product.active.is_(True))).all())
        if not sources:
            _emit(
                "scraper_cycle_warning detail=no_sources_selected "
                f"enabled_sources={len(all_sources)} "
                f"source_name_filters={source_name_filters or []} "
                f"exclude_source_name_filters={exclude_source_name_filters or []}"
            )
            return 0

        _log(
            verbose,
            (
                f"scraper_cycle_start sources={len(sources)} enabled_sources={len(all_sources)} "
                f"active_products={len(active_products)} started_at={datetime.now(timezone.utc).isoformat()}"
            ),
        )
        for source in sources:
            source_inserted = 0
            source_config_updated = False
            source_started = perf_counter()
            try:
                config = _load_config(source)
                mode = str(config.get("mode", "standard")).strip().lower()
                _log(verbose, f"scraper_source_start source={source.name} mode={mode}")
                if mode == "per_product_search":
                    source_inserted, source_config_updated = _run_per_product_source(
                        session,
                        source,
                        config,
                        active_fetcher,
                        active_products,
                        verbose=verbose,
                    )
                elif mode == "shopify_suggest_json":
                    source_inserted = _run_shopify_suggest_source(
                        session,
                        source,
                        config,
                        active_fetcher,
                        active_products,
                        verbose=verbose,
                    )
                else:
                    source_inserted = _run_standard_source(
                        session,
                        source,
                        config,
                        active_fetcher,
                        verbose=verbose,
                    )

                attempted_products = len(active_products) if mode in {"per_product_search", "shopify_suggest_json"} else 0
                state_changed = _update_runtime_state(
                    config,
                    attempted_products=attempted_products,
                    inserted=source_inserted,
                )
                source_config_updated = source_config_updated or state_changed

                if source_config_updated:
                    source.scrape_config_json = json.dumps(config)
                source.last_run_at = datetime.now(timezone.utc)
                session.commit()
                inserted_rows += source_inserted
                elapsed = perf_counter() - source_started
                _log(
                    verbose,
                    (
                        f"scraper_source_done source={source.name} inserted={source_inserted} "
                        f"elapsed_seconds={elapsed:.2f}"
                    ),
                )
            except Exception as exc:
                session.rollback()
                _emit(f"scraper_source_error source={source.name} detail={exc}")
                continue

        _log(
            verbose,
            (
                f"scraper_cycle_done inserted_total={inserted_rows} "
                f"finished_at={datetime.now(timezone.utc).isoformat()}"
            ),
        )
        return inserted_rows
    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run competitor scraper job cycle.")
    parser.add_argument("--verbose", action="store_true", help="Print detailed source and product-level scraper logs.")
    parser.add_argument(
        "--source-name",
        action="append",
        default=[],
        help="Case-insensitive partial source-name filter. Repeat flag for multiple filters.",
    )
    parser.add_argument(
        "--exclude-source-name",
        action="append",
        default=[],
        help="Case-insensitive partial source-name exclusion filter. Repeat flag for multiple filters.",
    )
    args = parser.parse_args()
    inserted = run_scraper_cycle(
        verbose=args.verbose,
        source_name_filters=args.source_name,
        exclude_source_name_filters=args.exclude_source_name,
    )
    _emit(f"scraper_rows_inserted={inserted}")


if __name__ == "__main__":
    main()
