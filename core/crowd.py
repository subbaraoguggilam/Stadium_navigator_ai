"""
crowd.py
Reads a mock "live" crowd-density feed (1 = empty ... 5 = very crowded).

ASSUMPTION: In production this file would be replaced by a real feed from
turnstile counters / CCTV analytics / Wi-Fi occupancy sensors, polled on an
interval. The interface (get_level / as_weight_multiplier) is deliberately the
only thing the rest of the app depends on, so swapping the data source later
requires no changes to router.py or assistant.py.
"""
import json
import os
import time
from typing import Dict

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CROWD_PATH = os.path.join(_BASE_DIR, "data", "crowd_data.json")

# Multipliers per crowd level (1–5). Level 0 is unused; index aligns with level.
# Level 1 (very quiet) → 0.85x  (slightly preferred over neutral)
# Level 2 (quiet)      → 1.07x  (near-neutral)
# Level 3 (moderate)   → 1.30x  (mild penalty)
# Level 4 (busy)       → 1.55x  (noticeable penalty)
# Level 5 (very busy)  → 1.80x  (strong avoidance)
_LEVEL_MULTIPLIERS = [1.00, 0.85, 1.07, 1.30, 1.55, 1.80]

_LEVEL_LABELS = ["", "very quiet", "quiet", "moderate", "busy", "very busy"]

# Crowd data is considered stale after this many seconds (for production feeds)
_STALE_AFTER_SECONDS = 300  # 5 minutes


class CrowdFeed:
    """
    Provides crowd density levels per venue node and helpers that the router
    uses to weight edges and generate human-readable crowd annotations.

    Parameters
    ----------
    path : str
        Absolute path to crowd_data.json.
    """

    def __init__(self, path: str = _CROWD_PATH) -> None:
        with open(path, "r", encoding="utf-8") as f:
            self._levels: Dict[str, int] = json.load(f)
        self._loaded_at: float = time.time()

    # ---------------------------------------------------------------------- #
    # Core interface
    # ---------------------------------------------------------------------- #

    def get_level(self, node_id: str) -> int:
        """
        Return the crowd level for a node on a 1–5 scale.

        1 = very quiet, 5 = very crowded. Unknown nodes default to 2 (quiet),
        which represents a conservative, near-neutral estimate.

        Parameters
        ----------
        node_id : str
            The venue node identifier.

        Returns
        -------
        int
            Crowd level in the range [1, 5].
        """
        level = self._levels.get(node_id, 2)
        # Clamp to valid range in case the data file contains out-of-range values
        return max(1, min(5, level))

    def as_weight_multiplier(self, node_id: str) -> float:
        """
        Convert a crowd level into a Dijkstra edge-weight multiplier.

        Applied to the base distance of each edge so the router naturally
        prefers quieter paths. Level 1 → 0.85x (favoured), level 5 → 1.80x
        (strongly discouraged).

        Parameters
        ----------
        node_id : str
            The venue node identifier.

        Returns
        -------
        float
            Multiplier in the range [0.85, 1.80].
        """
        level = self.get_level(node_id)
        return _LEVEL_MULTIPLIERS[level]

    def get_all(self) -> Dict[str, int]:
        """Return a copy of the full crowd map, used for map rendering."""
        return dict(self._levels)

    def label_for(self, node_id: str) -> str:
        """
        Return a human-readable crowd description for a node.

        Parameters
        ----------
        node_id : str
            The venue node identifier.

        Returns
        -------
        str
            One of: 'very quiet', 'quiet', 'moderate', 'busy', 'very busy'.
        """
        level = self.get_level(node_id)
        return _LEVEL_LABELS[level]

    # ---------------------------------------------------------------------- #
    # Freshness tracking (for production feed integration)
    # ---------------------------------------------------------------------- #

    def is_stale(self) -> bool:
        """
        Return True if the crowd data has not been refreshed within the
        staleness window (_STALE_AFTER_SECONDS).  In a production deployment
        this would trigger a reload from the live feed.
        """
        return (time.time() - self._loaded_at) > _STALE_AFTER_SECONDS

    def age_seconds(self) -> float:
        """Return the age of the current crowd snapshot in seconds."""
        return time.time() - self._loaded_at

    def simulate_refresh(self, new_levels: Dict[str, int]) -> None:
        """
        Update the in-memory crowd levels (e.g. from a pushed feed update).

        Parameters
        ----------
        new_levels : Dict[str, int]
            Mapping of node_id → crowd level (1–5). Merged into the existing
            snapshot; nodes not mentioned retain their previous level.
        """
        self._levels.update(new_levels)
        self._loaded_at = time.time()
