from fastapi.testclient import TestClient

from app.main import _parse_cors_allow_origins, app, create_app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_parse_cors_allow_origins_normalizes_common_env_values() -> None:
    assert _parse_cors_allow_origins(
        " https://stock-sage-blue.vercel.app/, 'http://localhost:5173/' ,https://stock-sage-blue.vercel.app"
    ) == ["https://stock-sage-blue.vercel.app", "http://localhost:5173"]


def test_cors_preflight_allows_origin_when_env_has_trailing_slash(monkeypatch) -> None:
    origin = "https://stock-sage-blue.vercel.app"
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
