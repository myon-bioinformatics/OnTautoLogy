"""Knowledge-graph tool: graph-shape answers under the names the parent's fleet code uses. Standard library only.

The walks themselves live in the core (ontautology.py); nothing is implemented twice here. This file keeps
the names and return shapes of myon-bioinformatics/myon-bioinformatics fleet_records.relation_cycles and the
static-order pattern of vendor_fleet_plan.build_graph, so the parent can call these instead of its own copies.

Project vocabularies and records are supplied by the caller.
"""
import argparse
from pathlib import Path

import ontautology as ot

__all__ = ["relation_cycles", "topological_order", "rdf_mermaid", "turtle_mermaid", "graph_mermaid"]


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


def rdf_mermaid(path, *, focus=None):
    """Return a Markdown diagram of a saved RDF graph (requires the exchange extra)."""
    from graph_exchange import read_graph

    graph = read_graph(path)
    triples = [tuple(term.n3(graph.namespace_manager) for term in triple) for triple in graph]
    return _diagram({}, triples, focus)


def graph_mermaid(data, *, focus=None):
    """Draw the topology of an OTL graph, optionally just one node and its neighbours."""
    if data.get("schema") == ot.CONCEPT_SCHEMA:
        data = ot.concept_edges(data)
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


turtle_mermaid = rdf_mermaid


def main(argv=None):
    """Render a graph from the command line."""
    parser = argparse.ArgumentParser(description="Render an OTL or RDF graph as Mermaid Markdown.")
    parser.add_argument("file", type=Path, help=".json, .ttl, .nt, .rdf")
    parser.add_argument("--focus", help="show only this node ID and its immediate neighbours")
    args = parser.parse_args(argv)
    try:
        if args.file.suffix.lower() == ".json" or str(args.file) == "-":
            diagram = graph_mermaid(ot._read_json(args.file), focus=args.focus)
        else:
            diagram = rdf_mermaid(args.file, focus=args.focus)
        print(diagram, end="")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
