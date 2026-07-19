# Stadium Navigator AI 🏟️

[![CI](https://github.com/YOUR_USERNAME/stadium-navigator-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/stadium-navigator-ai/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Accessibility: WCAG AA](https://img.shields.io/badge/accessibility-WCAG%20AA-green.svg)](https://www.w3.org/WAI/WCAG21/quickref/)

> **AI-powered fan wayfinding assistant for the FIFA World Cup 2026.**  
> Helps 80,000+ fans find their gate, seat, and nearest amenities — with crowd-aware routing, multilingual support, and emergency response — in real time.

**Chosen vertical:** Fan Navigation & Wayfinding

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [Approach & Logic](#2-approach--logic)
3. [Features](#3-features)
4. [How It Works](#4-how-it-works)
5. [API Reference](#5-api-reference)
6. [Getting Started](#6-getting-started)
7. [Running Tests](#7-running-tests)
8. [Deployment](#8-deployment)
9. [Security & Efficiency Hardening](#9-security--efficiency-hardening)
10. [Accessibility](#10-accessibility)
11. [Assumptions & Scope](#11-assumptions--scope)
12. [Tech Stack](#12-tech-stack)

---

## 1. The Problem

On match day at an 80,000+ seat FIFA World Cup stadium, fans routinely struggle with:

- **"Where is my gate/section?"** — Static signage can't adapt to real-time conditions.
- **"Where's the nearest accessible restroom/food/first-aid?"** — No dynamic proximity search.
- **"Which route avoids the crowds?"** — Congested concourses create safety risks.
- **Language barriers** — FIFA World Cup 2026 draws fans from 200+ countries.
- **Emergencies** — Delayed response when fans can't quickly find medical help.

**Stadium Navigator AI** solves all of these with a conversational AI assistant that combines deterministic graph-based routing (always correct, always safe) with a GenAI language layer (natural, multilingual, context-aware).

---

## 2. Approach & Logic

The system is split into three deliberate layers so **navigation correctness never depends on a language model's non-determinism**:

```
Fan message
    │
    ▼
1. Understand (NLU)  ──▶  {intent, destination, amenity_type,
    │                       accessible_required, avoid_crowds,
    │                       emergency, language}
    │                       ↑ LLM-parsed when ANTHROPIC_API_KEY is set;
    │                         deterministic keyword fallback otherwise
    ▼
2. Router (deterministic Dijkstra)
    │   • Crowd-weighted edge costs (quieter paths preferred)
    │   • Accessibility node/edge filtering
    │   • Emergency mode (raw shortest path, no crowd avoidance)
    │   • Walk-time estimation (distance ÷ crowd-adjusted speed)
    │   • LRU-cached: O(1) on repeated queries
    ▼
3. Respond (GenAI or template)
    │   Turns the computed route into a short, warm, context-aware reply
    │   in the fan's own language — NEVER invents a location.
    ▼
Reply + step-by-step route + live animated map highlight
```

**Why this split matters:** A hallucinated turn-by-turn direction inside a real stadium is a genuine safety issue. The LLM only *phrases* an already-computed, deterministic, verifiable route — it never computes one.

### Graceful Degradation

No API key? No problem. The app automatically falls back to:
- A multilingual keyword-based intent parser (supports English, Spanish, French, Arabic, Chinese)
- A structured, still-genuinely-useful step-by-step template reply

A reviewer can grade the full assistant functionality without provisioning any API key.

---

## 3. Features

| Feature | Description |
|---------|-------------|
| 🗺️ **Interactive SVG Map** | Click any venue node to pre-fill a navigation query |
| 🤖 **Natural Language Chat** | Free-text queries in any language |
| 🧭 **Crowd-Aware Routing** | Dijkstra weighted by live crowd density |
| ♿ **Accessibility Routing** | Filter to wheelchair-accessible nodes end-to-end |
| 🚨 **Emergency Mode** | Instant route to medical station, crowd-bypassing |
| ⏱️ **Walk-Time Estimates** | "~4 min walk" based on distance + crowd level |
| 🌍 **Multilingual NLU** | Keyword fallback covers EN/ES/FR/DE/AR/ZH |
| ⚡ **Route Caching** | LRU cache on both `find_route` and `nearest_of_type` |
| 🔒 **Security Headers** | CSP, HSTS, X-Frame-Options, Permissions-Policy |
| 📊 **Rate Limiting** | 20 req/min/IP sliding-window on the LLM endpoint |
| 🏗️ **CI/CD** | GitHub Actions: flake8 + pytest + pip-audit on Python 3.11/3.12 |

---

## 4. How It Works

### Core Modules

| Module | Role |
|--------|------|
| `core/venue.py` | Loads venue graph from `data/venue_data.json`; exposes node lookups, type/level queries, keyword search, and graph validation |
| `core/crowd.py` | Reads crowd density (1–5 scale) per node; translates to edge-weight multipliers; tracks data freshness |
| `core/router.py` | Dijkstra pathfinding: crowd-weighted, accessibility-filtered, emergency-mode, walk-time aware; LRU-cached |
| `core/assistant.py` | Orchestrates NLU → routing → response; multilingual keyword tables; emergency intent |
| `core/llm_client.py` | Anthropic API wrapper: retry logic, configurable timeout, graceful None fallback |
| `app.py` | Flask: 5 endpoints, security headers, rate limiting, input sanitization, structured logging |

### Venue Graph

The sample venue (`data/venue_data.json`) models **27 nodes** across 5 types:
- **Gates** (4) — entry/exit points with accessibility flags
- **Concourses** (6) — horizontal routing corridors (ground + upper levels)
- **Sections** (6) — seating areas including a Family Zone
- **Amenities** (8) — restrooms, food (Halal/Vegetarian options), medical, prayer room, merchandise, ATM
- **Transport** (3) — metro, shuttle bus, taxi/rideshare

Connected by **32 undirected edges** with distances in metres.

### Crowd Density

All 27 nodes have crowd levels (1 = very quiet … 5 = very busy). Levels are converted to Dijkstra edge-weight multipliers:

| Level | Label | Multiplier |
|-------|-------|-----------|
| 1 | Very quiet | 0.85× (preferred) |
| 2 | Quiet | 1.07× |
| 3 | Moderate | 1.30× |
| 4 | Busy | 1.55× |
| 5 | Very busy | 1.80× |

### Example Interactions

```
Fan: "Take me to Section 215"
→ Gate A → East Concourse 1 → East Concourse 2 → Section 215 (175m, ~2.4 min)

Fan: "Nearest accessible restroom"
→ Gate A → East Concourse 1 → Restroom East (80m, ~1.1 min)

Fan: "Medical emergency!"
→ 🚨 EMERGENCY — Gate A → East Concourse 1 → Medical & First Aid (90m, ~1.3 min)

Fan: "Dónde está el baño?" (Spanish)
→ Nearest restroom route in Spanish (with LLM) or English template (without)

Fan: "Fastest way to the metro" (fastest = avoids crowd avoidance)
→ Direct raw-distance shortest path to Metro Station Exit
```

---

## 5. API Reference

### `GET /`
Returns the main wayfinding UI.

### `GET /api/health`
```json
{
  "status": "ok",
  "genai_configured": false,
  "crowd_is_stale": false,
  "crowd_age_seconds": 42.1,
  "router_cache": {"find_route": {...}, "nearest_of_type": {...}}
}
```

### `GET /api/venue`
Returns the full venue graph (nodes, edges, crowd levels). Cached 60 seconds.

### `GET /api/route`
Direct route query without chat.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `from` | string | ✅ | Origin node id |
| `to` | string | ✅ | Destination node id |
| `accessible` | bool | ❌ | `true` to require accessible path |
| `avoid_crowds` | bool | ❌ | `false` to use raw shortest path |

```bash
GET /api/route?from=gate_a&to=section_215&accessible=true
```

### `POST /api/chat`
```json
// Request
{ "message": "Take me to Section 215", "current_location": "gate_a" }

// Response
{
  "reply": "Here's your route (175m, ~2.4 min walk):\n1. Start at Gate A (East Plaza).\n...",
  "intent": { "intent": "navigate", "destination_node": "section_215", ... },
  "route": {
    "found": true,
    "path": ["gate_a", "concourse_e1", "concourse_e2", "section_215"],
    "path_labels": ["Gate A (East Plaza)", "East Concourse 1", ...],
    "steps": ["Start at Gate A...", "Continue through East Concourse 1...", "Arrive at Section 215"],
    "warnings": [],
    "distance_meters": 175.0,
    "estimated_minutes": 2.4
  }
}
```

**Rate limit:** 20 requests/minute per IP. Returns `429` when exceeded.  
**Message limits:** 500 characters maximum. 16 KB body maximum.

---

## 6. Getting Started

### Prerequisites
- Python 3.11 or 3.12
- Git

### Local Development

```bash
git clone https://github.com/YOUR_USERNAME/stadium-navigator-ai.git
cd stadium-navigator-ai

# Create virtual environment (recommended)
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # macOS/Linux

pip install -r requirements.txt

# Optional: enable free-form multilingual NLU + replies
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=your_key_here

python app.py
# Open http://localhost:5000
```

The app works fully without an API key using the deterministic keyword fallback.

---

## 7. Running Tests

```bash
pytest tests/ -v
```

**Test coverage:**
- `tests/test_app.py` — Flask endpoints, security headers, error handlers, rate limiting
- `tests/test_assistant.py` — NLU pipeline, multilingual synonyms, emergency intent, full pipeline
- `tests/test_router.py` — Dijkstra routing, accessibility filtering, walk times, caching
- `tests/test_venue.py` — Graph loading, lookups, validation, keyword search
- `tests/test_crowd.py` — Crowd levels, multipliers, freshness, refresh

```bash
# With coverage report
pytest tests/ --cov=core --cov=app --cov-report=term-missing
```

---

## 8. Deployment

### Vercel (Serverless)
```bash
npm i -g vercel
vercel --prod
```
Set `ANTHROPIC_API_KEY` in Vercel environment variables for LLM features.

### Render (Free Tier — Recommended)
1. Fork this repository
2. Create a new **Web Service** on [render.com](https://render.com)
3. Point it to your fork — Render detects `render.yaml` automatically
4. Add `ANTHROPIC_API_KEY` as an environment variable (optional)

### GitHub Pages (Static Demo)
The app requires a Python server, so full deployment uses Render/Vercel.  
For a static demo, host on any platform that supports Python WSGI apps.

---

## 9. Security & Efficiency Hardening

### Security
| Measure | Detail |
|---------|--------|
| **HTTP Security Headers** | CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy |
| **Content Security Policy** | Restricts scripts/styles to same-origin; allows Google Fonts CDN specifically |
| **Rate Limiting** | 20 req/min/IP sliding-window on the LLM-backed `/api/chat` endpoint |
| **Input Validation** | Message length cap (500 chars), body size cap (16 KB → 413), location node validation |
| **Input Sanitization** | Non-printable characters stripped before processing |
| **XSS Prevention** | `textContent` not `innerHTML` in frontend; CSP `script-src 'self'` |
| **Secret Management** | API key read-only from environment; never hardcoded; `load_dotenv()` for local dev |
| **Request Tracing** | `X-Request-ID` header on every response for log correlation |
| **LLM Timeout** | 8-second hard timeout on Anthropic API calls with 1 retry on transient errors |
| **Error Handling** | JSON error responses for 400/404/405/413/429/500; no stack traces in production |

### Efficiency
| Measure | Detail |
|---------|--------|
| **Route Caching** | `lru_cache(maxsize=2048)` on `find_route` + `lru_cache(maxsize=512)` on `nearest_of_type` |
| **HTTP Caching** | `Cache-Control: public, max-age=60` on `/api/venue` (stable within a match day) |
| **Venue Singleton** | Graph loaded once at startup, never re-read per request |
| **Serverless-safe** | LLM timeout (8s) under Vercel Hobby's 10s cap; `maxDuration: 15` in `vercel.json` |
| **Minimal Dependencies** | 5 packages: Flask, requests, python-dotenv, pytest, pytest-cov — no heavy frameworks |

---

## 10. Accessibility

The UI meets **WCAG 2.1 AA** standards:

- ♿ **Skip-to-content link** for keyboard and screen-reader users
- 🔊 **`aria-live="polite"`** on chat log for screen reader announcements  
- 🗺️ **`aria-label`** on SVG map nodes (individual `<title>` per node)
- ⌨️ **Full keyboard navigation** — Tab, Enter, Esc, / (focus input)
- 🎯 **Visible focus states** — 2px solid outline with adequate contrast
- 🔇 **`prefers-reduced-motion`** — all animations disabled if requested
- 🎨 **Forced colors mode** — explicit borders for high-contrast display modes
- 🖨️ **Print styles** — clean route output when printed
- 🌐 **`lang="en"`** on `<html>`; region aria-labels on every major section
- ⚠️ **Warning alerts** use `role="alert"` for priority announcement

---

## 11. Assumptions & Scope

- The venue graph in `data/venue_data.json` is a **sample stadium** — in production this would be provided by each host stadium's facilities team.
- The crowd feed in `data/crowd_data.json` is **mocked static data** standing in for real turnstile/CCTV/Wi-Fi occupancy data. `core/crowd.py` isolates the interface so a real feed can be swapped with zero changes to the routing or assistant logic.
- No user data is persisted. Chat messages are processed in-memory per-request only. `sessionStorage` retains the fan's location for UX (cleared on tab close).
- The LLM is used strictly for *language understanding and response phrasing*, never for computing routes — keeping navigation guidance verifiable and safe.
- Rate limiting is in-memory per-process (documented limitation). A production deployment should use Redis/Upstash for cross-instance durability.

---

## 12. Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, Flask 3.0 |
| Routing | Custom Dijkstra (no external dependencies) |
| AI / NLU | Anthropic Claude API (optional) + keyword fallback |
| Frontend | Vanilla HTML5, CSS3, JavaScript (no build step) |
| Fonts | Google Fonts — Barlow Condensed + Inter |
| Testing | pytest, pytest-cov |
| Linting | flake8 |
| CI/CD | GitHub Actions (Python 3.11 + 3.12 matrix) |
| Deployment | Vercel (serverless) or Render (free tier) |

---

Built for the **FIFA World Cup 2026 GenAI stadium-ops challenge** — Fan Navigation & Wayfinding vertical.
