"""
venue.py
Loads the static venue graph (gates, concourses, sections, amenities) and
exposes convenience lookups used by the router and assistant layers.
"""
import json
import os
from typing import Dict, List, Optional

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENUE_PATH = os.path.join(_BASE_DIR, "data", "venue_data.json")


class VenueLoadError(Exception):
    """Raised when the venue data file cannot be loaded or is malformed."""


class Venue:
    """
    Represents the venue graph: a collection of named nodes (gates, concourses,
    sections, amenities, transport links) connected by weighted edges.

    Parameters
    ----------
    path : str
        Absolute path to the venue_data.json file.
    """

    def __init__(self, path: str = _VENUE_PATH) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            raise VenueLoadError(f"Venue data file not found: {path}")
        except json.JSONDecodeError as exc:
            raise VenueLoadError(f"Venue data file is not valid JSON: {exc}") from exc

        if "venue_name" not in raw or "nodes" not in raw or "edges" not in raw:
            raise VenueLoadError("Venue data file is missing required keys: venue_name, nodes, edges")

        self.name: str = raw["venue_name"]
        self.nodes: Dict[str, dict] = raw["nodes"]   # node_id → {label, type, accessible, level}
        self.edges: List[dict] = raw["edges"]         # list of {from, to, distance}
        self.adjacency: Dict[str, List] = self._build_adjacency()

    # ---------------------------------------------------------------------- #
    # Graph construction
    # ---------------------------------------------------------------------- #

    def _build_adjacency(self) -> Dict[str, List]:
        """Build an undirected adjacency list from the edge list."""
        adj: Dict[str, List] = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            a, b, d = edge["from"], edge["to"], edge["distance"]
            adj.setdefault(a, []).append((b, d))
            adj.setdefault(b, []).append((a, d))  # undirected concourse graph
        return adj

    def validate_graph(self) -> List[str]:
        """
        Sanity-check the graph for common data issues.

        Returns
        -------
        List[str]
            A list of warning strings (empty list means the graph is clean).
        """
        warnings: List[str] = []

        # Check for nodes referenced in edges but not defined in nodes dict
        for edge in self.edges:
            for side in ("from", "to"):
                nid = edge.get(side)
                if nid and nid not in self.nodes:
                    warnings.append(f"Edge references undefined node: '{nid}'")

        # Check for orphan nodes (no edges touching them)
        connected = set()
        for edge in self.edges:
            connected.add(edge.get("from"))
            connected.add(edge.get("to"))
        for nid in self.nodes:
            if nid not in connected:
                warnings.append(f"Node '{nid}' ({self.nodes[nid].get('label', '')}) has no edges — unreachable.")

        # Check for negative distances
        for edge in self.edges:
            if edge.get("distance", 0) <= 0:
                warnings.append(f"Edge {edge.get('from')} → {edge.get('to')} has non-positive distance.")

        return warnings

    # ---------------------------------------------------------------------- #
    # Lookup helpers
    # ---------------------------------------------------------------------- #

    def node_label(self, node_id: str) -> str:
        """Return the human-readable label for a node, or the node_id if not found."""
        node = self.nodes.get(node_id)
        return node["label"] if node else node_id

    def is_accessible(self, node_id: str) -> bool:
        """Return True if the node is marked wheelchair-accessible."""
        node = self.nodes.get(node_id)
        return bool(node and node.get("accessible", False))

    def find_nodes_by_type(self, node_type: str) -> List[str]:
        """Return node_ids matching a category, e.g. 'restroom', 'food', 'gate'."""
        return [nid for nid, n in self.nodes.items() if n.get("type") == node_type]

    def find_nodes_by_level(self, level: str) -> List[str]:
        """
        Return node_ids on a given structural level, e.g. 'ground' or 'upper'.

        Parameters
        ----------
        level : str
            The level identifier to filter on (case-sensitive, matches 'level' field).
        """
        return [nid for nid, n in self.nodes.items() if n.get("level") == level]

    def search_by_keyword(self, keyword: str) -> List[str]:
        """
        Loose text search over node ids, labels, and types.

        Used by the NLU keyword fallback to match free-form location names
        (e.g. "east concourse", "section 215") to canonical node ids.

        Parameters
        ----------
        keyword : str
            Search term (case-insensitive).

        Returns
        -------
        List[str]
            List of matching node_ids, ordered as they appear in the nodes dict.
        """
        keyword = keyword.lower()
        matches: List[str] = []
        for nid, n in self.nodes.items():
            if (
                keyword in nid.lower()
                or keyword in n.get("label", "").lower()
                or keyword in n.get("type", "").lower()
            ):
                matches.append(nid)
        return matches

    def find_node_by_id(self, node_id: str) -> Optional[dict]:
        """Return the node dict for the given id, or None."""
        return self.nodes.get(node_id)

    def all_node_ids(self) -> List[str]:
        """Return a list of all node ids in insertion order."""
        return list(self.nodes.keys())
