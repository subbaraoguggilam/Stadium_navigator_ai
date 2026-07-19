"""
crowd.py
Reads a mock "live" crowd-density feed (1 = empty ... 5 = very crowded).

ASSUMPTION: In production this file would be replaced by a real feed from
turnstile counters / CCTV analytics / Wi-Fi occupancy sensors, polled on an
interval. The interface (get_level / as_weight) is deliberately the only
thing the rest of the app depends on, so swapping the data source later
requires no changes to router.py or assistant.py.
"""
import json
import os

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CROWD_PATH = os.path.join(_BASE_DIR, "data", "crowd_data.json")


class CrowdFeed:
    def __init__(self, path: str = _CROWD_PATH):
        with open(path, "r", encoding="utf-8") as f:
            self._levels = json.load(f)

    def get_level(self, node_id: str) -> int:
        """1 (quiet) .. 5 (very crowded). Unknown nodes default to 2 (mild)."""
        return self._levels.get(node_id, 2)

    def as_weight_multiplier(self, node_id: str) -> float:
        """
        Converts a crowd level into a multiplier applied to travel distance,
        so the router naturally prefers quieter paths without needing a
        separate optimisation objective. Level 1 -> 0.9x (slightly favoured),
        level 5 -> 1.8x (strongly discouraged).
        """
        level = self.get_level(node_id)
        return 0.7 + (level * 0.22)

    def get_all(self) -> dict:
        """Returns a copy of the full crowd map, used for map rendering."""
        return dict(self._levels)

    def label_for(self, node_id: str) -> str:
        level = self.get_level(node_id)
        return ["", "very quiet", "quiet", "moderate", "busy", "very busy"][level]
