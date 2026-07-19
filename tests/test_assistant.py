import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ensure no API key leaks in from the test environment, so these tests
# always exercise the deterministic keyword/template fallback path.
os.environ.pop("ANTHROPIC_API_KEY", None)  # noqa: E402

from core.assistant import StadiumAssistant  # noqa: E402


def make_assistant():
    return StadiumAssistant()


def test_navigate_intent_detected_from_free_text():
    a = make_assistant()
    intent = a.understand("Take me to Section 215 please", "gate_a")
    assert intent["intent"] == "navigate"
    assert intent["destination_node"] == "section_215"


def test_amenity_intent_detected_for_restroom_synonyms():
    a = make_assistant()
    for phrase in ["Where's the nearest bathroom?", "I need a toilet", "nearest washroom"]:
        intent = a.understand(phrase, "gate_a")
        assert intent["intent"] == "find_amenity"
        assert intent["amenity_type"] == "restroom"


def test_accessible_keyword_sets_accessible_required_flag():
    a = make_assistant()
    intent = a.understand("I need a wheelchair accessible restroom", "gate_a")
    assert intent["accessible_required"] is True


def test_general_question_when_no_destination_or_amenity_recognised():
    a = make_assistant()
    intent = a.understand("What time does the match start?", "gate_a")
    assert intent["intent"] == "general_question"


def test_handle_message_returns_route_for_navigate_intent():
    a = make_assistant()
    result = a.handle_message("Take me to Section 215", "gate_a")
    assert result["route"]["found"] is True
    assert result["route"]["path"][0] == "gate_a"
    assert "reply" in result and len(result["reply"]) > 0


def test_handle_message_handles_unroutable_request_gracefully():
    a = make_assistant()
    result = a.handle_message("Take me to the moon", "gate_a")
    # Falls through to a general_question / no-route response, never crashes.
    assert "reply" in result
    assert isinstance(result["reply"], str)


def test_handle_message_never_crashes_on_empty_or_odd_input():
    a = make_assistant()
    for msg in ["", "   ", "??? !!! 123", "asdkjaslkdjalksjdlaksjd"]:
        result = a.handle_message(msg or "hello", "gate_a")
        assert "reply" in result


def test_assistant_works_end_to_end_without_api_key_configured():
    from core import llm_client
    assert llm_client.is_configured() is False
    a = make_assistant()
    result = a.handle_message("nearest accessible restroom", "gate_b")
    assert result["route"]["found"] is True
