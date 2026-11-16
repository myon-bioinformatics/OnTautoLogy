"""Knowledge-graph tool: graph-shape answers under the names the parent's fleet code uses. Standard library only.

The walks themselves live in the core (ontautology.py); nothing is implemented twice here. This file keeps
the names and return shapes of myon-bioinformatics/myon-bioinformatics fleet_records.relation_cycles and the
static-order pattern of vendor_fleet_plan.build_graph, so the parent can call these instead of its own copies.

Dependency goes one way: tools/ import the core, the core never imports tools/.
Every function is callable by name from Python, and from Node through vendor/py_launch.cjs (--call).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ontautology as ot  # noqa: E402

__all__ = ["relation_cycles", "topological_order"]


def relation_cycles(edges, *, limit=5):
    """Representative cycles among relations (reported; nothing stops on them — evidence graphs need not be DAGs).

    ``edges`` is an iterable of mappings with ``source`` and ``target``. The verdict is only
    about those edges. Isolated nodes and acyclic side-branches are omitted from the result.
    """
    return ot.cycles(list(edges), limit=limit)


def topological_order(edges):
    """Order nodes so each edge's source comes before its target.

    On success ``cycle`` is None and ``order`` lists every node that appears as a source or target; on a
    cycle, ``order`` is empty and ``cycle`` is the node list (first node repeated at the end). Ask the core
    ``order`` instead when the acyclic remainder should still be ordered.
    """
    found = ot.order([{"kind": edge.get("kind", ""), "source": edge["source"], "target": edge["target"]} for edge in edges])
    if found["cycle"]:
        return {"order": [], "cycle": found["cycle"]}
    return {"order": [node for batch in found["batches"] for node in batch], "cycle": None}
