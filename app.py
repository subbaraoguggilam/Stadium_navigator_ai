"""
app.py
Flask entry point for the Stadium Navigator AI assistant.

Endpoints:
  GET  /                -> chat UI
  GET  /api/venue       -> venue graph (for rendering the map)
  POST /api/chat        -> {message, current_location} -> assistant reply + route
  GET  /api/health       -> basic health check (also reports whether GenAI is configured)
"""
import os
import time
from collections import defaultdict, deque

from flask import Flask, jsonify, request, render_template

from core.assistant import StadiumAssistant
from core import llm_client

app = Flask(__name__)
assistant = StadiumAssistant()

MAX_MESSAGE_LENGTH = 500  # basic input hardening
MAX_CONTENT_LENGTH = 16 * 1024  # 16 KB request body cap — a chat message never needs more
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# --- Simple per-process rate limiter --------------------------------------
# In-memory sliding-window limiter: caps abuse/cost blowup on the LLM-backed
# /api/chat endpoint. Deliberately dependency-free for this demo.
# LIMITATION: state is per-process, so it resets across serverless cold
# starts and isn't shared across concurrent instances. A production
# deployment should back this with Redis/Upstash (or Vercel Edge Config)
# for a durable, cross-instance limit.
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 20
_request_log = defaultdict(deque)


def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else (request.remote_addr or "unknown")


def _rate_limited(key: str) -> bool:
    now = time.time()
    window = _request_log[key]
    while window and now - window[0] > RATE_LIMIT_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= RATE_LIMIT_MAX_REQUESTS:
        return True
    window.append(now)
    return False


@app.after_request
def apply_security_headers(response):
    """Defense-in-depth headers; cheap to set, meaningfully reduce attack surface."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'"
    )
    return response


@app.route("/")
def index():
    return render_template("index.html", venue_name=assistant.venue.name)


@app.route("/api/venue")
def venue():
    response = jsonify(
        {
            "venue_name": assistant.venue.name,
            "nodes": assistant.venue.nodes,
            "edges": assistant.venue.edges,
            "crowd": assistant.crowd.get_all(),
        }
    )
    # Venue layout rarely changes within a match day; let the browser reuse
    # this response instead of re-fetching it on every chat interaction.
    response.headers["Cache-Control"] = "public, max-age=60"
    return response


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "genai_configured": llm_client.is_configured()})


@app.route("/api/chat", methods=["POST"])
def chat():
    if _rate_limited(_client_ip()):
        return jsonify({"error": "Too many requests, please slow down and try again shortly."}), 429

    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    current_location = (payload.get("current_location") or "gate_a").strip()

    if not message:
        return jsonify({"error": "message is required"}), 400
    if len(message) > MAX_MESSAGE_LENGTH:
        return jsonify({"error": f"message too long (max {MAX_MESSAGE_LENGTH} chars)"}), 400
    if current_location not in assistant.venue.nodes:
        return jsonify({"error": "unknown current_location"}), 400

    result = assistant.handle_message(message, current_location)
    return jsonify(result)


@app.errorhandler(413)
def payload_too_large(_e):
    return jsonify({"error": "request body too large"}), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
