from fastapi.testclient import TestClient

from throughball_ai.main import app


def test_health_reports_runtime_without_secrets(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("SERVICE_NAME", "throughball-ai")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("GEMINI_FLASH_MODEL", "gemini-2.0-flash-001")

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "throughball-ai",
        "environment": "local",
        "model_default": "gemini-2.0-flash-001",
        "vertex_ai_configured": True,
    }
    assert "GOOGLE_API_KEY" not in response.text
