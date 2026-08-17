# Stadium Navigator AI

A GenAI-enabled fan wayfinding assistant built for the **FIFA World Cup 2026** stadium-operations
challenge.

**Chosen vertical:** Fan Navigation & Wayfinding — helping fans find gates, seats, and
amenities quickly, safely, and in their own language, while steering them around
congestion in real time.

---

## 1. The Problem

On match day, fans arriving at a 80,000+ seat stadium routinely struggle with:

- "Where is my gate / section, and what's the fastest way there from here?"
- "Where's the *nearest* accessible restroom / food stall / first-aid point?"
- Getting funneled into already-crowded concourses because static signage
  can't react to real-time conditions.
- Language barriers — FIFA World Cup 2026 draws fans from dozens of countries.

Static maps and signage solve none of these dynamically. **Stadium Navigator AI**
combines a deterministic routing engine (so directions are always correct and
testable) with a GenAI layer (so the assistant understands free-form questions
and replies naturally, in the fan's own language).

## 2. Approach & Logic

The system is deliberately split into three layers so that **navigation
correctness never depends on a language model's non-determinism**:

```
Fan message
    │
    ▼
1. Understand (NLU)  ──▶  {intent, destination, amenity_type, accessible?, language}
    │                       (LLM-parsed when an API key is configured,
    │                        otherwise a keyword-based fallback — see below)
    ▼
2. Router (deterministic)
    │   Dijkstra's algorithm over a graph of gates → concourses → sections/amenities,
    │   with edge weights inflated by live crowd density, so the engine naturally
    │   prefers quieter routes. Accessibility filtering excludes non-accessible
    │   nodes entirely when required.
    ▼
3. Respond (GenAI)
    │   Turns the structured route into a short, warm, contextual reply —
    │   in the fan's language — while never inventing a location that
    │   wasn't actually in the computed route.
    ▼
Reply + step-by-step route + live map highlight
```

**Why this split matters:** a hallucinated turn-by-turn direction inside a real
stadium is a genuine safety issue, not just an annoyance. So the LLM is only
ever allowed to *phrase* an already-computed, verifiable route — never invent
one. Every routing decision is unit-tested independent of any model call.

### Graceful degradation (no API key required to demo or grade)

`core/llm_client.py` reads `ANTHROPIC_API_KEY` from the environment only —
never hardcoded. If it's absent, or the request fails for any reason, the app
automatically falls back to:
- a keyword-based intent parser (`core/assistant.py::_understand_with_keywords`)
- a templated, still-genuinely-useful step-by-step reply
  (`core/assistant.py::_respond_with_template`)

This means the whole assistant is fully functional and testable offline, and a
reviewer never needs to provision a key just to see it work — but plugging in
a key immediately upgrades it to free-form multilingual conversation.

## 3. How It Works

- **`core/venue.py`** — loads the venue graph (`data/venue_data.json`): gates,
  concourses, sections, restrooms, food, medical, shops, and transport links,
  each tagged with an `accessible` flag.
- **`core/crowd.py`** — reads a mock live crowd-density feed
  (`data/crowd_data.json`, 1–5 scale) behind a small interface, so a real
  turnstile/Wi-Fi-occupancy feed could be swapped in later with zero changes
  to the routing or assistant code.
- **`core/router.py`** — Dijkstra's shortest path, weighted by crowd density,
  with optional accessibility filtering and a "nearest amenity of type X"
  helper.
- **`core/assistant.py`** — orchestrates NLU → routing → response generation,
  as described above.
- **`core/llm_client.py`** — thin, defensive wrapper around the Anthropic
  Messages API. Times out safely, never raises past its boundary.
- **`app.py`** — Flask app exposing `/`, `/api/venue`, `/api/chat`,
  `/api/health`. Basic input validation (message length, known-location
  checks) guards the chat endpoint.
- **`templates/` + `static/`** — a single-page UI: a live SVG stadium map
  (nodes colored by crowd level, current path highlighted) next to a chat
  panel, with quick-suggestion chips. Built with semantic HTML, `aria-live`
  regions, visible focus states, and screen-reader labels for accessibility.

## 4. Example Interactions

- *"Take me to Section 215"* → step-by-step route + live map highlight.
- *"Nearest accessible restroom"* → filters out non-accessible amenities and
  routes only through accessible nodes.
- *"Fastest way to the metro after the match"* → recognizes "fastest" as a
  signal to tolerate crowds in exchange for distance.
- *"¿Dónde puedo comer algo?"* (with an API key configured) → understood and
  answered in Spanish.

## 5. Getting Started

```bash
git clone <your-repo-url>
cd stadium-navigator-ai
pip install -r requirements.txt

# Optional — enables free-form multilingual NLU + replies.
# The app works fully without this, using the deterministic fallback.
cp .env.example .env
# then edit .env and set ANTHROPIC_API_KEY

python app.py
# open http://localhost:5000
```

Run the test suite:

```bash
pytest tests/ -v
```

## 6. Security & Efficiency Hardening

- **Rate limiting**: `/api/chat` (the only LLM-backed, cost-bearing endpoint)
  is protected by a sliding-window limiter (20 req/min/IP). Documented
  limitation: it's in-memory per-process, so a production deployment should
  back it with Redis/Upstash for a durable, cross-instance limit.
- **Security headers**: every response sets `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, `Strict-Transport-Security`, and a
  `Content-Security-Policy` restricting scripts/styles to same-origin.
- **Input hardening**: message length cap, request body size cap (413 on
  oversized payloads), and strict validation of `current_location` against
  known venue nodes — all enforced server-side, not just client-side.
- **No XSS surface**: the frontend renders assistant replies via
  `textContent`, never `innerHTML`, so a malicious or LLM-generated string
  can never inject markup.
- **Route caching**: `Router.find_route` is `lru_cache`-wrapped — the same
  "gate → my section" query repeated by thousands of fans on match day is
  computed once, not re-run through Dijkstra every time.
- **Serverless-safe timeouts**: the LLM call timeout (8s) is kept
  comfortably under common serverless function duration caps (e.g. Vercel's
  10s default, also pinned explicitly in `vercel.json`), so a slow model
  response degrades to the deterministic template fallback instead of the
  whole request timing out.
- **HTTP caching**: `/api/venue` sets `Cache-Control: public, max-age=60`
  since the venue layout doesn't change mid-match.
- **CI**: `.github/workflows/ci.yml` runs `flake8` + the full `pytest` suite
  on every push/PR.

## 7. Cross-Vertical Touches

While the primary vertical is **Fan Navigation & Wayfinding**, the same
architecture naturally extends into other challenge areas the brief called
out:

- **Crowd management**: routes are computed against a live crowd-density
  feed and can be asked to explicitly avoid busy concourses.
- **Accessibility**: every route can be constrained to fully
  wheelchair-accessible nodes end-to-end, not just at the destination.
- **Transportation**: the venue graph includes metro/rideshare/parking
  nodes, so "how do I get home" is answerable in the same conversation.
- **Multilingual assistance**: when an API key is configured, the assistant
  understands and replies in whatever language the fan writes in — no
  separate translation step required.

## 8. Assumptions & Scope

- The venue graph in `data/venue_data.json` is a **sample stadium**, not a
  real FIFA World Cup 2026 venue — in production this would be provided by
  each host stadium's facilities team.
- The crowd feed in `data/crowd_data.json` is **mocked static data** standing
  in for a real turnstile/CCTV/Wi-Fi occupancy feed. `core/crowd.py`
  isolates this so a real feed can be swapped in without touching routing
  or assistant logic.
- No user data is persisted or logged; chat messages are processed
  in-memory per-request only.
- The LLM is used strictly for *language understanding and phrasing*, never
  for computing the route itself, to keep navigation guidance verifiable
  and safe.
- Designed as a single-venue demo; multi-venue support would mean loading a
  different `venue_data.json`/`crowd_data.json` pair per stadium.

## 9. Tech Stack

Python, Flask, vanilla HTML/CSS/JS (no build step, keeps the repo small),
Anthropic Claude API (optional), pytest, flake8, GitHub Actions.

---
Built for the FIFA World Cup 2026 GenAI stadium-ops challenge — Fan Navigation & Wayfinding vertical.
