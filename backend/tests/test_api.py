"""API surface smoke tests. No Supabase or Gemini credentials needed."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_integration_state_without_leaking_secrets():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body["integrations"]) >= {"supabase", "gemini", "usda", "redis"}
    assert "key" not in str(body).lower().replace("usda_demo_key", "")


def test_public_met_catalog_needs_no_auth():
    resp = client.get("/api/workouts/catalog")
    assert resp.status_code == 200
    assert len(resp.json()["activities"]) > 30


def test_protected_routes_reject_anonymous_requests():
    for path in ("/api/me", "/api/dashboard", "/api/analytics", "/api/chat/sessions"):
        resp = client.get(path)
        assert resp.status_code in (401, 503), path
        assert "error" in resp.json()


def test_errors_use_the_shared_envelope():
    resp = client.get("/api/me")
    body = resp.json()
    assert set(body["error"]) == {"code", "message"}


def test_openapi_schema_builds():
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    for expected in ("/api/dashboard", "/api/ai/food-photo", "/api/chat/messages", "/api/goals/preview"):
        assert expected in paths


def test_docs_are_served():
    assert client.get("/docs").status_code == 200
