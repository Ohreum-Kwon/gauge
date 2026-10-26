import pytest
from fastapi.testclient import TestClient

from app.config import DEV_JWT_SECRET, Settings, get_settings
from app.main import create_app


def test_production_refuses_the_development_secret():
    with pytest.raises(ValueError, match="GAUGE_JWT_SECRET"):
        Settings(environment="production", jwt_secret=DEV_JWT_SECRET)
    Settings(environment="production", jwt_secret="a-real-secret-from-the-host-0123456789")


@pytest.fixture
def app_with_frontend(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("outside dist")
    monkeypatch.setenv("GAUGE_FRONTEND_DIST", str(tmp_path))
    get_settings.cache_clear()
    yield TestClient(create_app())
    get_settings.cache_clear()


def test_serves_the_frontend_with_client_side_routes(app_with_frontend):
    client = app_with_frontend
    assert client.get("/assets/app.js").text == "console.log(1)"
    # Paths the client-side router owns get index.html.
    for path in ("/", "/projects/3/quality", "/audit"):
        response = client.get(path)
        assert response.status_code == 200
        assert "id=root" in response.text
    # The API keeps its own 404s, and paths can't escape the dist folder.
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/nope").status_code == 404
    for sneaky in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt"):
        assert "outside dist" not in client.get(sneaky).text
