"""
app.py
Flask entry point for the Stadium Navigator AI assistant.

Endpoints:
  GET  /             -> chat UI
  GET  /api/venue    -> venue graph (for rendering the map)
  GET  /api/route    -> direct route query (no chat needed)
  POST /api/chat     -> {message, current_location} -> assistant reply + route
  GET  /api/health   -> health check (also reports GenAI and crowd-feed status)
"""
import logging
import os
import time
import uuid
from collections import defaultdict, deque

from dotenv import load_dotenv
from flask import Flask, jsonify, request, render_template, Response

from core.assistant import StadiumAssistant
from core import llm_client

# Load .env file for local development. In production the platform supplies
# real environment variables; load_dotenv() is a no-op when the keys are
# already set, so this is safe to call unconditionally.
load_dotenv()

# Configure structured logging so production log aggregators can parse it.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
assistant = StadiumAssistant()

MAX_MESSAGE_LENGTH = 500          # characters — single chat message cap
MAX_CONTENT_LENGTH = 16 * 1024   # 16 KB request body — chat never needs more
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# ---------------------------------------------------------------------------
# Rate limiting — sliding-window, per-process in-memory
# ---------------------------------------------------------------------------
# Caps abuse/cost blowup on the LLM-backed /api/chat endpoint.
# LIMITATION: state is per-process, so it resets across serverless cold starts
# and isn't shared across concurrent instances. A production deployment should
# back this with Redis / Upstash for a durable, cross-instance limit.
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 20
_request_log: defaultdict = defaultdict(deque)


