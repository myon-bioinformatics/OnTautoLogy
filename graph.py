"""Generic directed-graph helpers. No GitHub, repository, CI or record-format concepts.

Ported from myon-bioinformatics/myon-bioinformatics fleet_records.relation_cycles
(and the graphlib static-order pattern in vendor_fleet_plan.build_graph). The parent
still has its own copies; switching the parent to import or vendor this module is a
follow-up, not part of this change.

Python 3.9+ standard library only (graphlib).
"""
import graphlib


def relation_cycles(edges, *, limit=5):
    """Representative cycles among relations (reported; nothing stops on them — evidence graphs need not be DAGs).

    ``edges`` is an iterable of mappings with ``source`` and ``target``. The verdict is only
    about those edges. Isolated nodes and acyclic side-branches are omitted from the result.
    """
    out = {}
    for e in edges:
        out.setdefault(e["source"], []).append(e["target"])
    colour, cycles = {}, []
    for start in sorted(out):
        if colour.get(start):
            continue
        stack = [(start, iter(sorted(out.get(start, ()))))]
        path, colour[start] = [start], 1
        while stack and len(cycles) < limit:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                colour[node] = 2
                stack.pop()
                path.pop()
            elif colour.get(child) == 1:
                cycles.append(path[path.index(child):] + [child])
            elif not colour.get(child):
                colour[child] = 1
                path.append(child)
                stack.append((child, iter(sorted(out.get(child, ())))))
    return cycles


def topological_order(edges):
    """Order nodes so each edge's source comes before its target (graphlib.TopologicalSorter.static_order).

    This is the pattern vendor_fleet_plan.build_graph uses for the fleet update plan: on success
    ``cycle`` is None and ``order`` lists every node that appears as a source or target; on a
    cycle, ``order`` is empty and ``cycle`` is the node list from CycleError. It does not try
    to order the acyclic remainder after a cycle is found.
    """
    predecessors = {}
    for e in edges:
        predecessors.setdefault(e["target"], set()).add(e["source"])
        predecessors.setdefault(e["source"], set())
    sorter = graphlib.TopologicalSorter(predecessors)
    try:
        return {"order": list(sorter.static_order()), "cycle": None}
    except graphlib.CycleError as exc:
        return {"order": [], "cycle": list(exc.args[1])}
