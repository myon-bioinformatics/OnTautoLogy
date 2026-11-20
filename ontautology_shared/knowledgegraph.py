"""OTL adapters for concept corpora and RDF files."""
import argparse
from pathlib import Path

import ontautology as ot
from ._onto import knowledgegraph as shared
from ._onto.knowledgegraph import relation_cycles, topological_order

__all__ = ["relation_cycles", "topological_order", "rdf_mermaid", "turtle_mermaid", "graph_mermaid"]


def rdf_mermaid(path, *, focus=None):
    """Return a Markdown diagram of a saved RDF graph (requires the exchange extra)."""
    from graph_exchange import read_graph

    graph = read_graph(path)
    return shared.rdf_graph_mermaid(graph, focus=focus)


def graph_mermaid(data, *, focus=None):
    if data.get("schema") == ot.CONCEPT_SCHEMA:
        data = ot.concept_edges(data)
    return shared.graph_mermaid(data, focus=focus)


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
