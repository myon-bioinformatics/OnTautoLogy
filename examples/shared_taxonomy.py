"""Run with an installed copy of ontautology, from any checkout."""
from ontautology_shared import knowledgegraph, ontology

# The consumer defines its vocabulary and stable IDs. Edges point from parent to child.
vocabulary = {"narrower": (["Category"], "Category")}
graph = {
    "nodes": [{"id": key, "type": "Category"} for key in ("A", "B", "C")],
    "edges": [
        {"source": "B", "relation": "narrower", "target": "A"},
        {"source": "C", "relation": "narrower", "target": "A"},
    ],
}

assert ontology.violations(graph, vocabulary) == []
assert knowledgegraph.relation_cycles(graph["edges"]) == []
diagram = knowledgegraph.graph_mermaid(graph, focus="A")
assert diagram.count(' -->|"narrower"| ') == 2
print(diagram, end="")
