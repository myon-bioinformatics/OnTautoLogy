import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

import onto_path

try:
    from rdflib import BNode, Graph, Literal, Namespace, RDF
    from rdflib.compare import isomorphic
    from ontautology_shared._onto.ontology import arcade, main as exchange_cli, statements
    from ontautology import exchange
except ModuleNotFoundError as exc:
    if exc.name != "rdflib" or os.getenv(onto_path.OTL_LIVE_ENV):
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

    def test_classify_turtle(self):
        for rule, verdict, value in ((["OR", "p", ["NOT", "p"]], "tautology", True),
                                     (["AND", "p", ["NOT", "p"]], "contradiction", False),
                                     ("p", "contingent", None)):
            done = subprocess.run([sys.executable, str(ROOT / "tools/tautology.py"), "classify",
                                   "--ttl", json.dumps(rule)], capture_output=True, text=True, check=True)
            graph = Graph().parse(data=done.stdout, format="turtle")
            prop, = graph.subjects(RDF.type, OTL.Proposition)
            self.assertEqual(graph.value(prop, OTL.classification), OTL[verdict])
            self.assertEqual(graph.value(prop, OTL.isTrue), Literal(value) if value is not None else None)

    def test_entailment_turtle_keeps_the_result_scoped(self):
        for premises, conclusion, verdict in [(["p"], "p", "entailed"), ([], "p", "counterexample"),
                                              (["p", ["NOT", "p"]], "q", "inconsistent-premises")]:
            done = subprocess.run([sys.executable, str(ROOT / "ontautology.py"), "entails", "-", "--ttl"],
                                  input=json.dumps(dict(premises=premises, conclusion=conclusion)),
                                  text=True, capture_output=True)
            self.assertEqual(done.returncode, 0 if verdict == "entailed" else 2, done.stderr)
            graph = Graph().parse(data=done.stdout, format="turtle")
            check, = graph.subjects(RDF.type, OTL.InferenceCheck)
            self.assertEqual(graph.value(check, OTL.verdict), OTL[verdict])
            self.assertEqual(len(set(graph.objects(check, OTL.premise))), len(premises))
            self.assertIsNotNone(graph.value(check, OTL.conclusion))
            self.assertFalse(list(graph.triples((None, OTL.isTrue, None))))
            if verdict == "counterexample":
                self.assertEqual(json.loads(str(graph.value(check, OTL.counterexample))), {"p": False})

    def test_opposing_judgments_share_one_proposition(self):
        corpus = json.loads((ROOT / "examples/concepts-20261115.json").read_text())
        first = corpus["judgments"][0]
        corpus["judgments"].append({**first, "actor": "再確認者", "holds": False, "evidence": "追試記録"})
        done = subprocess.run([sys.executable, str(ROOT / "tools/tautology.py"), "cases", "-", "--ttl"],
                              input=json.dumps(corpus), capture_output=True, text=True)
        self.assertEqual(done.returncode, 2, done.stderr)
        graph = Graph().parse(data=done.stdout, format="turtle")
        case = OTL["case:" + first["case"]]
        prop, = graph.subjects(OTL.aboutCase, case)
        yes, = graph.subjects(OTL.regardsAsTrue, prop)
        no, = graph.subjects(OTL.regardsAsFalse, prop)
        self.assertEqual(set(graph.objects(case, OTL.judgment)), {yes, no})
        self.assertEqual(graph.value(yes, OTL.actor), Literal(first["actor"]))
        self.assertEqual(graph.value(no, OTL.evidence), Literal("追試記録"))
        self.assertFalse(list(graph.triples((None, OTL.isTrue, None))))
        self.assertFalse(list(graph.objects(OTL["case:K003-shift-change"], OTL.judgment)))

    def test_event_is_the_shared_object_of_judgments_not_the_recipient(self):
        from tools.tautology import cases
        from ontautology_shared.truth import judgment_graph
        corpus = json.loads((ROOT / "examples/concepts-20261115.json").read_text())
        share = next(j for j in corpus["judgments"] if j["case"] == "K002-share-only")
        corpus["judgments"].append({**share, "actor": "担当F", "holds": False})
        graph = judgment_graph(corpus, cases(corpus)["cases"])
        graph = Graph().parse(data=graph.serialize(format="turtle"), format="turtle")
        event = OTL["event:K002-share-only"]
        self.assertEqual(graph.value(OTL["case:K002-share-only"], OTL.event), event)
        prop, = graph.subjects(OTL.aboutEvent, event)
        for field, person in ((OTL.regardsAsTrue, "担当E"), (OTL.regardsAsFalse, "担当F")):
            judgment, = graph.subjects(field, prop)
            self.assertEqual(graph.value(judgment, OTL.actor), Literal(person))
        self.assertEqual(graph.value(event, OTL.notifiedParty), Literal("関係者"))
        self.assertIsNone(graph.value(event, OTL.decisionRequestedFrom))
        request = OTL["event:K001-night-db"]
        self.assertEqual(graph.value(request, OTL.decisionRequestedFrom), Literal("二次対応"))
        self.assertEqual(graph.value(request, OTL.requestedDecision), Literal("再起動してよいか"))
        self.assertFalse(list(graph.objects(OTL["case:K003-shift-change"], OTL.event)))

    def test_markers_keep_repeated_roles_missing_values_and_empty_slots(self):
        from ontautology_shared.markers import MARKERS, marker_slots
        from ontautology_shared.truth import add_markers
        from urllib.parse import quote
        slots = marker_slots({"to": [{"role": "recipient", "value": v} for v in ("A", "B")],
                              "@none": [{"role": "content", "value": "report"}], "for": [],
                              "hereafter in": [{"role": "scope", "value": None}]})
        graph = Graph()
        event = OTL["event:one"]
        add_markers(graph, event, slots)
        graph = Graph().parse(data=graph.serialize(format="turtle"), format="turtle")
        predicate = lambda key: OTL["marker:" + quote(key, safe="")]
        self.assertEqual(set(graph.predicates(event)), {predicate(m) for m in MARKERS})
        self.assertEqual({graph.value(n, RDF.value) for n in graph.objects(event, predicate("to"))},
                         {Literal("A"), Literal("B")})
        self.assertEqual(graph.value(event, predicate("by")), OTL.Unspecified)
        self.assertEqual(graph.value(event, predicate("for")), RDF.nil)
        self.assertEqual(graph.value(graph.value(event, predicate("hereafter in")), RDF.value), OTL.Unknown)
        self.assertEqual(graph.value(graph.value(event, predicate("@none")), RDF.value), Literal("report"))

    def test_marker_expressions_share_only_explicit_local_meanings(self):
        from ontautology_shared.markers import marker_slots
        from ontautology_shared.truth import add_markers
        arg = {"role": "channel", "value": "chat", "meaning": "relay"}
        slots = marker_slots({"via": [{**arg, "expression": "via chat"}, {**arg, "expression": "via the chat"}],
                              "through": [{**arg, "expression": "through chat"}],
                              "by": [{"role": "channel", "value": "chat"}]})
        graph = Graph()
        for event in (OTL.first, OTL.second):
            add_markers(graph, event, slots)
        graph = Graph().parse(data=graph.serialize(format="turtle"), format="turtle")
        meanings = []
        for event in (OTL.first, OTL.second):
            records = set(graph.objects(event, OTL["marker:via"])) | set(graph.objects(event, OTL["marker:through"]))
            self.assertEqual({str(graph.value(r, OTL.expression)) for r in records},
                             {"via chat", "via the chat", "through chat"})
            meaning, = {graph.value(r, OTL.expresses) for r in records}
            self.assertEqual(graph.value(meaning, RDF.value), Literal("chat"))
            self.assertIsNone(graph.value(graph.value(event, OTL["marker:by"]), OTL.expresses))
            meanings.append(meaning)
        self.assertNotEqual(*meanings)

    def test_reversi_preview_shares_move_and_preserves_opposing_judgments(self):
        from examples import reversi
        graph = reversi.graph(reversi.opening_cases(), preview=True)
        graph = Graph().parse(data=graph.serialize(format="turtle"), format="turtle")
        self.assertEqual(len(set(graph.subjects(RDF.type, OTL.CandidateMove))), 6)
        move = OTL["reversi:d3/e3"]
        self.assertEqual(set(graph.objects(move, OTL.flips)), {Literal("e4")})
        prop, = graph.subjects(OTL.aboutEvent, move)
        for predicate, policy in ((OTL.regardsAsTrue, "mostFlips"), (OTL.regardsAsFalse, "fewestReplies")):
            judgment, = graph.subjects(predicate, prop)
            self.assertEqual(graph.value(judgment, OTL.actor), Literal(policy))
        self.assertIsNone(graph.value(prop, OTL.isTrue))

    def test_input_formats(self):
        from ontautology_shared._onto.ontology import read_graph
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

    @unittest.skipUnless(os.getenv(onto_path.OTL_LIVE_ENV), "requires both databases")
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
            if directory := os.getenv(onto_path.OTL_EXPORT_DIR_ENV):
                target = Path(directory) / ("-".join(route) + ".ttl")
                target.parent.mkdir(parents=True, exist_ok=True)
                current.serialize(destination=target, format="turtle")
                self.assertTrue(isomorphic(original, Graph().parse(target, format="turtle")))
                json_path = target.with_suffix(".json")
                self.assertEqual(exchange_cli(["export", backend, scope, str(json_path)]), 0)
                data = json.loads(json_path.read_text(encoding="utf-8"))
                terms = {node["id"]: node["properties"]["term"] for node in data["nodes"]}
                actual = [(terms[r["start"]["id"]], r["properties"]["predicate"],
                           terms[r["end"]["id"]]) for r in data["rels"]]
                self.assertEqual(actual, [(r["subject"], r["predicate"], r["object"])
                                          for r in statements(original)])


