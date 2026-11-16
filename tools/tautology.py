"""Tautology tool: how far the graph is from the proof level, and what already follows. Standard library only.

The core counts the rungs (``ladder``) and walks one judgement back (``why``). This file asks the questions the
name stands for: which level does a node stand on, which edges are still below proof, and which proof edges
follow from the stated ones whatever the data.

Dependency goes one way: tools/ import the core, the core never imports tools/.
Every function is callable by name from Python, and from Node through vendor/py_launch.cjs (--call).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ontautology as ot  # noqa: E402

__all__ = ["standing", "gaps", "entailed"]


def standing(edges, node):
    """The level a node stands on: the weakest basis among everything it rests on, however deep.

    ``level`` is None when nothing is stated for the node to rest on — a given, which is not a proof.
    ``tautology`` is true only when every edge underneath is at the proof level.
    """
    edges = list(edges)
    rows = ot.why(edges, node, depth=len(edges) + 1, limit=len(edges) + 1)["rows"]
    level = min((row["weakest"] for row in rows), key=ot.BASIS.index, default=None)
    return {"node": node, "level": level, "edges": len(rows), "tautology": level == "proof"}


def gaps(edges):
    """What is left before the graph is at the tautology level: the edges below proof, weakest first."""
    edges = list(edges)
    below = [edge for edge in edges if ot._basis(edge) != "proof"]
    below.sort(key=lambda edge: (ot.BASIS.index(ot._basis(edge)), edge["kind"], edge["source"], edge["target"]))
    return {"edges": len(edges), "proof": len(edges) - len(below), "gaps": below}


def entailed(edges, kinds):
    """Proof edges that follow by transitivity and are not stated at the proof level yet.

    ``kinds`` are the edge kinds the caller declares transitive (an implication between rules, "must come
    before"). From a → b and b → c, both proof, a → c holds for every case too; ``via`` keeps the chain.
    Edges below proof entail nothing here, and an edge stated only below proof is returned so it can be raised.
    """
    found = []
    for kind in dict.fromkeys(kinds):
        proven = [edge for edge in edges if edge["kind"] == kind and ot._basis(edge) == "proof"]
        stated = {(edge["source"], edge["target"]) for edge in proven}
        for source in sorted({edge["source"] for edge in proven}):
            for row in ot.reach(proven, [source], limit=len(proven) + 1)["rows"]:
                if (source, row["node"]) not in stated:
                    found.append({"kind": kind, "source": source, "target": row["node"], "basis": "proof", "via": row["via"]})
    return found
