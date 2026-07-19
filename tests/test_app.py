import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("ANTHROPIC_API_KEY", None)  # noqa: E402

import importlib  # noqa: E402
import app as app_module  # noqa: E402


def make_client():
    """Fresh Flask test client with a clean rate-limit log per test."""
    importlib.reload(app_module)
    app_module._request_log.clear()
    return app_module.app.test_client()


def test_index_page_loads():
    client = make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Stadium Navigator" in resp.data


def test_health_endpoint():
    client = make_client()
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_venue_endpoint_has_cache_header():
    client = make_client()
    resp = client.get("/api/venue")
    assert resp.status_code == 200
    assert "max-age" in resp.headers.get("Cache-Control", "")


def test_security_headers_present_on_every_response():
    client = make_client()
    resp = client.get("/api/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in resp.headers
    assert "Strict-Transport-Security" in resp.headers


def test_chat_requires_message():
    client = make_client()
    resp = client.post("/api/chat", json={"current_location": "gate_a"})
    assert resp.status_code == 400


def test_chat_rejects_unknown_location():
    client = make_client()
    resp = client.post("/api/chat", json={"message": "hi", "current_location": "not_a_node"})
    assert resp.status_code == 400


def test_chat_rejects_oversized_message():
    client = make_client()
    huge = "a" * (app_module.MAX_MESSAGE_LENGTH + 1)
    resp = client.post("/api/chat", json={"message": huge, "current_location": "gate_a"})
    assert resp.status_code == 400


def test_chat_happy_path_returns_route():
    client = make_client()
    resp = client.post(
        "/api/chat", json={"message": "Take me to Section 215", "current_location": "gate_a"}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["route"]["found"] is True


def test_chat_rate_limit_blocks_after_threshold():
    client = make_client()
    limit = app_module.RATE_LIMIT_MAX_REQUESTS
    last_status = None
    for _ in range(limit + 1):
        last_status = client.post(
            "/api/chat", json={"message": "hi", "current_location": "gate_a"}
        ).status_code
    assert last_status == 429


def test_oversized_request_body_rejected():
    client = make_client()
    huge_payload = {"message": "a" * (app_module.MAX_CONTENT_LENGTH + 1000), "current_location": "gate_a"}
    resp = client.post("/api/chat", json=huge_payload)
    assert resp.status_code == 413
