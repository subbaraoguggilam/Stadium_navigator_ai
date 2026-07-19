"""
test_app.py
Integration tests for the Flask application endpoints.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("ANTHROPIC_API_KEY", None)

import importlib  # noqa: E402
import app as app_module  # noqa: E402


@pytest.fixture
def client():
    """Fresh Flask test client with a clean rate-limit log per test."""
    importlib.reload(app_module)
    app_module._request_log.clear()
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

def test_index_page_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Stadium Navigator" in resp.data


def test_index_contains_meta_description(client):
    resp = client.get("/")
    assert b"meta" in resp.data and b"description" in resp.data


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

def test_health_endpoint_returns_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert "genai_configured" in body


def test_health_includes_crowd_freshness(client):
    resp = client.get("/api/health")
    body = resp.get_json()
    assert "crowd_is_stale" in body
    assert "crowd_age_seconds" in body


def test_health_includes_router_cache(client):
    resp = client.get("/api/health")
    body = resp.get_json()
    assert "router_cache" in body


# ---------------------------------------------------------------------------
# GET /api/venue
# ---------------------------------------------------------------------------

def test_venue_endpoint_returns_nodes_and_edges(client):
    resp = client.get("/api/venue")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "nodes" in body
    assert "edges" in body
    assert "crowd" in body
    assert len(body["nodes"]) > 0
    assert len(body["edges"]) > 0


def test_venue_endpoint_has_cache_header(client):
    resp = client.get("/api/venue")
    assert "max-age" in resp.headers.get("Cache-Control", "")


def test_venue_includes_crowd_freshness(client):
    resp = client.get("/api/venue")
    body = resp.get_json()
    assert "crowd_age_seconds" in body
    assert "crowd_is_stale" in body


# ---------------------------------------------------------------------------
# GET /api/route
# ---------------------------------------------------------------------------

def test_direct_route_endpoint_works(client):
    resp = client.get("/api/route?from=gate_a&to=section_215")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["found"] is True
    assert body["from"] == "gate_a"
    assert body["to"] == "section_215"
    assert body["distance_meters"] > 0
    assert body["estimated_minutes"] > 0


def test_direct_route_missing_params_returns_400(client):
    resp = client.get("/api/route?from=gate_a")
    assert resp.status_code == 400


def test_direct_route_unknown_node_returns_400(client):
    resp = client.get("/api/route?from=gate_a&to=not_a_node")
    assert resp.status_code == 400


def test_direct_route_with_accessible_flag(client):
    resp = client.get("/api/route?from=gate_a&to=section_215&accessible=true")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["found"] is True


# ---------------------------------------------------------------------------
# POST /api/chat
# ---------------------------------------------------------------------------

def test_chat_happy_path_returns_route(client):
    resp = client.post(
        "/api/chat",
        json={"message": "Take me to Section 215", "current_location": "gate_a"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["route"]["found"] is True
    assert "estimated_minutes" in body["route"]


def test_chat_requires_message(client):
    resp = client.post("/api/chat", json={"current_location": "gate_a"})
    assert resp.status_code == 400


def test_chat_rejects_empty_message(client):
    resp = client.post("/api/chat", json={"message": "   ", "current_location": "gate_a"})
    assert resp.status_code == 400


def test_chat_rejects_unknown_location(client):
    resp = client.post(
        "/api/chat", json={"message": "hi", "current_location": "not_a_node"}
    )
    assert resp.status_code == 400


def test_chat_rejects_oversized_message(client):
    huge = "a" * (app_module.MAX_MESSAGE_LENGTH + 1)
    resp = client.post("/api/chat", json={"message": huge, "current_location": "gate_a"})
    assert resp.status_code == 400


def test_chat_rate_limit_blocks_after_threshold(client):
    limit = app_module.RATE_LIMIT_MAX_REQUESTS
    last_status = None
    for _ in range(limit + 1):
        last_status = client.post(
            "/api/chat",
            json={"message": "hi", "current_location": "gate_a"},
        ).status_code
    assert last_status == 429


def test_oversized_request_body_rejected(client):
    huge_payload = {"message": "a" * 20000, "current_location": "gate_a"}
    resp = client.post("/api/chat", json=huge_payload)
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# Security headers — present on every response
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("endpoint", ["/", "/api/health", "/api/venue"])
def test_security_headers_on_every_response(client, endpoint):
    resp = client.get(endpoint)
    headers = resp.headers
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in headers
    assert "Strict-Transport-Security" in headers
    assert "Permissions-Policy" in headers
    assert "X-Request-ID" in headers


def test_csp_allows_google_fonts(client):
    """CSP must include Google Fonts domains to allow font loading."""
    resp = client.get("/api/health")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "fonts.googleapis.com" in csp
    assert "fonts.gstatic.com" in csp


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

def test_404_returns_json(client):
    resp = client.get("/api/nonexistent_endpoint_xyz")
    assert resp.status_code == 404
    body = resp.get_json()
    assert "error" in body


def test_405_returns_json(client):
    resp = client.post("/api/venue")  # venue only allows GET
    assert resp.status_code == 405
    body = resp.get_json()
    assert "error" in body
