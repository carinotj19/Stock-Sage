import json

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, CompetitorPriceSnapshot, CompetitorSource, Product, Supplier
from app.jobs.run_scraper_cycle import _default_fetcher, run_scraper_cycle
from app.scrapers.parser_utils import normalize_price


TEST_DATABASE_URL = "sqlite:///./data/test_scraper_pipeline.db"


def _build_test_engine():
    return create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})


def test_normalize_price_ignores_embedded_savings_amount() -> None:
    parsed = normalize_price("₱44,800.00 ₱43,904.00 SAVE ₱896.00")
    assert str(parsed) == "43904.00"


def test_scraper_pipeline_persists_mapped_rows() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    html = """
    <html>
      <body>
        <div class="item">
          <span class="name">Milk</span>
          <span class="sku">SKU-100</span>
          <span class="price">$3.99</span>
          <span class="stock">In Stock</span>
        </div>
        <div class="item">
          <span class="name">Unknown Product</span>
          <span class="sku">SKU-404</span>
          <span class="price">$9.99</span>
          <span class="stock">In Stock</span>
        </div>
      </body>
    </html>
    """

    with TestingSessionLocal() as db:
        supplier = Supplier(name="Scraper Supplier", lead_time_days_default=3)
        db.add(supplier)
        db.flush()

        db.add(
            Product(
                sku="SKU-100",
                name="Milk",
                supplier_id=supplier.id,
                cost_price=2.0,
                sell_price=4.5,
                reorder_min_qty=5,
                reorder_multiple=5,
                safety_stock=2,
                active=True,
            )
        )
        db.flush()

        source = CompetitorSource(
            name="Competitor A",
            base_url="http://example.test/prices",
            scrape_config_json=json.dumps(
                {
                    "item_selector": ".item",
                    "name_selector": ".name",
                    "sku_selector": ".sku",
                    "price_selector": ".price",
                    "in_stock_selector": ".stock",
                    "in_stock_text": "in stock",
                    "currency": "USD",
                }
            ),
            enabled=True,
        )
        db.add(source)
        db.commit()

        inserted = run_scraper_cycle(db=db, fetcher=lambda _source, _config: html)
        assert inserted == 1

        snapshot_count = db.scalar(select(func.count()).select_from(CompetitorPriceSnapshot))
        assert snapshot_count == 1

        snapshot = db.scalars(select(CompetitorPriceSnapshot)).first()
        assert snapshot is not None
        assert str(snapshot.competitor_price) == "3.99"
        assert snapshot.currency == "USD"

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_scraper_pipeline_per_product_search_covers_all_active_inventory() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        supplier = Supplier(name="Per Product Supplier", lead_time_days_default=4)
        db.add(supplier)
        db.flush()

        cpu = Product(
            sku="CPU-TEST-5600",
            name="AMD Ryzen 5 5600 6-Core Processor",
            supplier_id=supplier.id,
            cost_price=6000.0,
            sell_price=6900.0,
            reorder_min_qty=2,
            reorder_multiple=1,
            safety_stock=1,
            active=True,
        )
        gpu = Product(
            sku="GPU-TEST-4060",
            name="NVIDIA GeForce RTX 4060 8GB Graphics Card",
            supplier_id=supplier.id,
            cost_price=18000.0,
            sell_price=20000.0,
            reorder_min_qty=1,
            reorder_multiple=1,
            safety_stock=1,
            active=True,
        )
        db.add_all([cpu, gpu])
        db.flush()

        source = CompetitorSource(
            name="Per Product Search Source",
            base_url="http://example.test/search",
            scrape_config_json=json.dumps(
                {
                    "mode": "per_product_search",
                    "search_url_template": "http://example.test/search?q={query}",
                    "query_override_map": {
                        "CPU-TEST-5600": "ryzen 5 5600",
                        "GPU-TEST-4060": "rtx 4060",
                    },
                    "required_terms_map": {
                        "CPU-TEST-5600": ["ryzen", "5600"],
                        "GPU-TEST-4060": ["rtx", "4060"],
                    },
                    "item_selector": ".item",
                    "name_selector": ".name",
                    "price_selector": ".price",
                    "currency": "PHP",
                }
            ),
            enabled=True,
        )
        db.add(source)
        db.commit()

        def fake_fetcher(_source: CompetitorSource, config: dict) -> str:
            request_url = str(config.get("_request_url", ""))
            if "ryzen+5+5600" in request_url:
                return """
                <div class="item">
                  <span class="name">AMD Ryzen 5 5600 6-Core Processor</span>
                  <span class="price">₱6,990.00</span>
                </div>
                <div class="item">
                  <span class="name">Intel Core i5-12400F 6-Core Processor</span>
                  <span class="price">₱8,990.00</span>
                </div>
                """
            if "rtx+4060" in request_url:
                return """
                <div class="item">
                  <span class="name">MSI GeForce RTX 4060 Ventus 2X 8G OC</span>
                  <span class="price">₱19,990.00</span>
                </div>
                <div class="item">
                  <span class="name">NVIDIA GeForce RTX 4070 SUPER</span>
                  <span class="price">₱32,500.00</span>
                </div>
                """
            return "<div></div>"

        inserted = run_scraper_cycle(db=db, fetcher=fake_fetcher)
        assert inserted == 2

        snapshots = db.scalars(select(CompetitorPriceSnapshot)).all()
        assert len(snapshots) == 2
        assert {snapshot.product_id for snapshot in snapshots} == {cpu.id, gpu.id}

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_scraper_pipeline_shopify_suggest_mode_covers_active_inventory() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        supplier = Supplier(name="Shopify Suggest Supplier", lead_time_days_default=4)
        db.add(supplier)
        db.flush()

        cpu = Product(
            sku="CPU-TEST-5600",
            name="AMD Ryzen 5 5600 6-Core Processor",
            supplier_id=supplier.id,
            cost_price=6000.0,
            sell_price=6900.0,
            reorder_min_qty=2,
            reorder_multiple=1,
            safety_stock=1,
            active=True,
        )
        gpu = Product(
            sku="GPU-TEST-4060",
            name="MSI GeForce RTX 4060 Ventus 2X 8G OC",
            supplier_id=supplier.id,
            cost_price=18000.0,
            sell_price=20000.0,
            reorder_min_qty=1,
            reorder_multiple=1,
            safety_stock=1,
            active=True,
        )
        db.add_all([cpu, gpu])
        db.flush()

        source = CompetitorSource(
            name="Shopify Suggest Source",
            base_url="http://example.test/suggest.json",
            scrape_config_json=json.dumps(
                {
                    "mode": "shopify_suggest_json",
                    "search_url_template": "http://example.test/suggest.json?q={query}",
                    "query_override_map": {
                        "CPU-TEST-5600": "ryzen 5 5600",
                        "GPU-TEST-4060": "rtx 4060",
                    },
                    "required_terms_map": {
                        "CPU-TEST-5600": ["ryzen", "5600"],
                        "GPU-TEST-4060": ["rtx", "4060"],
                    },
                    "currency": "PHP",
                }
            ),
            enabled=True,
        )
        db.add(source)
        db.commit()

        def fake_fetcher(_source: CompetitorSource, config: dict) -> str:
            request_url = str(config.get("_request_url", ""))
            if "ryzen+5+5600" in request_url:
                return json.dumps(
                    {
                        "resources": {
                            "results": {
                                "products": [
                                    {
                                        "title": "AMD Ryzen 5 5600 6-Core Processor",
                                        "price": "6990.00",
                                        "available": True,
                                        "handle": "amd-ryzen-5-5600",
                                    },
                                    {
                                        "title": "Intel Core i5-12400F 6-Core Processor",
                                        "price": "8990.00",
                                        "available": True,
                                        "handle": "intel-core-i5-12400f",
                                    },
                                ]
                            }
                        }
                    }
                )

            if "rtx+4060" in request_url:
                return json.dumps(
                    {
                        "resources": {
                            "results": {
                                "products": [
                                    {
                                        "title": "MSI GeForce RTX 4060 Ventus 2X 8G OC",
                                        "price": "19990.00",
                                        "available": True,
                                        "handle": "msi-rtx-4060-ventus-2x",
                                    },
                                    {
                                        "title": "NVIDIA GeForce RTX 4070 SUPER",
                                        "price": "32500.00",
                                        "available": True,
                                        "handle": "nvidia-rtx-4070-super",
                                    },
                                ]
                            }
                        }
                    }
                )

            return json.dumps({"resources": {"results": {"products": []}}})

        inserted = run_scraper_cycle(db=db, fetcher=fake_fetcher)
        assert inserted == 2

        snapshots = db.scalars(select(CompetitorPriceSnapshot)).all()
        assert len(snapshots) == 2
        assert {snapshot.product_id for snapshot in snapshots} == {cpu.id, gpu.id}

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_scraper_pipeline_per_product_supports_direct_product_url_fallback() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        supplier = Supplier(name="Direct URL Supplier", lead_time_days_default=4)
        db.add(supplier)
        db.flush()

        gpu = Product(
            sku="GPU-TEST-5070",
            name="MSI GeForce RTX 5070 Shadow 2X OC 12GB GDDR7 Graphics Card",
            supplier_id=supplier.id,
            cost_price=38000.0,
            sell_price=43000.0,
            reorder_min_qty=1,
            reorder_multiple=1,
            safety_stock=1,
            active=True,
        )
        db.add(gpu)
        db.flush()

        direct_url = "https://example.test/products/msi-geforce-rtx-5070-shadow-2x-oc"
        source = CompetitorSource(
            name="Direct URL Source",
            base_url="http://example.test/search",
            scrape_config_json=json.dumps(
                {
                    "mode": "per_product_search",
                    "search_url_template": "http://example.test/search?q={query}",
                    "query_override_map": {
                        "GPU-TEST-5070": "rtx 5070",
                    },
                    "required_terms_map": {
                        "GPU-TEST-5070": ["rtx", "5070"],
                    },
                    "item_selector": ".item",
                    "name_selector": ".name",
                    "price_selector": ".price",
                    "product_url_map": {
                        "GPU-TEST-5070": direct_url,
                    },
                    "product_page_item_selector": "body",
                    "product_page_name_selector": "h1",
                    "product_page_price_selector": ".price",
                    "currency": "PHP",
                }
            ),
            enabled=True,
        )
        db.add(source)
        db.commit()

        seen_request_urls: list[str] = []

        def fake_fetcher(_source: CompetitorSource, config: dict) -> str:
            request_url = str(config.get("_request_url", ""))
            seen_request_urls.append(request_url)
            if "/products/" in request_url:
                return """
                <html>
                  <body>
                    <h1>MSI GeForce RTX 5070 Shadow 2X OC 12GB GDDR7 Graphics Card</h1>
                    <div class="price">â‚±40,376.00</div>
                  </body>
                </html>
                """
            return """
            <div class="item">
              <span class="name">Unrelated Product</span>
              <span class="price">â‚±99,999.00</span>
            </div>
            """

        inserted = run_scraper_cycle(db=db, fetcher=fake_fetcher)
        assert inserted == 1
        assert any(url == direct_url for url in seen_request_urls)

        snapshot = db.scalars(select(CompetitorPriceSnapshot)).first()
        assert snapshot is not None
        assert snapshot.product_id == gpu.id
        assert str(snapshot.competitor_price) == "40376.00"

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_scraper_pipeline_per_product_falls_back_to_search_when_direct_url_has_no_match() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        supplier = Supplier(name="Direct Fallback Supplier", lead_time_days_default=4)
        db.add(supplier)
        db.flush()

        cpu = Product(
            sku="CPU-TEST-12400F",
            name="Intel Core i5-12400F 6-Core Processor",
            supplier_id=supplier.id,
            cost_price=8000.0,
            sell_price=9000.0,
            reorder_min_qty=1,
            reorder_multiple=1,
            safety_stock=1,
            active=True,
        )
        db.add(cpu)
        db.flush()

        direct_url = "https://example.test/products/intel-core-i5-12400"
        source = CompetitorSource(
            name="Per Product Direct Fallback Source",
            base_url="http://example.test/search",
            scrape_config_json=json.dumps(
                {
                    "mode": "per_product_search",
                    "search_url_template": "http://example.test/search?q={query}",
                    "query_override_map": {"CPU-TEST-12400F": "intel i5 12400f"},
                    "required_terms_map": {"CPU-TEST-12400F": ["intel", "12400f"]},
                    "item_selector": ".item",
                    "name_selector": ".name",
                    "price_selector": ".price",
                    "product_url_map": {"CPU-TEST-12400F": direct_url},
                    "product_page_item_selector": "body",
                    "product_page_name_selector": "h1",
                    "product_page_price_selector": ".price",
                    "currency": "PHP",
                }
            ),
            enabled=True,
        )
        db.add(source)
        db.commit()

        seen_urls: list[str] = []

        def fake_fetcher(_source: CompetitorSource, config: dict) -> str:
            request_url = str(config.get("_request_url", ""))
            seen_urls.append(request_url)
            if request_url == direct_url:
                return """
                <html>
                  <body>
                    <h1>Unrelated Product</h1>
                    <div class="price">Ã¢â€šÂ±19,999.00</div>
                  </body>
                </html>
                """
            return """
            <div class="item">
              <span class="name">Intel Core i5-12400F 6-Core Processor</span>
              <span class="price">Ã¢â€šÂ±8,990.00</span>
            </div>
            """

        inserted = run_scraper_cycle(db=db, fetcher=fake_fetcher)
        assert inserted == 1
        assert any(url == direct_url for url in seen_urls)
        assert any("search?q=intel+i5+12400f" in url for url in seen_urls)

        snapshot = db.scalars(select(CompetitorPriceSnapshot)).first()
        assert snapshot is not None
        assert snapshot.product_id == cpu.id
        assert str(snapshot.competitor_price) == "8990.00"

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_scraper_pipeline_per_product_falls_back_to_search_when_direct_url_errors() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        supplier = Supplier(name="Direct Error Fallback Supplier", lead_time_days_default=4)
        db.add(supplier)
        db.flush()

        cpu = Product(
            sku="CPU-TEST-12400F",
            name="Intel Core i5-12400F 6-Core Processor",
            supplier_id=supplier.id,
            cost_price=8000.0,
            sell_price=9000.0,
            reorder_min_qty=1,
            reorder_multiple=1,
            safety_stock=1,
            active=True,
        )
        db.add(cpu)
        db.flush()

        direct_url = "https://example.test/products/intel-core-i5-12400"
        source = CompetitorSource(
            name="Per Product Direct Error Source",
            base_url="http://example.test/search",
            scrape_config_json=json.dumps(
                {
                    "mode": "per_product_search",
                    "search_url_template": "http://example.test/search?q={query}",
                    "query_override_map": {"CPU-TEST-12400F": "intel i5 12400f"},
                    "required_terms_map": {"CPU-TEST-12400F": ["intel", "12400f"]},
                    "item_selector": ".item",
                    "name_selector": ".name",
                    "price_selector": ".price",
                    "product_url_map": {"CPU-TEST-12400F": direct_url},
                    "product_page_item_selector": "body",
                    "product_page_name_selector": "h1",
                    "product_page_price_selector": ".price",
                    "currency": "PHP",
                }
            ),
            enabled=True,
        )
        db.add(source)
        db.commit()

        def fake_fetcher(_source: CompetitorSource, config: dict) -> str:
            request_url = str(config.get("_request_url", ""))
            if request_url == direct_url:
                raise RuntimeError("404 Not Found")
            return """
            <div class="item">
              <span class="name">Intel Core i5-12400F 6-Core Processor</span>
              <span class="price">Ã¢â€šÂ±8,990.00</span>
            </div>
            """

        inserted = run_scraper_cycle(db=db, fetcher=fake_fetcher)
        assert inserted == 1

        snapshot = db.scalars(select(CompetitorPriceSnapshot)).first()
        assert snapshot is not None
        assert snapshot.product_id == cpu.id
        assert str(snapshot.competitor_price) == "8990.00"

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_scraper_pipeline_shopify_supports_direct_product_url_fallback() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        supplier = Supplier(name="Shopify Direct URL Supplier", lead_time_days_default=4)
        db.add(supplier)
        db.flush()

        gpu = Product(
            sku="GPU-TEST-4060",
            name="MSI GeForce RTX 4060 Ventus 2X 8G OC",
            supplier_id=supplier.id,
            cost_price=18000.0,
            sell_price=20000.0,
            reorder_min_qty=1,
            reorder_multiple=1,
            safety_stock=1,
            active=True,
        )
        db.add(gpu)
        db.flush()

        direct_url = "https://example.test/products/msi-geforce-rtx-4060-ventus-2x-oc"
        source = CompetitorSource(
            name="Shopify Direct URL Source",
            base_url="http://example.test/suggest.json",
            scrape_config_json=json.dumps(
                {
                    "mode": "shopify_suggest_json",
                    "search_url_template": "http://example.test/suggest.json?q={query}",
                    "query_override_map": {"GPU-TEST-4060": "msi rtx 4060 ventus"},
                    "required_terms_map": {"GPU-TEST-4060": ["msi", "rtx", "4060", "ventus"]},
                    "product_url_map": {"GPU-TEST-4060": direct_url},
                    "product_page_item_selector": "body",
                    "product_page_name_selector": "h1",
                    "product_page_price_selector": ".price",
                    "currency": "PHP",
                }
            ),
            enabled=True,
        )
        db.add(source)
        db.commit()

        seen_urls: list[str] = []

        def fake_fetcher(_source: CompetitorSource, config: dict) -> str:
            request_url = str(config.get("_request_url", ""))
            seen_urls.append(request_url)
            if request_url == direct_url:
                return """
                <html>
                  <body>
                    <h1>MSI GeForce RTX 4060 Ventus 2X 8G OC</h1>
                    <div class="price">Ã¢â€šÂ±19,990.00</div>
                  </body>
                </html>
                """
            return json.dumps({"resources": {"results": {"products": []}}})

        inserted = run_scraper_cycle(db=db, fetcher=fake_fetcher)
        assert inserted == 1
        assert any(url == direct_url for url in seen_urls)

        snapshot = db.scalars(select(CompetitorPriceSnapshot)).first()
        assert snapshot is not None
        assert snapshot.product_id == gpu.id
        assert str(snapshot.competitor_price) == "19990.00"

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_scraper_pipeline_shopify_falls_back_to_suggest_when_direct_url_errors() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        supplier = Supplier(name="Shopify Direct Error Supplier", lead_time_days_default=4)
        db.add(supplier)
        db.flush()

        gpu = Product(
            sku="GPU-TEST-4060",
            name="MSI GeForce RTX 4060 Ventus 2X 8G OC",
            supplier_id=supplier.id,
            cost_price=18000.0,
            sell_price=20000.0,
            reorder_min_qty=1,
            reorder_multiple=1,
            safety_stock=1,
            active=True,
        )
        db.add(gpu)
        db.flush()

        direct_url = "https://example.test/products/msi-geforce-rtx-4060-ventus-2x-oc"
        source = CompetitorSource(
            name="Shopify Direct Error Source",
            base_url="http://example.test/suggest.json",
            scrape_config_json=json.dumps(
                {
                    "mode": "shopify_suggest_json",
                    "search_url_template": "http://example.test/suggest.json?q={query}",
                    "query_override_map": {"GPU-TEST-4060": "msi rtx 4060 ventus"},
                    "required_terms_map": {"GPU-TEST-4060": ["msi", "rtx", "4060", "ventus"]},
                    "product_url_map": {"GPU-TEST-4060": direct_url},
                    "product_page_item_selector": "body",
                    "product_page_name_selector": "h1",
                    "product_page_price_selector": ".price",
                    "currency": "PHP",
                }
            ),
            enabled=True,
        )
        db.add(source)
        db.commit()

        def fake_fetcher(_source: CompetitorSource, config: dict) -> str:
            request_url = str(config.get("_request_url", ""))
            if request_url == direct_url:
                raise RuntimeError("404 Not Found")
            return json.dumps(
                {
                    "resources": {
                        "results": {
                            "products": [
                                {
                                    "title": "MSI GeForce RTX 4060 Ventus 2X 8G OC",
                                    "price": "19990.00",
                                    "available": True,
                                    "handle": "msi-rtx-4060-ventus-2x",
                                }
                            ]
                        }
                    }
                }
            )

        inserted = run_scraper_cycle(db=db, fetcher=fake_fetcher)
        assert inserted == 1

        snapshot = db.scalars(select(CompetitorPriceSnapshot)).first()
        assert snapshot is not None
        assert snapshot.product_id == gpu.id
        assert str(snapshot.competitor_price) == "19990.00"

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_scraper_pipeline_auto_discovers_product_url_for_future_runs() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        supplier = Supplier(name="Auto Discover Supplier", lead_time_days_default=4)
        db.add(supplier)
        db.flush()

        gpu = Product(
            sku="GPU-AUTO-4060",
            name="MSI GeForce RTX 4060 Ventus 2X 8G OC",
            supplier_id=supplier.id,
            cost_price=18000.0,
            sell_price=20000.0,
            reorder_min_qty=1,
            reorder_multiple=1,
            safety_stock=1,
            active=True,
        )
        db.add(gpu)
        db.flush()

        source = CompetitorSource(
            name="Auto Discover Source",
            base_url="http://example.test/search",
            scrape_config_json=json.dumps(
                {
                    "mode": "per_product_search",
                    "search_url_template": "http://example.test/search?q={query}",
                    "query_override_map": {"GPU-AUTO-4060": "msi rtx 4060 ventus"},
                    "required_terms_map": {"GPU-AUTO-4060": ["rtx", "4060", "ventus"]},
                    "item_selector": ".item",
                    "name_selector": ".name a",
                    "price_selector": ".price",
                    "link_selector": ".name a",
                    "enable_auto_product_url_discovery": True,
                    "discovery_url_pattern": "/products/",
                    "discovery_min_name_match_score": 0.75,
                    "discovery_min_fuzzy_ratio": 0.5,
                    "currency": "PHP",
                }
            ),
            enabled=True,
        )
        db.add(source)
        db.commit()

        discovered_url = "http://example.test/products/msi-geforce-rtx-4060-ventus-2x-oc"

        def fake_fetcher(_source: CompetitorSource, _config: dict) -> str:
            return f"""
            <div class="item">
              <span class="name"><a href="/products/msi-geforce-rtx-4060-ventus-2x-oc">MSI GeForce RTX 4060 Ventus 2X 8G OC</a></span>
              <span class="price">â‚±19,990.00</span>
            </div>
            <div class="item">
              <span class="name"><a href="/products/unrelated-rtx-4070">Unrelated RTX 4070</a></span>
              <span class="price">â‚±24,990.00</span>
            </div>
            """

        inserted = run_scraper_cycle(db=db, fetcher=fake_fetcher)
        assert inserted == 1

        refreshed = db.get(CompetitorSource, source.id)
        assert refreshed is not None
        refreshed_config = json.loads(refreshed.scrape_config_json or "{}")
        product_url_map = refreshed_config.get("product_url_map", {})
        assert product_url_map.get("GPU-AUTO-4060") == discovered_url

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_default_fetcher_uses_configured_render_options(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_playwright_fetch(
        url: str,
        timeout_ms: int,
        wait_until: str,
        retries: int,
        retry_delay_ms: int,
        extra_wait_ms: int,
        user_agent: str | None,
    ) -> str:
        captured["url"] = url
        captured["timeout_ms"] = timeout_ms
        captured["wait_until"] = wait_until
        captured["retries"] = retries
        captured["retry_delay_ms"] = retry_delay_ms
        captured["extra_wait_ms"] = extra_wait_ms
        captured["user_agent"] = user_agent
        return "<html></html>"

    monkeypatch.setattr("app.jobs.run_scraper_cycle.fetch_html_with_playwright", fake_playwright_fetch)

    source = CompetitorSource(name="Test Source", base_url="https://example.test/search", enabled=True)
    config = {
        "render_js": True,
        "_request_url": "https://example.test/search?q=cpu",
        "render_timeout_ms": 61000,
        "render_wait_until": "domcontentloaded",
        "render_retries": 2,
        "render_retry_delay_ms": 1400,
        "render_extra_wait_ms": 900,
        "user_agent": "agent-test",
    }
    html = _default_fetcher(source, config)
    assert html == "<html></html>"
    assert captured["url"] == "https://example.test/search?q=cpu"
    assert captured["timeout_ms"] == 61000
    assert captured["wait_until"] == "domcontentloaded"
    assert captured["retries"] == 2
    assert captured["retry_delay_ms"] == 1400
    assert captured["extra_wait_ms"] == 900
    assert captured["user_agent"] == "agent-test"


def test_default_fetcher_falls_back_to_requests_on_playwright_runtime_error(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_playwright_fetch(*_args, **_kwargs):
        raise RuntimeError("Playwright failed")

    def fake_requests_fetch(
        url: str,
        timeout_seconds: int,
        retries: int,
        retry_delay_seconds: float,
        user_agent: str | None,
    ) -> str:
        captured["url"] = url
        captured["timeout_seconds"] = timeout_seconds
        captured["retries"] = retries
        captured["retry_delay_seconds"] = retry_delay_seconds
        captured["user_agent"] = user_agent
        return "<html>fallback</html>"

    monkeypatch.setattr("app.jobs.run_scraper_cycle.fetch_html_with_playwright", fake_playwright_fetch)
    monkeypatch.setattr("app.jobs.run_scraper_cycle.fetch_html", fake_requests_fetch)

    source = CompetitorSource(name="Test Source", base_url="https://example.test/search", enabled=True)
    config = {
        "render_js": True,
        "_request_url": "https://example.test/search?q=gpu",
        "request_timeout_seconds": 27,
        "request_retries": 3,
        "request_retry_delay_seconds": 1.4,
        "user_agent": "fallback-agent",
    }
    html = _default_fetcher(source, config)
    assert html == "<html>fallback</html>"
    assert captured["url"] == "https://example.test/search?q=gpu"
    assert captured["timeout_seconds"] == 27
    assert captured["retries"] == 3
    assert captured["retry_delay_seconds"] == 1.4
    assert captured["user_agent"] == "fallback-agent"


def test_scraper_per_product_uses_fuzzy_scoring_for_alias_names() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        supplier = Supplier(name="Fuzzy Supplier", lead_time_days_default=4)
        db.add(supplier)
        db.flush()

        gpu = Product(
            sku="GPU-ALIAS-4060",
            name="MSI GeForce RTX 4060 Ventus 2X 8G OC",
            supplier_id=supplier.id,
            cost_price=18000.0,
            sell_price=20500.0,
            reorder_min_qty=1,
            reorder_multiple=1,
            safety_stock=1,
            active=True,
        )
        db.add(gpu)
        db.flush()

        source = CompetitorSource(
            name="Fuzzy Source",
            base_url="http://example.test/search",
            scrape_config_json=json.dumps(
                {
                    "mode": "per_product_search",
                    "search_url_template": "http://example.test/search?q={query}",
                        "required_terms_map": {
                            "GPU-ALIAS-4060": ["rtx", "4060", "ventus"],
                        },
                        "min_name_match_score": 0.35,
                        "min_fuzzy_ratio": 0.35,
                    "item_selector": ".item",
                    "name_selector": ".name",
                    "price_selector": ".price",
                    "currency": "PHP",
                }
            ),
            enabled=True,
        )
        db.add(source)
        db.commit()

        def fake_fetcher(_source: CompetitorSource, _config: dict) -> str:
            return """
            <div class="item">
              <span class="name">MSI RTX4060 Ventus 2X 8GB OC Graphics Card</span>
              <span class="price">₱19,990.00</span>
            </div>
            <div class="item">
              <span class="name">MSI RTX 4070 Ventus 2X 12GB</span>
              <span class="price">₱22,990.00</span>
            </div>
            """

        inserted = run_scraper_cycle(db=db, fetcher=fake_fetcher)
        assert inserted == 1

        snapshot = db.scalars(select(CompetitorPriceSnapshot)).first()
        assert snapshot is not None
        assert snapshot.product_id == gpu.id
        assert str(snapshot.competitor_price) == "19990.00"
        payload = json.loads(snapshot.raw_payload_json or "{}")
        assert float(payload.get("match_score", 0)) >= 0.35

    Base.metadata.drop_all(bind=engine)
    engine.dispose()
