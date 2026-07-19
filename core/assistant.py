"""
assistant.py
Orchestrates the fan-facing navigation assistant.

Pipeline (deliberately split so the app degrades gracefully without an API
key, and so navigation correctness never depends on model output):

  1. understand()  → LLM (or keyword fallback) turns free text into a
                     structured intent: {intent, origin, destination,
                     amenity_type, accessible_required, avoid_crowds,
                     emergency, language}
  2. Router        → deterministic pathfinding over the venue graph
  3. respond()     → LLM (or template fallback) turns the structured route
                     into a short, friendly, context-aware reply —
                     optionally in the fan's own language.
"""
import json
import logging
import re
from typing import Optional

from core.venue import Venue
from core.router import Router, RouteResult
from core.crowd import CrowdFeed
from core import llm_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword tables for language-agnostic intent detection
# ---------------------------------------------------------------------------

AMENITY_KEYWORDS = {
    "restroom": [
        "restroom", "toilet", "bathroom", "washroom", "lavatory",
        "wc", "aseos", "baño", "toilette", "toiletten",   # Spanish / French / German
        "مرحاض", "حمام",                                   # Arabic
        "化粒间", "洗手间",                                  # Chinese
    ],
    "food": [
        "food", "eat", "hungry", "snack", "drink", "concession", "burger",
        "pizza", "restaurant", "cafe", "kiosk", "halal", "vegetarian",
        "comida", "comer", "nourriture", "manger", "essen",  # Spanish / French / German
        "طعام", "أكل",                                        # Arabic
    ],
    "medical": [
        "medical", "first aid", "firstaid", "doctor", "nurse",
        "injury", "injured", "sick", "ill", "emergency", "hurt",
        "ambulance", "medico", "médico", "médecin", "arzt",  # Spanish / French / German
        "طبيب", "إسعاف",                                      # Arabic
    ],
    "prayer": [
        "prayer", "pray", "chapel", "worship", "mosque", "church",
        "temple", "meditation", "faith", "religious",
        "oracion", "oración", "prière", "musalá",            # Spanish / French
        "صلاة", "مسجد",                                       # Arabic
    ],
    "shop": [
        "merch", "shop", "store", "jersey", "souvenir", "merchandise",
        "fan zone", "boutique", "gear", "kit",
        "tienda", "boutique",                                 # Spanish / French
        "متجر",                                               # Arabic
    ],
    "service": [
        "atm", "cash", "help desk", "help", "lost", "found",
        "guest services", "information", "info", "customer service",
        "cajero", "dinero",                                   # Spanish
        "صراف",                                               # Arabic
    ],
    "transport": [
        "metro", "bus", "taxi", "uber", "train", "shuttle", "exit",
        "home", "leave", "going home", "after match", "after the game",
        "rideshare", "lyft", "transport",
        "tren", "autobús", "métro", "bus", "زين",             # Spanish / French / Arabic
    ],
}

ACCESSIBLE_KEYWORDS = [
    "wheelchair", "accessible", "accessibility", "disability",
    "disabled", "mobility", "mobility impaired", "crutches",
    "discapacidad", "silla de ruedas",                        # Spanish
    "handicapé", "fauteuil roulant",                          # French
    "إعاقة",                                                  # Arabic
]

EMERGENCY_KEYWORDS = [
    "emergency", "urgent", "help me", "help!", "sos",
    "medical emergency", "heart attack", "unconscious", "collapsed",
    "bleeding", "allergic reaction", "epipen",
    "emergencia", "urgencia",                                 # Spanish
    "urgence", "secours",                                     # French
    "طوارئ",                                                  # Arabic
]

# "Fastest" synonyms — user explicitly wants minimum distance (accepts crowds)
FASTEST_KEYWORDS = ["fastest", "quickest", "shortest", "direct", "closest"]


