"""Tests for GET /api/health and the SPA fallback."""

import pytesseract
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(frontend_dist=tmp_path))


@pytest.fixture(autouse=True)
def restore_tesseract_cmd():
    """pytesseract keeps the binary path in a module global; put it back after each test."""
    original = pytesseract.pytesseract.tesseract_cmd
    yield
    pytesseract.pytesseract.tesseract_cmd = original


def test_health_reports_configured_models(monkeypatch, client):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "")

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["models_configured"] == {"gemini": True, "groq": False}
    assert "test-gemini-key" not in response.text


def test_health_reports_ocr_available(monkeypatch, client):
    monkeypatch.setattr(pytesseract, "get_tesseract_version", lambda: "5.5.0")

    body = client.get("/api/health").json()

    assert body["ocr"] == {"available": True, "version": "5.5.0"}


def test_health_reports_ocr_unavailable_without_crashing(monkeypatch, client):
    def missing():
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "get_tesseract_version", missing)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ocr"] == {"available": False, "version": None}


def test_health_respects_tesseract_cmd(monkeypatch, client):
    monkeypatch.setenv("TESSERACT_CMD", "/no/such/tesseract")

    body = client.get("/api/health").json()

    assert pytesseract.pytesseract.tesseract_cmd == "/no/such/tesseract"
    assert body["ocr"] == {"available": False, "version": None}


def test_spa_fallback_serves_index_but_not_for_api(tmp_path):
    (tmp_path / "index.html").write_text("<html>app</html>")
    client = TestClient(create_app(frontend_dist=tmp_path))

    assert client.get("/dashboard").text == "<html>app</html>"
    assert client.get("/api/does-not-exist").status_code == 404
