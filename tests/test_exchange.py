import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

try:
    from rdflib import BNode, Graph, Literal, Namespace, RDF
    from rdflib.compare import isomorphic
    from graph_exchange import arcade, statements
    from ontautology import exchange
except ModuleNotFoundError as exc:
    if exc.name != "rdflib" or os.getenv("OTL_LIVE"):
        raise
    raise unittest.SkipTest("install the exchange extra")


OTL = Namespace("urn:otl:")
ROOT = Path(__file__).resolve().parents[1]


def case_graph():
    """Project the first case, its source, and the human judgments from the existing fixture."""
    corpus = json.loads((ROOT / "examples/concepts-20261115.json").read_text())
    case = corpus["cases"][0]
    resource = OTL[case["id"]]
    graph = Graph()
    graph.add((resource, RDF.type, OTL.Case))
    graph.add((resource, OTL.statement, Literal(case["statement"], lang="ja")))
    graph.add((resource, OTL.evidence, Literal(case["evidence"])))
    for index, judgment in enumerate(corpus["judgments"]):
        if judgment["case"] == case["id"]:
            node = OTL[f"judgment-{index}"]
            graph.add((resource, OTL.judgment, node))
            for field in ("concept", "actor", "holds", "note"):
                graph.add((node, OTL[field], Literal(judgment[field])))
            graph.add((node, OTL.confidence, Literal(0)))
    # Independent counter-observation without a confidence value.
    graph.add((resource, OTL.judgment, OTL.counter))
    graph.add((OTL.counter, OTL.holds, Literal(False)))
    return graph


QUERY = """PREFIX ot: <urn:otl:>
SELECT ?case ?judgment ?evidence ?holds ?confidence WHERE {
  ?case ot:judgment ?judgment ; ot:evidence ?evidence .
  ?judgment ot:holds ?holds .
  OPTIONAL { ?judgment ot:confidence ?confidence }
}"""


class Exchange(unittest.TestCase):
    def test_fixture(self):
        original = case_graph()
        copy = Graph().parse(data=original.serialize(format="turtle"), format="turtle")
        self.assertTrue(isomorphic(original, copy))
        self.assertEqual({(bool(row.holds.toPython()), None if row.confidence is None
                           else row.confidence.toPython()) for row in copy.query(QUERY)},
                         {(True, 0), (False, None)})
        self.assertEqual(statements(original), statements(copy))
        snapshot = ROOT / "examples/K001-night-db.ttl"
        self.assertTrue(isomorphic(original, Graph().parse(snapshot, format="turtle")))
        from tools.knowledgegraph import turtle_mermaid
        diagram = turtle_mermaid(snapshot)
        self.assertEqual(diagram.count(" -->|"), len(original))
        self.assertIn("K001-night-db", diagram)
        copy.add((BNode(), RDF.type, OTL.Case))
        with self.assertRaisesRegex(ValueError, "stable IRIs"):
            statements(copy)

    def test_input_formats(self):
        from graph_exchange import read_graph
        from tools.knowledgegraph import rdf_mermaid

        graph = case_graph()
        with TemporaryDirectory() as directory:
            for extension, syntax in ((".ttl", "turtle"), (".nt", "nt"), (".rdf", "xml")):
                with self.subTest(extension=extension):
                    path = Path(directory) / ("case" + extension)
                    graph.serialize(destination=path, format=syntax, encoding="utf-8")
                    self.assertTrue(isomorphic(graph, read_graph(path)))
                    self.assertEqual(rdf_mermaid(path).count(" -->|"), len(graph))
            with self.assertRaisesRegex(ValueError, "input extensions"):
                read_graph(Path(directory) / "case.nq")

    @unittest.skipUnless(os.getenv("OTL_LIVE"), "requires both databases")
    def test_both_directions(self):
        for command in ("CREATE VERTEX TYPE OtlTerm IF NOT EXISTS",
                        "CREATE EDGE TYPE OtlStatement IF NOT EXISTS"):
            arcade("sql", command, {})
        original = case_graph()
        expected = set(original.query(QUERY))
        for route in (("neo4j", "arcade", "neo4j"), ("arcade", "neo4j", "arcade")):
            current = original
            for backend in route:
                scope = uuid4().hex
                for _ in range(2):
                    exchange(backend, scope, current)
                current = exchange(backend, scope)
                self.assertTrue(isomorphic(original, current))
                self.assertEqual(expected, set(current.query(QUERY)))
                current = Graph().parse(data=current.serialize(format="turtle"), format="turtle")
            if directory := os.getenv("OTL_EXPORT_DIR"):
                target = Path(directory) / ("-".join(route) + ".ttl")
                target.parent.mkdir(parents=True, exist_ok=True)
                current.serialize(destination=target, format="turtle")
                self.assertTrue(isomorphic(original, Graph().parse(target, format="turtle")))
