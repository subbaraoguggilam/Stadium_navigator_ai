import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.venue import Venue  # noqa: E402
from core.crowd import CrowdFeed  # noqa: E402
from core.router import Router  # noqa: E402


def make_router():
    return Router(Venue(), CrowdFeed())


def test_route_found_between_gate_and_section():
    router = make_router()
    result = router.find_route("gate_a", "section_215")
    assert result.found
    assert result.path[0] == "gate_a"
    assert result.path[-1] == "section_215"
    assert result.total_distance > 0


def test_route_same_start_and_goal():
    router = make_router()
    result = router.find_route("gate_a", "gate_a")
    assert result.found
    assert result.path == ["gate_a"]
    assert result.total_distance == 0


def test_unknown_node_returns_not_found():
    router = make_router()
    result = router.find_route("gate_a", "not_a_real_node")
    assert not result.found
    assert result.warnings


def test_accessible_requirement_excludes_non_accessible_destination():
    router = make_router()
    venue = router.venue
    non_accessible = [n for n, d in venue.nodes.items() if not d.get("accessible", True)]
    assert non_accessible, "fixture should contain at least one non-accessible node"
    result = router.find_route("gate_a", non_accessible[0], require_accessible=True)
    assert not result.found


def test_accessible_requirement_never_routes_through_inaccessible_nodes():
    router = make_router()
    venue = router.venue
    result = router.find_route("gate_a", "section_215", require_accessible=True)
    assert result.found
    for node in result.path:
        assert venue.is_accessible(node), f"{node} should be accessible-filtered out"


def test_nearest_of_type_returns_closest_amenity():
    router = make_router()
    result = router.nearest_of_type("gate_b", "restroom")
    assert result is not None
    assert result.found
    assert router.venue.nodes[result.path[-1]]["type"] == "restroom"


def test_nearest_of_type_unknown_category_returns_none():
    router = make_router()
    result = router.nearest_of_type("gate_a", "not_a_category")
    assert result is None


def test_crowded_path_costs_more_than_quiet_path_would():
    router = make_router()
    result_avoiding = router.find_route("gate_a", "section_215", avoid_crowds=True)
    result_ignoring = router.find_route("gate_a", "section_215", avoid_crowds=False)
    assert result_avoiding.found and result_ignoring.found
    # Same graph distances, but crowd-aware weighting must never produce a
    # *shorter* reported distance than the raw distances would.
    assert result_avoiding.total_distance >= result_ignoring.total_distance * 0.99