def _client_ip() -> str:
    """Extract the real client IP, honouring X-Forwarded-For for proxied deployments."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else (request.remote_addr or "unknown")


def _rate_limited(key: str) -> bool:
    """
    Return True if *key* (client IP) has exceeded the rate limit.

    Implements a sliding-window counter: timestamps older than
    RATE_LIMIT_WINDOW_SECONDS are evicted before checking the count.
    """
    now = time.time()
    window = _request_log[key]
    while window and now - window[0] > RATE_LIMIT_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= RATE_LIMIT_MAX_REQUESTS:
        return True
    window.append(now)
    return False


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------

@app.after_request
def apply_security_headers(response: Response) -> Response:
    """
    Attach defence-in-depth HTTP security headers to every response.

    These headers are cheap to set and meaningfully reduce the attack surface
    for common web vulnerabilities (clickjacking, MIME sniffing, data leakage,
    XSS via injected scripts).
    """
    # Prevent MIME-type sniffing attacks
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Deny embedding in iframes (clickjacking protection)
    response.headers["X-Frame-Options"] = "DENY"
    # Don't send Referer header to other origins
    response.headers["Referrer-Policy"] = "no-referrer"
    # Enforce HTTPS for one year including subdomains
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # CSP: allow Google Fonts CDN (style + font files), same-origin scripts/connect
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    # Disable features not used by this app
    response.headers["Permissions-Policy"] = (
        "geolocation=(), microphone=(), camera=(), payment=()"
    )
    # Add a unique request ID to every response for traceability in logs
    response.headers["X-Request-ID"] = request.environ.get(
        "HTTP_X_REQUEST_ID", str(uuid.uuid4())
    )
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index() -> str:
    """Serve the single-page wayfinding UI."""
    return render_template("index.html", venue_name=assistant.venue.name)


@app.route("/api/venue")
def venue() -> Response:
    """
    Return the full venue graph (nodes + edges + crowd levels) as JSON.

    Used by the front-end SVG map renderer. The venue layout is stable within
    a match day so we allow the browser to cache this response for 60 seconds.
    """
    graph_warnings = assistant.venue.validate_graph()
    response = jsonify(
        {
            "venue_name": assistant.venue.name,
            "nodes": assistant.venue.nodes,
            "edges": assistant.venue.edges,
            "crowd": assistant.crowd.get_all(),
            "crowd_age_seconds": round(assistant.crowd.age_seconds(), 1),
            "crowd_is_stale": assistant.crowd.is_stale(),
            "graph_warnings": graph_warnings,
        }
    )
    response.headers["Cache-Control"] = "public, max-age=60"
    return response


@app.route("/api/health")
def health() -> Response:
    """
    Health check endpoint.

    Returns the service status, GenAI configuration, and crowd-feed freshness.
    Used by monitoring systems and deployment readiness probes.
    """
    return jsonify(
        {
            "status": "ok",
            "genai_configured": llm_client.is_configured(),
            "crowd_is_stale": assistant.crowd.is_stale(),
            "crowd_age_seconds": round(assistant.crowd.age_seconds(), 1),
            "router_cache": assistant.router.cache_info(),
        }
    )


@app.route("/api/route")
def direct_route() -> Response:
    """
    Direct route query endpoint — no NLU step, no LLM call.

    Query parameters
    ----------------
    from : str   (required) — origin node id
    to   : str   (required) — destination node id
    accessible : str        — 'true' to require accessible path
    avoid_crowds : str      — 'false' to use raw shortest path

    Returns the same route structure as /api/chat but without a chat reply.
    Useful for programmatic integrations and testing.
    """
    origin = (request.args.get("from") or "").strip()
    destination = (request.args.get("to") or "").strip()
    require_accessible = request.args.get("accessible", "false").lower() == "true"
    avoid_crowds = request.args.get("avoid_crowds", "true").lower() != "false"

    if not origin or not destination:
        return jsonify({"error": "Both 'from' and 'to' query parameters are required."}), 400
    if origin not in assistant.venue.nodes:
        return jsonify({"error": f"Unknown location: '{origin}'"}), 400
    if destination not in assistant.venue.nodes:
        return jsonify({"error": f"Unknown location: '{destination}'"}), 400

    result = assistant.router.find_route(
        origin,
        destination,
        require_accessible=require_accessible,
        avoid_crowds=avoid_crowds,
    )

    return jsonify(
        {
            "found": result.found,
            "from": origin,
            "from_label": assistant.venue.node_label(origin),
            "to": destination,
            "to_label": assistant.venue.node_label(destination),
            "path": result.path,
            "path_labels": [assistant.venue.node_label(n) for n in result.path],
            "steps": result.steps,
            "warnings": result.warnings,
            "distance_meters": result.total_distance,
            "estimated_minutes": result.estimated_minutes,
        }
    )


@app.route("/api/chat", methods=["POST"])
def chat() -> Response:
    """
    Main conversational endpoint — accepts a fan message and returns a reply.

    Request body (JSON)
    -------------------
    message          : str  (required) — fan's text input
    current_location : str             — node_id of fan's current position

    Returns
    -------
    JSON with keys: reply, intent, route
    """
    if _rate_limited(_client_ip()):
        logger.warning("Rate limit hit for IP: %s", _client_ip())
        return jsonify(
            {"error": "Too many requests. Please slow down and try again shortly."}
        ), 429

    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    current_location = (payload.get("current_location") or "gate_a").strip()

    # Sanitize: strip non-printable / control characters
    message = "".join(c for c in message if c.isprintable())

    if not message:
        return jsonify({"error": "message is required"}), 400
    if len(message) > MAX_MESSAGE_LENGTH:
        return jsonify({"error": f"message too long (max {MAX_MESSAGE_LENGTH} chars)"}), 400
    if current_location not in assistant.venue.nodes:
        return jsonify({"error": "unknown current_location"}), 400

    result = assistant.handle_message(message, current_location)
    return jsonify(result)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(400)
def bad_request(_e) -> tuple:
    return jsonify({"error": "bad request"}), 400


@app.errorhandler(404)
def not_found(_e) -> tuple:
    return jsonify({"error": "endpoint not found"}), 404


@app.errorhandler(405)
def method_not_allowed(_e) -> tuple:
    return jsonify({"error": "method not allowed"}), 405


@app.errorhandler(413)
def payload_too_large(_e) -> tuple:
    return jsonify({"error": "request body too large"}), 413


@app.errorhandler(429)
def too_many_requests(_e) -> tuple:
    return jsonify({"error": "too many requests"}), 429


@app.errorhandler(500)
def internal_server_error(_e) -> tuple:
    logger.exception("Unhandled internal server error")
    return jsonify({"error": "internal server error"}), 500


# ---------------------------------------------------------------------------
# Development server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    logger.info("Starting Stadium Navigator AI on port %d (debug=%s)", port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug)
