"""
test_crowd.py
Unit tests for core/crowd.py — crowd density feed interface.
"""
import os
import sys
import json
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.crowd import CrowdFeed, _LEVEL_MULTIPLIERS, _LEVEL_LABELS  # noqa: E402


@pytest.fixture
def crowd():
    return CrowdFeed()


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def test_crowd_loads_without_errors(crowd):
    """CrowdFeed loads the bundled crowd_data.json without error."""
    data = crowd.get_all()
    assert isinstance(data, dict)
    assert len(data) > 0


# ---------------------------------------------------------------------------
# get_level
# ---------------------------------------------------------------------------

def test_get_level_returns_known_value(crowd):
    """Known nodes return their configured crowd level."""
    # gate_c is set to 1 in crowd_data.json
    assert crowd.get_level("gate_c") == 1


def test_get_level_defaults_to_2_for_unknown_node(crowd):
    """Unknown nodes default to level 2 (quiet)."""
    assert crowd.get_level("totally_unknown_node_xyz") == 2


def test_get_level_clamps_out_of_range_values(tmp_path):
    """Crowd levels outside [1, 5] are clamped to valid range."""
    bad = tmp_path / "bad_crowd.json"
    bad.write_text(json.dumps({"node_a": 99, "node_b": -3}))
    feed = CrowdFeed(path=str(bad))
    assert feed.get_level("node_a") == 5
    assert feed.get_level("node_b") == 1


# ---------------------------------------------------------------------------
# as_weight_multiplier
# ---------------------------------------------------------------------------

def test_weight_multiplier_is_lowest_for_level_1(crowd):
    """Level 1 (quietest) gives the lowest multiplier."""
    mult_1 = _LEVEL_MULTIPLIERS[1]
    for level in range(2, 6):
        assert mult_1 < _LEVEL_MULTIPLIERS[level], (
            f"Level 1 multiplier {mult_1} should be less than level {level} multiplier {_LEVEL_MULTIPLIERS[level]}"
        )


def test_weight_multiplier_increases_monotonically():
    """Multiplier must increase strictly from level 1 to level 5."""
    for level in range(1, 5):
        assert _LEVEL_MULTIPLIERS[level] < _LEVEL_MULTIPLIERS[level + 1], (
            f"Multiplier at level {level} ({_LEVEL_MULTIPLIERS[level]}) should be "
            f"less than level {level + 1} ({_LEVEL_MULTIPLIERS[level + 1]})"
        )


def test_weight_multiplier_range():
    """All multipliers are in (0, 2] — reasonable for pathfinding costs."""
    for level in range(1, 6):
        m = _LEVEL_MULTIPLIERS[level]
        assert 0 < m <= 2.0, f"Multiplier {m} at level {level} is out of expected range"


def test_as_weight_multiplier_for_gate_c(crowd):
    """gate_c is level 1 (very quiet) so it should have the minimum multiplier."""
    mult = crowd.as_weight_multiplier("gate_c")
    assert mult == _LEVEL_MULTIPLIERS[1]


def test_as_weight_multiplier_for_gate_d(crowd):
    """gate_d is level 5 (very busy) so it should have the maximum multiplier."""
    mult = crowd.as_weight_multiplier("gate_d")
    assert mult == _LEVEL_MULTIPLIERS[5]


# ---------------------------------------------------------------------------
# label_for
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level,expected", [
    (1, "very quiet"),
    (2, "quiet"),
    (3, "moderate"),
    (4, "busy"),
    (5, "very busy"),
])
def test_label_for_all_levels(level, expected, tmp_path):
    """label_for() returns the correct human-readable label for each level."""
    f = tmp_path / "crowd.json"
    f.write_text(json.dumps({"test_node": level}))
    feed = CrowdFeed(path=str(f))
    assert feed.label_for("test_node") == expected


def test_label_for_unknown_node_returns_quiet(crowd):
    """Unknown nodes default to level 2 → 'quiet'."""
    assert crowd.label_for("unknown_xyz") == "quiet"


# ---------------------------------------------------------------------------
# get_all
# ---------------------------------------------------------------------------

def test_get_all_returns_copy(crowd):
    """get_all() returns a copy — modifying it does not affect the feed."""
    original = crowd.get_all()
    original["gate_a"] = 999
    assert crowd.get_level("gate_a") != 999


def test_get_all_covers_all_nodes(crowd):
    """All 27 venue nodes should have crowd data after the data file update."""
    data = crowd.get_all()
    assert len(data) >= 27, f"Expected at least 27 crowd entries, got {len(data)}"


# ---------------------------------------------------------------------------
# Freshness tracking
# ---------------------------------------------------------------------------

def test_new_feed_is_not_stale(crowd):
    """A freshly loaded feed should not be considered stale."""
    assert crowd.is_stale() is False


def test_age_seconds_increases_over_time(crowd):
    """age_seconds() should return a positive number that grows."""
    age1 = crowd.age_seconds()
    time.sleep(0.05)
    age2 = crowd.age_seconds()
    assert age2 >= age1


# ---------------------------------------------------------------------------
# simulate_refresh
# ---------------------------------------------------------------------------

def test_simulate_refresh_updates_level(crowd):
    """simulate_refresh() updates crowd levels in-memory."""
    crowd.simulate_refresh({"gate_a": 5})
    assert crowd.get_level("gate_a") == 5


def test_simulate_refresh_resets_age(crowd):
    """simulate_refresh() resets the loaded_at timestamp."""
    time.sleep(0.05)
    age_before = crowd.age_seconds()
    crowd.simulate_refresh({"gate_a": 1})
    age_after = crowd.age_seconds()
    assert age_after < age_before
