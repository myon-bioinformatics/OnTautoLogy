"""Inspect and visualize directed graphs supplied by callers."""
from graphlib import CycleError, TopologicalSorter

__all__ = ["relation_cycles", "topological_order", "rdf_graph_mermaid", "graph_mermaid"]


def relation_cycles(edges, *, limit=5):
    """Representative cycles, reported and never fatal: a graph with guesses and refutations need not be a DAG."""
    out = {}
    for edge in edges:
        out.setdefault(edge["source"], []).append(edge["target"])
    colour, found = {}, []
    for start in sorted(out):
        if colour.get(start):
            continue
        stack, path = [(start, iter(sorted(out[start])))], [start]
        colour[start] = 1
        while stack and len(found) < limit:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                colour[node] = 2
                stack.pop()
                path.pop()
            elif colour.get(child) == 1:
                found.append(path[path.index(child):] + [child])
            elif not colour.get(child):
                colour[child] = 1
                path.append(child)
                stack.append((child, iter(sorted(out.get(child, ())))))
    return found

def topological_order(edges):
    """Order nodes so each edge's source comes before its target.

    On success ``cycle`` is None and ``order`` lists every node that appears as a source or target; on a
    cycle, ``order`` is empty and ``cycle`` is the node list (first node repeated at the end). Ask the core
    ``order`` instead when the acyclic remainder should still be ordered.
    """
    predecessors = {}
    for edge in edges:
        predecessors.setdefault(edge["source"], set())
        predecessors.setdefault(edge["target"], set()).add(edge["source"])
    sorter = TopologicalSorter({key: sorted(values) for key, values in predecessors.items()})
    try:
        sorter.prepare()
    except CycleError as error:
        return {"order": [], "cycle": list(error.args[1])}
    ordered = []
    while sorter.is_active():
        ready = sorted(sorter.get_ready())
        ordered.extend(ready)
        sorter.done(*ready)
    return {"order": ordered, "cycle": None}


def rdf_graph_mermaid(graph, *, focus=None):
    """Draw an already parsed RDF graph with its namespace labels."""
    triples = [tuple(term.n3(graph.namespace_manager) for term in triple) for triple in graph]
    return _diagram({}, triples, focus)


def graph_mermaid(data, *, focus=None):
    """Draw the topology of an OTL graph, optionally just one node and its neighbours."""
    labels = {n["id"]: n.get("name", n["id"]) for n in data["nodes"]}
    if "edges" in data:
        triples = []
        for edge in data["edges"]:
            kind = edge["kind"] if "kind" in edge else edge["relation"]
            if edge.get("basis"):
                kind += " (" + edge["basis"] + ")"
            triples.append((edge["source"], kind, edge["target"]))
    else:
        # OTL graph JSON stores each RDF predicate on the directed statement.
        triples = [(r["start"]["id"], r["properties"]["predicate"], r["end"]["id"])
                   for r in data["rels"]]
    return _diagram(labels, triples, focus)


def _diagram(labels, triples, focus):
    terms = set(labels)
    for source, _, target in triples:
        terms.update((source, target))
    if focus is not None:
        if focus not in terms:
            raise ValueError(f"Unknown focus node: {focus}")
        triples = [t for t in triples if focus in (t[0], t[2])]
        terms = {focus} | {term for source, _, target in triples for term in (source, target)}
    terms = sorted(terms)
    ids = {term: f"n{i}" for i, term in enumerate(terms)}

    def label(value):
        # Mermaid decimal entities keep RDF strings inside their quoted labels.
        return "".join(c if c.isalnum() or c in " ._:-" else f"#{ord(c)};" for c in value)

    lines = ["```mermaid", "flowchart TD"]
    for term in terms:
        lines.append(f'  {ids[term]}["{label(labels.get(term, term))}"]')
    for subject, predicate, obj in sorted(triples):
        lines.append(f'  {ids[subject]} -->|"{label(predicate)}"| {ids[obj]}')
    return "\n".join([*lines, "```", ""])