class StadiumAssistant:
    """
    High-level interface for the fan wayfinding assistant.

    Composes the NLU, routing, and response-generation layers. Every public
    method returns structured data so callers can test each stage independently.

    Parameters
    ----------
    venue : Optional[Venue]
        Venue graph. Defaults to ``Venue()`` (loads from data/venue_data.json).
    crowd : Optional[CrowdFeed]
        Crowd density feed. Defaults to ``CrowdFeed()``.
    """

    def __init__(
        self,
        venue: Optional[Venue] = None,
        crowd: Optional[CrowdFeed] = None,
    ) -> None:
        self.venue = venue or Venue()
        self.crowd = crowd or CrowdFeed()
        self.router = Router(self.venue, self.crowd)

    # ------------------------------------------------------------------ #
    # Step 1: Natural language understanding
    # ------------------------------------------------------------------ #

    def understand(self, message: str, current_location: Optional[str]) -> dict:
        """
        Parse a free-text fan message into a structured intent dict.

        Tries the LLM path first (if configured); falls back to keyword
        matching deterministically so the app always works without an API key.

        Parameters
        ----------
        message : str
            The fan's raw input text.
        current_location : Optional[str]
            The fan's current venue node id, passed as context to the LLM.

        Returns
        -------
        dict
            Keys: intent, destination_node, amenity_type, accessible_required,
            avoid_crowds, emergency, language.
        """
        if llm_client.is_configured():
            parsed = self._understand_with_llm(message, current_location)
            if parsed:
                return parsed
        return self._understand_with_keywords(message, current_location)

    def _understand_with_llm(
        self, message: str, current_location: Optional[str]
    ) -> Optional[dict]:
        """Use the Anthropic API to parse the message into a structured intent."""
        node_catalog = "\n".join(
            f"- {nid}: {n['label']} ({n['type']})"
            for nid, n in self.venue.nodes.items()
        )
        system_prompt = f"""You are the intent parser for a stadium wayfinding assistant.
Venue nodes (id: label (type)):
{node_catalog}

Given a fan's message, output ONLY a compact JSON object — no prose, no markdown fences:
{{
  "intent": "navigate" | "find_amenity" | "emergency" | "general_question",
  "destination_node": "<node id from the catalog above, or null>",
  "amenity_type": "restroom|food|medical|prayer|shop|service|transport|null",
  "accessible_required": true|false,
  "avoid_crowds": true|false,
  "emergency": true|false,
  "language": "<ISO 639-1 code of the language the fan wrote in>"
}}
Rules:
- Use "emergency" intent only for genuine medical emergencies (heart attack, collapse, etc.).
- Set avoid_crowds=false only when the fan explicitly asks for the fastest/quickest/shortest path.
- accessible_required=true only when the fan mentions wheelchair, disability, accessible, etc.
Current fan location node id (may be null): {current_location}
"""
        raw = llm_client.complete(system_prompt, message, max_tokens=300)
        if not raw:
            return None
        try:
            cleaned = re.sub(
                r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE
            ).strip()
            data = json.loads(cleaned)
            data.setdefault("language", "en")
            data.setdefault("emergency", False)
            return data
        except (json.JSONDecodeError, TypeError):
            logger.warning("LLM NLU returned unparseable JSON: %r", raw[:120])
            return None

    def _understand_with_keywords(
        self, message: str, current_location: Optional[str]
    ) -> dict:
        """
        Deterministic keyword-based intent parser — no API key required.

        This is the fallback for when no LLM is configured or the LLM call
        fails. It is also the path exercised by the full test suite.
        """
        text = message.lower()

        # Emergency detection (highest priority — short-circuit everything else)
        if any(k in text for k in EMERGENCY_KEYWORDS):
            return {
                "intent": "emergency",
                "destination_node": "amenity_medical",
                "amenity_type": "medical",
                "accessible_required": False,
                "avoid_crowds": False,   # fastest path in emergencies
                "emergency": True,
                "language": "en",
            }

        accessible_required = any(k in text for k in ACCESSIBLE_KEYWORDS)

        # avoid_crowds defaults to True (prefer quiet routes); only set to
        # False when the fan explicitly asks for the fastest/quickest path.
        avoid_crowds = not any(k in text for k in FASTEST_KEYWORDS)

        # Amenity-type matching (checks multi-word keywords first)
        for amenity_type, keywords in AMENITY_KEYWORDS.items():
            if any(k in text for k in keywords):
                return {
                    "intent": "find_amenity",
                    "destination_node": None,
                    "amenity_type": amenity_type,
                    "accessible_required": accessible_required,
                    "avoid_crowds": avoid_crowds,
                    "emergency": False,
                    "language": "en",
                }

        # Venue node matching — use venue.search_by_keyword for each word
        # to find the best matching node id in the message.
        best_match = None
        for word in text.replace(",", " ").split():
            if len(word) < 3:
                continue
            hits = self.venue.search_by_keyword(word)
            if hits:
                best_match = hits[0]
                break

        # Also try matching full node id pattern (e.g. "section 215" → "section_215")
        normalised = re.sub(r"\s+", "_", text)
        for nid in self.venue.all_node_ids():
            if nid in normalised:
                best_match = nid
                break

        if best_match:
            return {
                "intent": "navigate",
                "destination_node": best_match,
                "amenity_type": None,
                "accessible_required": accessible_required,
                "avoid_crowds": avoid_crowds,
                "emergency": False,
                "language": "en",
            }

        return {
            "intent": "general_question",
            "destination_node": None,
            "amenity_type": None,
            "accessible_required": accessible_required,
            "avoid_crowds": avoid_crowds,
            "emergency": False,
            "language": "en",
        }

    # ------------------------------------------------------------------ #
    # Step 2 + 3: Route → natural reply
    # ------------------------------------------------------------------ #

    def handle_message(
        self, message: str, current_location: str = "gate_a"
    ) -> dict:
        """
        Full pipeline: understand the message, compute a route, generate a reply.

        Parameters
        ----------
        message : str
            The fan's question or navigation request.
        current_location : str
            The node_id representing where the fan currently is.

        Returns
        -------
        dict
            ``{reply: str, intent: dict, route: dict|None}``
        """
        intent = self.understand(message, current_location)

        route: Optional[RouteResult] = None
        is_navigation_intent = intent["intent"] in ("navigate", "find_amenity", "emergency")

        if intent["intent"] == "navigate" and intent.get("destination_node"):
            route = self.router.find_route(
                current_location,
                intent["destination_node"],
                require_accessible=intent.get("accessible_required", False),
                avoid_crowds=intent.get("avoid_crowds", True),
            )
        elif intent["intent"] == "emergency":
            # Emergency: route directly to nearest medical station, bypassing crowd avoidance
            route = self.router.find_route(
                current_location,
                "amenity_medical",
                require_accessible=False,
                avoid_crowds=False,
                emergency=True,
            )
        elif intent["intent"] == "find_amenity" and intent.get("amenity_type"):
            route = self.router.nearest_of_type(
                current_location,
                intent["amenity_type"],
                require_accessible=intent.get("accessible_required", False),
            )

        reply = self.respond(message, intent, route)

        route_data: Optional[dict] = None
        if is_navigation_intent:
            route_data = {
                "found": route.found if route else False,
                "path": route.path if route else [],
                "path_labels": (
                    [self.venue.node_label(n) for n in route.path] if route else []
                ),
                "steps": route.steps if route else [],
                "warnings": route.warnings if route else [],
                "distance_meters": route.total_distance if route else 0,
                "estimated_minutes": route.estimated_minutes if route else 0,
            }

        return {
            "reply": reply,
            "intent": intent,
            "route": route_data,
        }

    def respond(
        self,
        original_message: str,
        intent: dict,
        route: Optional[RouteResult],
    ) -> str:
        """
        Generate a natural-language reply from the routing result.

        Tries the LLM first; falls back to a structured template that is still
        genuinely useful.
        """
        if llm_client.is_configured():
            reply = self._respond_with_llm(original_message, intent, route)
            if reply:
                return reply
        return self._respond_with_template(intent, route)

    def _respond_with_llm(
        self,
        original_message: str,
        intent: dict,
        route: Optional[RouteResult],
    ) -> Optional[str]:
        """Use the Anthropic API to phrase the routing result naturally."""
        route_summary = "No route was requested."
        if route:
            if route.found:
                route_summary = (
                    f"Steps: {' → '.join(route.steps)}. "
                    f"Distance: {route.total_distance}m. "
                    f"Estimated walk time: ~{route.estimated_minutes} min. "
                    f"Warnings: {route.warnings or 'none'}."
                )
            else:
                route_summary = f"Could not find a route. Reason: {route.warnings}"

        lang = intent.get("language", "en")
        is_emergency = intent.get("emergency", False)
        emergency_note = (
            " This is a MEDICAL EMERGENCY — be direct, urgent, and concise." if is_emergency else ""
        )

        system_prompt = (
            f"You are a friendly, concise FIFA World Cup 2026 stadium wayfinding assistant "
            f"helping a fan in real time. Reply in the language with ISO 639-1 code '{lang}'."
            f"{emergency_note} "
            "Keep it under 60 words, warm and practical, like a helpful steward. "
            "Mention crowd warnings if present. Mention walk time if available. "
            "Do not invent locations that are not in the route data given.\n\n"
            f"Route data: {route_summary}"
        )
        return llm_client.complete(system_prompt, original_message, max_tokens=220)

    def _respond_with_template(
        self, intent: dict, route: Optional[RouteResult]
    ) -> str:
        """Generate a structured text reply without the LLM."""
        if intent.get("emergency"):
            if route and route.found:
                lines = ["🚨 EMERGENCY — heading to Medical & First Aid Station:"]
                lines.extend(f"{i + 1}. {s}" for i, s in enumerate(route.steps))
                lines.append(
                    f"Distance: {route.total_distance}m "
                    f"(~{route.estimated_minutes} min). Staff will meet you there."
                )
                return "\n".join(lines)
            return "🚨 Go immediately to the nearest staff member or press the emergency call point."

        if intent["intent"] == "general_question" or route is None:
            return (
                "I can help you find gates, seats, restrooms, food, medical, prayer rooms, "
                "shops, or transport. Try: 'Take me to Section 215', "
                "'nearest accessible restroom', or 'fastest way to the metro'."
            )

        if not route.found:
            reason = route.warnings[0] if route.warnings else "I couldn't find that location."
            return (
                f"Sorry — {reason} "
                "Try asking for a different location or removing the accessibility filter."
            )

        time_str = f" (~{route.estimated_minutes} min walk)" if route.estimated_minutes > 0 else ""
        lines = [f"Here's your route ({route.total_distance}m{time_str}):"]
        lines.extend(f"{i + 1}. {s}" for i, s in enumerate(route.steps))
        if route.warnings:
            lines.extend(route.warnings)
        return "\n".join(lines)
