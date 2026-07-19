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
from typing import List, Optional

from core.venue import Venue
from core.crowd import CrowdFeed


@dataclass
class RouteResult:
    found: bool
    path: List[str] = field(default_factory=list)
    total_distance: float = 0.0
    steps: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class Router:
    """
    Route queries are cached (functools.lru_cache) because on match day the
    same handful of "gate -> my section" and "gate -> nearest restroom"
    queries repeat constantly across thousands of fans. Caching turns those
    into O(1) lookups after the first computation instead of re-running
    Dijkstra every time.

    Cache invalidation: crowd data is a static snapshot loaded once at
    process start (see core/crowd.py), so cached results stay valid for the
    process lifetime. In production, call `router.find_route.cache_clear()`
    whenever new occupancy data lands.
    """

    def __init__(self, venue: Venue, crowd: CrowdFeed):
        self.venue = venue
        self.crowd = crowd
        # Instance-scoped cache so separate Router instances (e.g. in tests)
        # never share or pollute each other's cached results.
        self.find_route = lru_cache(maxsize=2048)(self._compute_route)

    def _compute_route(
        self,
        start: str,
        goal: str,
        require_accessible: bool = False,
        avoid_crowds: bool = True,
    ) -> RouteResult:
        if start not in self.venue.nodes or goal not in self.venue.nodes:
            return RouteResult(found=False, warnings=["Unknown location."])

        if require_accessible and not self.venue.is_accessible(goal):
            return RouteResult(
                found=False,
                warnings=[
                    f"{self.venue.node_label(goal)} is not marked as an "
                    f"accessible destination in our records."
                ],
            )

        # Dijkstra with crowd-weighted edge cost.
        dist = {start: 0.0}
        prev = {}
        visited = set()
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

                weight = base_dist
                if avoid_crowds:
                    weight *= self.crowd.as_weight_multiplier(neighbor)

                nd = d + weight
                if neighbor not in dist or nd < dist[neighbor]:
                    dist[neighbor] = nd
                    prev[neighbor] = node
                    heapq.heappush(pq, (nd, neighbor))

        if goal not in prev and goal != start:
            return RouteResult(found=False, warnings=["No route found between these points."])

        # Reconstruct path
        path = [goal]
        while path[-1] != start:
            path.append(prev[path[-1]])
        path.reverse()

        warnings = []
        busy_nodes = [n for n in path if self.crowd.get_level(n) >= 4]
        if busy_nodes:
            names = ", ".join(self.venue.node_label(n) for n in busy_nodes)
            warnings.append(f"Heads up: {names} currently {('are' if len(busy_nodes) > 1 else 'is')} busy.")

        steps = self._describe_steps(path)

        return RouteResult(
            found=True,
            path=path,
            total_distance=round(dist.get(goal, 0.0), 1),
            steps=steps,
            warnings=warnings,
        )

    def _describe_steps(self, path: List[str]) -> List[str]:
        steps = []
        for i, node in enumerate(path):
            label = self.venue.node_label(node)
            crowd_label = self.crowd.label_for(node)
            if i == 0:
                steps.append(f"Start at {label}.")
            elif i == len(path) - 1:
                steps.append(f"Arrive at {label} ({crowd_label}).")
            else:
                steps.append(f"Continue through {label} ({crowd_label}).")
        return steps

    def nearest_of_type(
        self, start: str, node_type: str, require_accessible: bool = False
    ) -> Optional[RouteResult]:
        """Find the closest amenity of a given type (e.g. 'restroom', 'food')."""
        candidates = self.venue.find_nodes_by_type(node_type)
        if require_accessible:
            candidates = [c for c in candidates if self.venue.is_accessible(c)]
        if not candidates:
            return None

        best = None
        for c in candidates:
            result = self.find_route(start, c, require_accessible=require_accessible)
            if result.found and (best is None or result.total_distance < best.total_distance):
                best = result
        return best
