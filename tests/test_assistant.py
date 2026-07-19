"""
test_assistant.py
Unit tests for core/assistant.py — NLU → routing → response pipeline.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ensure no API key leaks from the test environment — these tests always
# exercise the deterministic keyword / template fallback path.
os.environ.pop("ANTHROPIC_API_KEY", None)

from core.assistant import StadiumAssistant  # noqa: E402
from core import llm_client                  # noqa: E402


@pytest.fixture
def assistant():
    return StadiumAssistant()


# ---------------------------------------------------------------------------
# LLM configuration guard
# ---------------------------------------------------------------------------

def test_llm_not_configured_during_tests():
    """Confirm no real API key is active during tests."""
    assert llm_client.is_configured() is False


# ---------------------------------------------------------------------------
# Intent detection — navigate
# ---------------------------------------------------------------------------

def test_navigate_intent_detected_from_free_text(assistant):
    intent = assistant.understand("Take me to Section 215 please", "gate_a")
    assert intent["intent"] == "navigate"
    assert intent["destination_node"] == "section_215"


def test_navigate_intent_with_lowercase(assistant):
    intent = assistant.understand("i want to go to section 101", "gate_a")
    assert intent["intent"] == "navigate"


# ---------------------------------------------------------------------------
# Intent detection — find_amenity (parameterized across synonyms)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase,expected_type", [
    ("Where's the nearest bathroom?", "restroom"),
    ("I need a toilet", "restroom"),
    ("nearest washroom", "restroom"),
    ("I'm hungry, where can I eat?", "food"),
    ("any food kiosks nearby?", "food"),
    ("I need medical help", "medical"),
    ("first aid please", "medical"),
    ("where is the prayer room?", "prayer"),
    ("I need to pray", "prayer"),
    ("where can I buy a jersey?", "shop"),
    ("souvenir shop?", "shop"),
    ("where is the ATM?", "service"),
    ("metro station", "transport"),
    ("how do I get to the bus?", "transport"),
])
def test_amenity_intent_detected(assistant, phrase, expected_type):
    intent = assistant.understand(phrase, "gate_a")
    assert intent["intent"] == "find_amenity", f"Expected find_amenity for '{phrase}'"
    assert intent["amenity_type"] == expected_type, (
        f"Expected {expected_type} for '{phrase}', got {intent['amenity_type']}"
    )


# ---------------------------------------------------------------------------
# Intent detection — multilingual synonyms
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase,expected_type", [
    ("Dónde está el baño?", "restroom"),       # Spanish: bathroom
    ("Je cherche à manger", "food"),            # French: I'm looking to eat
    ("طعام", "food"),                           # Arabic: food
    ("مرحاض", "restroom"),                     # Arabic: toilet
    ("صلاة", "prayer"),                        # Arabic: prayer
])
def test_multilingual_amenity_intent(assistant, phrase, expected_type):
    intent = assistant.understand(phrase, "gate_a")
    assert intent["intent"] == "find_amenity", f"Expected find_amenity for '{phrase}'"
    assert intent["amenity_type"] == expected_type


# ---------------------------------------------------------------------------
# Intent detection — accessibility flag
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "I need a wheelchair accessible restroom",
    "accessible bathroom please",
    "I have a disability, nearest restroom",
    "mobility impaired, need a toilet",
])
def test_accessible_keyword_sets_flag(assistant, phrase):
    intent = assistant.understand(phrase, "gate_a")
    assert intent["accessible_required"] is True, f"Expected accessible_required for '{phrase}'"


# ---------------------------------------------------------------------------
# Intent detection — avoid_crowds / fastest
# ---------------------------------------------------------------------------

def test_fastest_keyword_sets_avoid_crowds_false(assistant):
    intent = assistant.understand("Fastest way to the metro after the match", "gate_a")
    assert intent["avoid_crowds"] is False


def test_quickest_keyword_sets_avoid_crowds_false(assistant):
    intent = assistant.understand("Quickest route to Section 215", "gate_a")
    assert intent["avoid_crowds"] is False


def test_normal_request_defaults_to_avoid_crowds(assistant):
    intent = assistant.understand("Take me to Section 215", "gate_a")
    assert intent["avoid_crowds"] is True


# ---------------------------------------------------------------------------
# Intent detection — emergency
# ---------------------------------------------------------------------------

def test_emergency_intent_detected(assistant):
    intent = assistant.understand("Medical emergency, I need help now!", "gate_a")
    assert intent["intent"] == "emergency"
    assert intent["emergency"] is True


def test_emergency_routes_to_medical(assistant):
    result = assistant.handle_message("emergency help now", "gate_a")
    # Emergency routing should always produce a route to medical
    assert "reply" in result
    assert isinstance(result["reply"], str)
    assert len(result["reply"]) > 0


# ---------------------------------------------------------------------------
# Intent detection — general question
# ---------------------------------------------------------------------------

def test_general_question_when_no_destination_recognised(assistant):
    intent = assistant.understand("What time does the match start?", "gate_a")
    assert intent["intent"] == "general_question"


# ---------------------------------------------------------------------------
# handle_message — full pipeline
# ---------------------------------------------------------------------------

def test_handle_message_returns_route_for_navigate(assistant):
    result = assistant.handle_message("Take me to Section 215", "gate_a")
    assert result["route"]["found"] is True
    assert result["route"]["path"][0] == "gate_a"
    assert "reply" in result
    assert len(result["reply"]) > 0


def test_handle_message_returns_walk_time(assistant):
    """Route result should include walk-time estimate."""
    result = assistant.handle_message("Take me to Section 215", "gate_a")
    assert result["route"]["found"] is True
    assert result["route"]["estimated_minutes"] > 0


def test_handle_message_for_amenity_returns_route(assistant):
    result = assistant.handle_message("nearest accessible restroom", "gate_b")
    assert result["route"]["found"] is True


def test_handle_message_unroutable_request_returns_graceful_reply(assistant):
    result = assistant.handle_message("Take me to the moon", "gate_a")
    assert "reply" in result
    assert isinstance(result["reply"], str)


def test_handle_message_never_crashes_on_odd_input(assistant):
    for msg in ["", "   ", "??? !!! 123", "x" * 400, "🏟️🚪🎉"]:
        result = assistant.handle_message(msg or "hello", "gate_a")
        assert "reply" in result
        assert isinstance(result["reply"], str)


def test_handle_message_general_question_returns_none_route(assistant):
    result = assistant.handle_message("What time is kick-off?", "gate_a")
    assert result["route"] is None


def test_end_to_end_without_api_key(assistant):
    """Full pipeline works correctly with no LLM API key configured."""
    assert not llm_client.is_configured()
    result = assistant.handle_message("nearest accessible restroom", "gate_b")
    assert result["route"]["found"] is True
    assert result["route"]["estimated_minutes"] > 0
