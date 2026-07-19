"""
test_venue.py
Unit tests for core/venue.py — Venue graph loader and lookup utilities.
"""
import os
import sys
import json
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.venue import Venue, VenueLoadError  # noqa: E402


@pytest.fixture
def venue():
    return Venue()


# ---------------------------------------------------------------------------
# Initialisation & error handling
# ---------------------------------------------------------------------------

def test_venue_loads_without_errors(venue):
    """Venue object is created successfully with real data file."""
    assert venue.name
    assert len(venue.nodes) > 0
    assert len(venue.edges) > 0


def test_venue_raises_on_missing_file():
    """VenueLoadError is raised when the data file doesn't exist."""
    with pytest.raises(VenueLoadError, match="not found"):
        Venue(path="/nonexistent/path/venue_data.json")


def test_venue_raises_on_invalid_json(tmp_path):
    """VenueLoadError is raised when the data file contains invalid JSON."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not json at all {{")
    with pytest.raises(VenueLoadError, match="not valid JSON"):
        Venue(path=str(bad_file))


def test_venue_raises_on_missing_keys(tmp_path):
    """VenueLoadError is raised when required keys are absent from the JSON."""
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text('{"venue_name": "Test"}')
    with pytest.raises(VenueLoadError, match="missing required keys"):
        Venue(path=str(incomplete))


# ---------------------------------------------------------------------------
# Node lookups
# ---------------------------------------------------------------------------

def test_node_label_returns_correct_label(venue):
    assert "Gate A" in venue.node_label("gate_a")


def test_node_label_falls_back_to_id_for_unknown_node(venue):
    assert venue.node_label("nonexistent_node") == "nonexistent_node"


def test_is_accessible_true_for_accessible_node(venue):
    assert venue.is_accessible("gate_a") is True


def test_is_accessible_false_for_inaccessible_node(venue):
    assert venue.is_accessible("gate_d") is False


def test_is_accessible_false_for_unknown_node(venue):
    assert venue.is_accessible("totally_unknown") is False


# ---------------------------------------------------------------------------
# Type and level queries
# ---------------------------------------------------------------------------

def test_find_nodes_by_type_returns_all_gates(venue):
    gates = venue.find_nodes_by_type("gate")
    assert len(gates) == 4
    assert "gate_a" in gates


def test_find_nodes_by_type_returns_all_restrooms(venue):
    restrooms = venue.find_nodes_by_type("restroom")
    assert len(restrooms) >= 2
    assert all(venue.nodes[n]["type"] == "restroom" for n in restrooms)


def test_find_nodes_by_type_unknown_category_returns_empty(venue):
    assert venue.find_nodes_by_type("spaceship") == []


def test_find_nodes_by_level_returns_ground_level(venue):
    ground = venue.find_nodes_by_level("ground")
    assert len(ground) > 0
    assert all(venue.nodes[n].get("level") == "ground" for n in ground)


def test_find_nodes_by_level_returns_upper_level(venue):
    upper = venue.find_nodes_by_level("upper")
    assert len(upper) > 0
    assert "section_215" in upper


def test_all_node_ids_returns_all_nodes(venue):
    ids = venue.all_node_ids()
    assert len(ids) == len(venue.nodes)


# ---------------------------------------------------------------------------
# Keyword search
# ---------------------------------------------------------------------------

def test_search_by_keyword_matches_gate(venue):
    results = venue.search_by_keyword("gate")
    assert len(results) > 0
    assert all("gate" in r for r in results)


def test_search_by_keyword_case_insensitive(venue):
    upper = venue.search_by_keyword("GATE")
    lower = venue.search_by_keyword("gate")
    assert set(upper) == set(lower)


def test_search_by_keyword_matches_partial_label(venue):
    results = venue.search_by_keyword("215")
    assert "section_215" in results


def test_search_by_keyword_no_match_returns_empty(venue):
    results = venue.search_by_keyword("zzzyyyxxx_nosuchlabel")
    assert results == []


# ---------------------------------------------------------------------------
# Graph validation
# ---------------------------------------------------------------------------

def test_validate_graph_real_data_has_no_warnings(venue):
    """The bundled venue_data.json should pass validation cleanly."""
    warnings = venue.validate_graph()
    assert warnings == [], f"Unexpected graph warnings: {warnings}"


def test_validate_graph_detects_orphan_node(tmp_path):
    """validate_graph() flags nodes with no edges."""
    data = {
        "venue_name": "Test",
        "nodes": {
            "a": {"label": "A", "type": "gate", "accessible": True, "level": "ground"},
            "b": {"label": "B", "type": "gate", "accessible": True, "level": "ground"},
            "orphan": {"label": "Orphan", "type": "gate", "accessible": True, "level": "ground"},
        },
        "edges": [
            {"from": "a", "to": "b", "distance": 10}
        ],
    }
    f = tmp_path / "v.json"
    f.write_text(json.dumps(data))
    v = Venue(path=str(f))
    warnings = v.validate_graph()
    assert any("orphan" in w for w in warnings), f"Expected orphan warning, got: {warnings}"


def test_validate_graph_detects_undefined_node_in_edge(tmp_path):
    """validate_graph() flags edges referencing nodes not in the nodes dict."""
    data = {
        "venue_name": "Test",
        "nodes": {
            "a": {"label": "A", "type": "gate", "accessible": True, "level": "ground"},
        },
        "edges": [
            {"from": "a", "to": "ghost_node", "distance": 20}
        ],
    }
    f = tmp_path / "v.json"
    f.write_text(json.dumps(data))
    v = Venue(path=str(f))
    warnings = v.validate_graph()
    assert any("ghost_node" in w for w in warnings), f"Expected undefined node warning, got: {warnings}"
