"""
assistant.py
Orchestrates the fan-facing navigation assistant.

Pipeline (deliberately split so the app degrades gracefully without an API key,
and so navigation correctness never depends on model output):

  1. understand()  -> LLM (or keyword fallback) turns free text into a
                       structured intent: {intent, origin, destination,
                       amenity_type, accessible_required, avoid_crowds}
  2. Router         -> deterministic pathfinding over the venue graph
  3. respond()      -> LLM (or template fallback) turns the structured route
                       into a short, friendly, context-aware reply -
                       optionally in the fan's own language.
"""
import json
import re

from core.venue import Venue
from core.router import Router, RouteResult
from core.crowd import CrowdFeed
from core import llm_client

AMENITY_KEYWORDS = {
    "restroom": ["restroom", "toilet", "bathroom", "washroom"],
    "food": ["food", "eat", "hungry", "snack", "drink", "concession"],
    "medical": ["medical", "first aid", "doctor", "injury", "sick"],
    "prayer": ["prayer", "pray", "chapel", "worship"],
    "shop": ["merch", "shop", "store", "jersey", "souvenir"],
    "service": ["atm", "cash", "help desk", "guest services", "lost"],
    "transport": ["metro", "bus", "taxi", "uber", "train", "shuttle", "exit"],
}

ACCESSIBLE_KEYWORDS = ["wheelchair", "accessible", "disability", "disabled", "mobility"]


class StadiumAssistant:
    def __init__(self, venue: Venue | None = None, crowd: CrowdFeed | None = None):
        self.venue = venue or Venue()
        self.crowd = crowd or CrowdFeed()
        self.router = Router(self.venue, self.crowd)

    # ------------------------------------------------------------------ #
    # Step 1: Natural language understanding
    # ------------------------------------------------------------------ #
    def understand(self, message: str, current_location: str | None) -> dict:
        if llm_client.is_configured():
            parsed = self._understand_with_llm(message, current_location)
            if parsed:
                return parsed
        return self._understand_with_keywords(message, current_location)

    def _understand_with_llm(self, message: str, current_location: str | None) -> dict | None:
        node_catalog = "\n".join(
            f"- {nid}: {n['label']} ({n['type']})" for nid, n in self.venue.nodes.items()
        )
        system_prompt = f"""You are the intent parser for a stadium wayfinding assistant.
Venue nodes (id: label (type)):
{node_catalog}

Given a fan's message, output ONLY a compact JSON object, no prose, no markdown fences:
{{
  "intent": "navigate" | "find_amenity" | "general_question",
  "destination_node": "<node id from the catalog above, or null>",
  "amenity_type": "restroom|food|medical|prayer|shop|service|transport|null",
  "accessible_required": true|false,
  "avoid_crowds": true|false,
  "language": "<ISO 639-1 code of the language the fan wrote in>"
}}
Current fan location node id (may be null): {current_location}
"""
        raw = llm_client.complete(system_prompt, message, max_tokens=300)
        if not raw:
            return None
        try:
            cleaned = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
            data = json.loads(cleaned)
            data.setdefault("language", "en")
            return data
        except (json.JSONDecodeError, TypeError):
            return None

    def _understand_with_keywords(self, message: str, current_location: str | None) -> dict:
        text = message.lower()
        accessible_required = any(k in text for k in ACCESSIBLE_KEYWORDS)
        avoid_crowds = "fastest" not in text and "quickest" not in text  # fastest may accept crowds

        for amenity_type, keywords in AMENITY_KEYWORDS.items():
            if any(k in text for k in keywords):
                return {
                    "intent": "find_amenity",
                    "destination_node": None,
                    "amenity_type": amenity_type,
                    "accessible_required": accessible_required,
                    "avoid_crowds": avoid_crowds,
                    "language": "en",
                }

        matches = []
        for nid, node in self.venue.nodes.items():
            simple_id = nid.replace("_", " ")
            if simple_id in text or node["label"].lower().split(" (")[0] in text:
                matches = [nid]
                break

        if matches:
            return {
                "intent": "navigate",
                "destination_node": matches[0],
                "amenity_type": None,
                "accessible_required": accessible_required,
                "avoid_crowds": avoid_crowds,
                "language": "en",
            }

        return {
            "intent": "general_question",
            "destination_node": None,
            "amenity_type": None,
            "accessible_required": accessible_required,
            "avoid_crowds": avoid_crowds,
            "language": "en",
        }

    # ------------------------------------------------------------------ #
    # Step 2 + 3: Route, then produce a natural reply
    # ------------------------------------------------------------------ #
    def handle_message(self, message: str, current_location: str = "gate_a") -> dict:
        intent = self.understand(message, current_location)

        route: RouteResult | None = None
        if intent["intent"] == "navigate" and intent.get("destination_node"):
            route = self.router.find_route(
                current_location,
                intent["destination_node"],
                require_accessible=intent.get("accessible_required", False),
                avoid_crowds=intent.get("avoid_crowds", True),
            )
        elif intent["intent"] == "find_amenity" and intent.get("amenity_type"):
            route = self.router.nearest_of_type(
                current_location,
                intent["amenity_type"],
                require_accessible=intent.get("accessible_required", False),
            )

        reply = self.respond(message, intent, route)
        return {
            "reply": reply,
            "intent": intent,
            "route": {
                "found": route.found if route else False,
                "path": route.path if route else [],
                "path_labels": [self.venue.node_label(n) for n in route.path] if route else [],
                "steps": route.steps if route else [],
                "warnings": route.warnings if route else [],
                "distance_meters": route.total_distance if route else 0,
            } if route is not None or intent["intent"] in ("navigate", "find_amenity") else None,
        }

    def respond(self, original_message: str, intent: dict, route: RouteResult | None) -> str:
        if llm_client.is_configured():
            reply = self._respond_with_llm(original_message, intent, route)
            if reply:
                return reply
        return self._respond_with_template(intent, route)

    def _respond_with_llm(self, original_message: str, intent: dict, route: RouteResult | None) -> str | None:
        route_summary = "No route was requested."
        if route:
            if route.found:
                route_summary = (
                    f"Steps: {' -> '.join(route.steps)}. "
                    f"Approx distance: {route.total_distance}m. Warnings: {route.warnings or 'none'}."
                )
            else:
                route_summary = f"Could not find a route. Reason: {route.warnings}"

        system_prompt = f"""You are a friendly, concise FIFA World Cup 2026 stadium wayfinding
assistant helping a fan in real time. Reply in the language code '{intent.get("language", "en")}'.
Keep it under 60 words, warm and practical, like a helpful steward. Mention crowd
warnings if present. Do not invent locations that are not in the route data given.

Route data: {route_summary}
"""
        return llm_client.complete(system_prompt, original_message, max_tokens=220)

    def _respond_with_template(self, intent: dict, route: RouteResult | None) -> str:
        if intent["intent"] == "general_question" or route is None:
            return (
                "I can help you find gates, seats, restrooms, food, medical, prayer rooms, "
                "shops, or transport. Try: 'Take me to Section 215' or "
                "'nearest accessible restroom'."
            )
        if not route.found:
            reason = route.warnings[0] if route.warnings else "I couldn't find that location."
            return f"Sorry - {reason} Try asking for a different location or drop the accessibility filter."

        lines = [f"Here's your route ({route.total_distance}m):"]
        lines.extend(f"{i+1}. {s}" for i, s in enumerate(route.steps))
        if route.warnings:
            lines.append(" ".join(route.warnings))
        return "\n".join(lines)
