"""
router.py
Deterministic, testable routing logic. This is intentionally kept separate
from any LLM call: navigation correctness must never depend on a model's
non-determinism. The GenAI layer (assistant.py) only turns the *output*
of this module into natural, conversational language.
"""
import heapq
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional

from core.venue import Venue
from core.crowd import CrowdFeed

# Average comfortable walking speed in a crowded stadium concourse (m/s).
# Used for walk-time estimates. Slightly slower than free-walk (~1.4 m/s)
# to account for doors, stairs, and general stadium congestion.
_WALK_SPEED_MPS = 1.2


@dataclass
class RouteResult:
    """
    Encapsulates the outcome of a single routing query.

    Attributes
    ----------
    found : bool
        True if a valid path was found.
    path : List[str]
        Ordered list of node_ids from start to goal.
    total_distance : float
        Sum of raw edge distances along the chosen path (metres).
    estimated_minutes : float
        Approximate walk time in minutes, accounting for crowd density.
    steps : List[str]
        Human-readable turn-by-turn directions.
    warnings : List[str]
        Any crowd or accessibility warnings the user should know.
    """

    found: bool
    path: List[str] = field(default_factory=list)
    total_distance: float = 0.0
    estimated_minutes: float = 0.0
    steps: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class Router:
    """
    Crowd-aware, accessibility-respecting pathfinder over the venue graph.

    Route queries are cached (functools.lru_cache) because on match day the
    same handful of "gate → my section" and "gate → nearest restroom" queries
    repeat constantly across thousands of fans. Caching turns those into O(1)
    lookups after the first computation instead of re-running Dijkstra every
    time.

    Cache invalidation: call ``router.find_route.cache_clear()`` whenever new
    occupancy data arrives (e.g. from a real-time crowd feed update).

    Each Router instance maintains its own independent cache so that separate
    instances in tests never share or pollute each other's results.
    """

    def __init__(self, venue: Venue, crowd: CrowdFeed) -> None:
        self.venue = venue
        self.crowd = crowd
        # Instance-scoped LRU cache — wraps the private method so that each
        # Router instance in tests gets its own isolated cache.
        self.find_route = lru_cache(maxsize=2048)(self._compute_route)
        self.nearest_of_type = lru_cache(maxsize=512)(self._compute_nearest_of_type)

    # ---------------------------------------------------------------------- #
    # Public API
    # ---------------------------------------------------------------------- #

    def cache_info(self) -> Dict[str, object]:
        """Return cache statistics for both cached methods (useful for diagnostics)."""
        return {
            "find_route": self.find_route.cache_info()._asdict(),
            "nearest_of_type": self.nearest_of_type.cache_info()._asdict(),
        }

    # ---------------------------------------------------------------------- #
    # Core pathfinding (Dijkstra)
    # ---------------------------------------------------------------------- #

    def _compute_route(
        self,
        start: str,
        goal: str,
        require_accessible: bool = False,
        avoid_crowds: bool = True,
        emergency: bool = False,
    ) -> RouteResult:
        """
        Find the optimal path from *start* to *goal* using Dijkstra's algorithm.

        Parameters
        ----------
        start : str
            Origin node id.
        goal : str
            Destination node id.
        require_accessible : bool
            If True, only traverse nodes and destinations marked accessible.
        avoid_crowds : bool
            If True, inflate edge weights by the crowd density multiplier so
            the router naturally prefers quieter routes.
        emergency : bool
            If True, ignore crowd weights entirely and find the raw shortest
            path (used for medical emergencies where speed overrides comfort).

        Returns
        -------
        RouteResult
            Always returned (never raises). ``found=False`` carries a
            human-readable reason in ``warnings``.
        """
        if start not in self.venue.nodes:
            return RouteResult(found=False, warnings=[f"Unknown start location: '{start}'."])
        if goal not in self.venue.nodes:
            return RouteResult(found=False, warnings=[f"Unknown destination: '{goal}'."])

        if require_accessible and not self.venue.is_accessible(goal):
            dest_label = self.venue.node_label(goal)
            return RouteResult(
                found=False,
                warnings=[
                    f"{dest_label} is not marked as an accessible destination. "
                    "Try removing the accessibility filter or ask for a nearby accessible alternative."
                ],
            )

        # Same start and goal — trivial case
        if start == goal:
            label = self.venue.node_label(start)
            return RouteResult(
                found=True,
                path=[start],
                total_distance=0.0,
                estimated_minutes=0.0,
                steps=[f"You are already at {label}."],
                warnings=[],
            )

        # Dijkstra with optional crowd-weighted edge costs
        dist: Dict[str, float] = {start: 0.0}
        raw_dist: Dict[str, float] = {start: 0.0}  # unweighted, for time estimate
        prev: Dict[str, str] = {}
        visited: set = set()
        pq = [(0.0, start)]

        while pq:
            d, node = heapq.heappop(pq)
            if node in visited:
                continue
            visited.add(node)
            if node == goal:
                break

            for neighbor, base_dist in self.venue.adjacency.get(node, []):
                if require_accessible and not self.venue.is_accessible(neighbor):
                    continue

                if emergency:
                    weight = base_dist  # raw distance — fastest possible
                elif avoid_crowds:
                    weight = base_dist * self.crowd.as_weight_multiplier(neighbor)
                else:
                    weight = base_dist

                nd = d + weight
                if neighbor not in dist or nd < dist[neighbor]:
                    dist[neighbor] = nd
                    raw_dist[neighbor] = raw_dist.get(node, 0.0) + base_dist
                    prev[neighbor] = node
                    heapq.heappush(pq, (nd, neighbor))

        if goal not in prev:
            return RouteResult(
                found=False,
                warnings=["No route found between these two points. "
                           "The locations may not be connected in the current venue map."],
            )

        # Reconstruct path by backtracking through prev
        path: List[str] = [goal]
        while path[-1] != start:
            path.append(prev[path[-1]])
        path.reverse()

        # Build crowd warnings for nodes on the chosen path
        warnings: List[str] = []
        busy_nodes = [n for n in path if self.crowd.get_level(n) >= 4]
        if busy_nodes:
            names = ", ".join(self.venue.node_label(n) for n in busy_nodes)
            verb = "are" if len(busy_nodes) > 1 else "is"
            warnings.append(f"⚠ Heads up: {names} currently {verb} busy.")

        if emergency and busy_nodes:
            warnings.insert(0, "🚨 Emergency route — ignoring crowd levels for fastest path.")

        # Walk-time estimate: use raw (unweighted) distance and walking speed.
        # Crowd level on the path adds a small time penalty (avg 10% per busy node).
        total_raw = raw_dist.get(goal, 0.0)
        crowd_penalty = 1.0 + 0.10 * len(busy_nodes)
        estimated_minutes = round((total_raw / _WALK_SPEED_MPS) * crowd_penalty / 60, 1)

        steps = self._describe_steps(path)

        return RouteResult(
            found=True,
            path=path,
            total_distance=round(dist.get(goal, 0.0), 1),
            estimated_minutes=estimated_minutes,
            steps=steps,
            warnings=warnings,
        )

    # ---------------------------------------------------------------------- #
    # Nearest-amenity helper
    # ---------------------------------------------------------------------- #

    def _compute_nearest_of_type(
        self,
        start: str,
        node_type: str,
        require_accessible: bool = False,
    ) -> Optional[RouteResult]:
        """
        Find the closest amenity of a given type from *start*.

        Runs ``find_route`` to each candidate and returns the one with the
        shortest ``total_distance``. Results are cached per ``(start,
        node_type, require_accessible)`` tuple.

        Parameters
        ----------
        start : str
            Origin node id.
        node_type : str
            Amenity category, e.g. 'restroom', 'food', 'medical'.
        require_accessible : bool
            If True, only consider accessible amenity nodes.

        Returns
        -------
        Optional[RouteResult]
            The nearest reachable amenity result, or None if none exist.
        """
        candidates = self.venue.find_nodes_by_type(node_type)
        if require_accessible:
            candidates = [c for c in candidates if self.venue.is_accessible(c)]
        if not candidates:
            return None

        best: Optional[RouteResult] = None
        for c in candidates:
            result = self.find_route(start, c, require_accessible=require_accessible)
            if result.found and (best is None or result.total_distance < best.total_distance):
                best = result
        return best

    # ---------------------------------------------------------------------- #
    # Step description builder
    # ---------------------------------------------------------------------- #

    def _describe_steps(self, path: List[str]) -> List[str]:
        """
        Convert a path of node_ids into numbered, human-readable directions.

        Parameters
        ----------
        path : List[str]
            Ordered list of node_ids from start to goal.

        Returns
        -------
        List[str]
            One string per waypoint in the path.
        """
        steps: List[str] = []
        for i, node in enumerate(path):
            label = self.venue.node_label(node)
            crowd_label = self.crowd.label_for(node)
            if i == 0:
                steps.append(f"Start at {label}.")
            elif i == len(path) - 1:
                steps.append(f"Arrive at {label} — currently {crowd_label}.")
            else:
                steps.append(f"Continue through {label} ({crowd_label}).")
        return steps