class PagesGraph(unittest.TestCase):
    def test_published_mermaid_matches_turtle(self):
        from ontautology_shared.knowledgegraph import rdf_mermaid

        root = ROOT / "site" / "concepts"
        diagram = (root / "bot.mmd").read_text(encoding="utf-8")
        self.assertEqual(rdf_mermaid(root / "bot.ttl"), f"```mermaid\n{diagram}```\n")


class WaveAtlas(unittest.TestCase):
    def test_claim_is_queryable_without_asserting_candidate(self):
        from scripts.atlas import OT, domain_graph, resource, views

        nodes = [{"id": "concept:AI", "name": "AI"}, {"id": "concept:bot", "name": "bot"}]
        edge = {"source": "concept:bot", "kind": "applicationOf", "target": "concept:AI",
                "basis": "hypothesis", "lock": "snapshot:test"}
        g = domain_graph({"nodes": nodes, "edges": [edge]})
        bot, ai = resource("concept:bot"), resource("concept:AI")
        self.assertNotIn((bot, OT.applicationOf, ai), g)
        claim, = g.subjects(RDF.subject, bot)
        self.assertIn((claim, RDF.object, ai), g)
        self.assertIn((claim, OT["field:lock"], resource("snapshot:test")), g)
        for index in range(19):
            g.add((bot, OT.test, Literal(index)))
        result = views(g, bot)
        pages = result["nodes"][result["start"]]["pages"]
        self.assertGreater(len(pages), 1)
        self.assertEqual(sum(len(p["edges"]) for p in pages), len(list(g.triples((bot, None, None)))) + 1)
