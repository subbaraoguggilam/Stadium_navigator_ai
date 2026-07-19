"""
venue.py
Loads the static venue graph (gates, concourses, sections, amenities) and
exposes convenience lookups used by the router and assistant layers.
"""
import json
import os

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENUE_PATH = os.path.join(_BASE_DIR, "data", "venue_data.json")


class Venue:
    def __init__(self, path: str = _VENUE_PATH):
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        self.name = raw["venue_name"]
        self.nodes = raw["nodes"]          # node_id -> {label, type, accessible, level}
        self.edges = raw["edges"]          # list of {from, to, distance}
        self.adjacency = self._build_adjacency()

    def _build_adjacency(self):
        adj = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            a, b, d = edge["from"], edge["to"], edge["distance"]
            adj.setdefault(a, []).append((b, d))
            adj.setdefault(b, []).append((a, d))  # undirected concourse graph
        return adj

    def node_label(self, node_id: str) -> str:
        node = self.nodes.get(node_id)
        return node["label"] if node else node_id

    def is_accessible(self, node_id: str) -> bool:
        node = self.nodes.get(node_id)
        return bool(node and node.get("accessible", False))

    def find_nodes_by_type(self, node_type: str):
        """Return node_ids matching a category, e.g. 'restroom', 'food', 'gate'."""
        return [nid for nid, n in self.nodes.items() if n.get("type") == node_type]

    def search_by_keyword(self, keyword: str):
        """Loose text match over node ids + labels, used for free-form NLU fallback."""
        keyword = keyword.lower()
        matches = []
        for nid, n in self.nodes.items():
            if keyword in nid.lower() or keyword in n["label"].lower() or keyword in n["type"].lower():
                matches.append(nid)
        return matches

    def all_node_ids(self):
        return list(self.nodes.keys())
