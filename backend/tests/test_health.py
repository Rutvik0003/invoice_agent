"""Tests for GET /api/health and the SPA fallback."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_configured_models(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "")
    client = TestClient(create_app(frontend_dist=tmp_path))

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["models_configured"] == {"gemini": True, "groq": False}
    assert "test-gemini-key" not in response.text


def test_spa_fallback_serves_index_but_not_for_api(tmp_path):
    (tmp_path / "index.html").write_text("<html>app</html>")
    client = TestClient(create_app(frontend_dist=tmp_path))

    assert client.get("/dashboard").text == "<html>app</html>"
    assert client.get("/api/does-not-exist").status_code == 404
