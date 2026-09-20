from fastapi.testclient import TestClient

from app.main import _parse_cors_allow_origins, app, create_app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_parse_cors_allow_origins_normalizes_common_env_values() -> None:
    assert _parse_cors_allow_origins(
        " https://stock-sage.example/, 'http://localhost:5173/' ,https://stock-sage.example"
    ) == ["https://stock-sage.example", "http://localhost:5173"]


def test_cors_preflight_allows_origin_when_env_has_trailing_slash(monkeypatch) -> None:
    origin = "https://stock-sage.example"
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", f"{origin}/")
    app_with_cors = create_app()

    with TestClient(app_with_cors) as test_client:
        response = test_client.options(
            "/auth/me",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_unhandled_backend_errors_keep_cors_headers(monkeypatch) -> None:
    origin = "https://stock-sage.example"
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", origin)
    app_with_cors = create_app()

    @app_with_cors.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    with TestClient(app_with_cors) as test_client:
        response = test_client.get("/boom", headers={"Origin": origin})

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == origin
    assert response.json()["detail"] == "Backend request failed. Check Render logs for unhandled_backend_error."


def test_forecast_report_backend_error_returns_cors_json(monkeypatch) -> None:
    from app.services.dashboard_service import DashboardService

    origin = "https://stock-sage.example"
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", origin)

    def fail_forecast_report(self, **kwargs) -> None:  # noqa: ANN001, ARG001
        raise RuntimeError("forecast failed")

    monkeypatch.setattr(DashboardService, "get_forecast_report", fail_forecast_report)
    app_with_cors = create_app()

    with TestClient(app_with_cors) as test_client:
        response = test_client.get(
            "/dashboard/forecast-report?include_details=true&evaluation_days=7",
            headers={"Origin": origin},
        )

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == origin
    assert response.json()["detail"] == (
        "Forecast report failed on the backend. Check Render logs for forecast_report_failed."
    )



def test_unsafe_browser_write_rejects_untrusted_origin(monkeypatch) -> None:
    allowed_origin = "https://stock-sage.example"
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", allowed_origin)
    app_with_cors = create_app()

    @app_with_cors.post("/write-probe")
    def write_probe() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app_with_cors) as test_client:
        rejected = test_client.post(
            "/write-probe",
            headers={"Origin": "https://untrusted.example"},
        )
        allowed = test_client.post(
            "/write-probe",
            headers={"Origin": allowed_origin},
        )

    assert rejected.status_code == 403
    assert rejected.json() == {"detail": "Origin is not allowed."}
    assert allowed.status_code == 200
    assert allowed.json() == {"ok": True}
    assert allowed.headers["access-control-allow-origin"] == allowed_origin
