"""tools/ — knowledgegraph, ontology, tautology. Each test states a judgement, not how it is computed.

Standard library only, except RedisCrossCheck: an independent answer from Redis for the same inputs, used to
try an idea with an outside module first. It is skipped without the redis package and a redis-server binary,
and fails instead of skipping in the CI job named redis.
"""
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import ontautology as ot  # noqa: E402
from tools import knowledgegraph, ontology, tautology  # noqa: E402


def edge(source, target, basis="observed", kind="dependsOn"):
    return {"kind": kind, "source": source, "target": target, "basis": basis}


def random_graph(seed, nodes=12, edges=24):
    """Edges among n0..n{nodes-1} with every basis, cycles and self-loops allowed."""
    rng = random.Random(seed)
    names = [f"n{i}" for i in range(nodes)]
    return [edge(rng.choice(names), rng.choice(names), rng.choice(ot.BASIS), rng.choice(("a", "b"))) for _ in range(edges)]


class OneWayDependency(unittest.TestCase):
    def test_core_never_imports_tools_and_tools_never_import_each_other(self):
        core = (ROOT / "ontautology.py").read_text(encoding="utf-8")
        self.assertNotIn("import tools", core)
        self.assertNotIn("from tools", core)
        for path in sorted((ROOT / "tools").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(tool=path.name):
                self.assertIn("import ontautology as ot", text)
                self.assertNotIn("from tools", text)
                self.assertNotIn("import tools", text)

    def test_every_public_name_is_callable(self):
        for module in (knowledgegraph, ontology, tautology):
            for name in module.__all__:
                with self.subTest(module=module.__name__, name=name):
                    self.assertTrue(callable(getattr(module, name)))


class RelationCyclesTests(unittest.TestCase):
    def test_parent_cycle_is_reported_and_an_acyclic_branch_is_omitted(self):
        # Same assertion as fleet_records.ShapesCyclesLimits.test_cycles_are_reported_and_the_rest_is_still_walked
        relations = [{"kind": "derived_from", "source": "a:x", "target": "a:y", "lock": "a:r"},
                     {"kind": "derived_from", "source": "a:y", "target": "a:x", "lock": "a:r"},
                     {"kind": "derived_from", "source": "b:p", "target": "b:q", "lock": "b:r"}]
        self.assertEqual(knowledgegraph.relation_cycles(relations), [["a:x", "a:y", "a:x"]])

    def test_empty_and_a_chain_have_no_cycle(self):
        self.assertEqual(knowledgegraph.relation_cycles([]), [])
        self.assertEqual(knowledgegraph.relation_cycles([edge("a", "b"), edge("b", "c")]), [])

    def test_self_loop_and_limit(self):
        self.assertEqual(knowledgegraph.relation_cycles([edge("x", "x")]), [["x", "x"]])
        pairs = [edge(a, b) for a, b in ("ab", "ba", "cd", "dc", "ef", "fe")]
        found = knowledgegraph.relation_cycles(pairs, limit=2)
        self.assertEqual(len(found), 2)
        self.assertTrue(all(c[0] == c[-1] for c in found))

    def test_same_answer_as_the_core(self):
        for seed in range(20):
            graph = random_graph(seed)
            with self.subTest(seed=seed):
                self.assertEqual(knowledgegraph.relation_cycles(graph), ot.cycles(graph))


class TopologicalOrderTests(unittest.TestCase):
    def test_sources_precede_targets(self):
        self.assertEqual(knowledgegraph.topological_order([edge("a", "b"), edge("b", "c")]),
                         {"order": ["a", "b", "c"], "cycle": None})

    def test_diamond_includes_every_node_once(self):
        result = knowledgegraph.topological_order([edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("c", "d")])
        self.assertIsNone(result["cycle"])
        order = result["order"]
        self.assertEqual(sorted(order), ["a", "b", "c", "d"])
        for before, after in ("ab", "ac", "bd", "cd"):
            self.assertLess(order.index(before), order.index(after))

    def test_cycle_clears_the_order(self):
        result = knowledgegraph.topological_order([edge("a", "b"), edge("b", "a")])
        self.assertEqual(result["order"], [])
        self.assertEqual(result["cycle"][0], result["cycle"][-1])

    def test_edges_without_kind_are_accepted(self):
        self.assertEqual(knowledgegraph.topological_order([{"source": "a", "target": "b"}])["order"], ["a", "b"])


class OntologyTests(unittest.TestCase):
    def graph(self):
        return {"nodes": [{"id": "pr:a#1", "type": "PullRequest"}, {"id": "repo:a", "type": "Repository"}],
                "edges": [{"source": "pr:a#1", "relation": "belongsTo", "target": "repo:a"}]}

    def test_classes_come_from_the_relations_only(self):
        self.assertEqual(ontology.classes(), ot._classes())
        self.assertEqual(ontology.classes({"implies": (("Rule",), "Rule")}), ["Rule"])

    def test_a_graph_in_its_vocabulary_has_no_violation(self):
        self.assertEqual(ontology.violations(self.graph()), [])
        example = ot.audit([json.loads((ROOT / "examples/audit-20261114.json").read_text(encoding="utf-8"))])
        self.assertEqual(ontology.violations(example), [])

    def test_every_violation_is_listed_and_nothing_is_repaired(self):
        graph = self.graph()
        graph["nodes"] += [{"id": "repo:a", "type": "Repository"}, {"id": "x", "type": "Ghost"}]
        graph["edges"] += [{"source": "repo:a", "relation": "belongsTo", "target": "pr:a#1"},
                           {"source": "pr:a#1", "relation": "mentions", "target": "repo:a"},
                           {"source": "pr:a#1", "relation": "belongsTo", "target": "nowhere"}]
        before = json.dumps(graph, sort_keys=True)
        kinds = [finding["kind"] for finding in ontology.violations(graph)]
        self.assertEqual(kinds, ["duplicate-node", "unknown-class", "domain-range", "unknown-relation", "missing-reference"])
        self.assertEqual(json.dumps(graph, sort_keys=True), before)

    def test_the_core_validate_rejects_what_violations_lists(self):
        graph = self.graph()
        graph["edges"].append({"source": "repo:a", "relation": "belongsTo", "target": "pr:a#1"})
        self.assertTrue(ontology.violations(graph))
        with self.assertRaises(ValueError):
            ot.validate({"schema": ot.KG_SCHEMA, **graph})

    def test_identity_promotes_the_first_candidate_that_is_a_key(self):
        items = [{"id": 1, "run": 1, "name": "a"}, {"id": 1, "run": 2, "name": "b"}]
        found = ontology.identity(items, [("id",), ("id", "run"), ("name",)])
        self.assertEqual(found["key"], ["id", "run"])
        self.assertEqual(found["report"]["id"]["verdict"], "collides")

    def test_identity_stays_open_while_nothing_qualifies(self):
        items = [{"id": 1}, {"id": 1}, {"name": "x"}]
        found = ontology.identity(items, [("id",), ("name",)])
        self.assertIsNone(found["key"])
        self.assertEqual({k: v["verdict"] for k, v in found["report"].items()}, {"id": "incomplete", "name": "incomplete"})

    def test_one_more_entry_takes_a_key_away(self):
        items = [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}]
        self.assertEqual(ontology.identity(items, [("id",)])["key"], ["id"])
        self.assertIsNone(ontology.identity(items + [{"id": 1, "v": "c"}], [("id",)])["key"])


class TautologyTests(unittest.TestCase):
    def test_a_chain_stands_on_its_weakest_edge(self):
        edges = [edge("a", "b", "proof"), edge("b", "c", "hypothesis"), edge("c", "d", "proof")]
        self.assertEqual(tautology.standing(edges, "d"), {"node": "d", "level": "hypothesis", "edges": 3, "tautology": False})
        self.assertEqual(tautology.standing(edges, "b")["level"], "proof")
        self.assertTrue(tautology.standing(edges, "b")["tautology"])

    def test_a_given_is_not_a_proof(self):
        self.assertEqual(tautology.standing([edge("a", "b", "proof")], "a"),
                         {"node": "a", "level": None, "edges": 0, "tautology": False})

    def test_depth_has_no_limit_unlike_why(self):
        chain = [edge(f"n{i}", f"n{i + 1}", "proof") for i in range(9)] + [edge("x", "n0", "derived")]
        self.assertEqual(tautology.standing(chain, "n9")["level"], "derived")
        self.assertTrue(ot.why(chain, "n9")["cut"])

    def test_cycles_terminate(self):
        self.assertEqual(tautology.standing([edge("a", "b", "proof"), edge("b", "a", "proof")], "a")["level"], "proof")

    def test_gaps_are_the_edges_below_proof_weakest_first(self):
        edges = [edge("a", "b", "observed"), edge("b", "c", "proof"), edge("c", "d", "hypothesis"), {"kind": "k", "source": "d", "target": "e"}]
        found = tautology.gaps(edges)
        self.assertEqual((found["edges"], found["proof"]), (4, 1))
        self.assertEqual([ot._basis(e) for e in found["gaps"]], ["hypothesis", "observed", "observed"])

    def test_entailed_follows_proof_edges_of_transitive_kinds_only(self):
        edges = [edge("a", "b", "proof", "implies"), edge("b", "c", "proof", "implies"), edge("c", "d", "observed", "implies"),
                 edge("x", "y", "proof", "touches"), edge("y", "z", "proof", "touches")]
        self.assertEqual(tautology.entailed(edges, ["implies"]),
                         [{"kind": "implies", "source": "a", "target": "c", "basis": "proof", "via": ["a", "b", "c"]}])

    def test_entailed_skips_what_is_already_stated_at_proof(self):
        edges = [edge("a", "b", "proof", "k"), edge("b", "c", "proof", "k"), edge("a", "c", "proof", "k")]
        self.assertEqual(tautology.entailed(edges, ["k"]), [])

    def test_raising_the_entailed_edges_closes_the_graph(self):
        for seed in range(20):
            edges = [dict(e, basis="proof") for e in random_graph(seed, nodes=6, edges=10)]
            closed = edges + [{k: v for k, v in e.items() if k != "via"} for e in tautology.entailed(edges, ["a", "b"])]
            with self.subTest(seed=seed):
                self.assertEqual(tautology.entailed(closed, ["a", "b"]), [])


def _redis_or_skip(case):
    """A throwaway redis-server on a unix socket in a temporary directory: no port, nothing saved."""
    try:
        import redis
    except ImportError:
        redis = None
    server = shutil.which("redis-server")
    if redis is None or server is None:
        message = "redis package or redis-server is not available"
        if os.environ.get("GITHUB_JOB") == "redis":
            case.fail(message + " in the redis CI job")
        case.skipTest(message)
    folder = tempfile.mkdtemp()
    socket = os.path.join(folder, "redis.sock")
    process = subprocess.Popen([server, "--port", "0", "--unixsocket", socket, "--save", "", "--appendonly", "no",
                                "--dir", folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = redis.Redis(unix_socket_path=socket, decode_responses=True)
    for _ in range(100):
        try:
            client.ping()
            break
        except redis.exceptions.ConnectionError:
            time.sleep(0.05)
    else:
        process.kill()
        case.fail("redis-server did not start")

    def stop():
        process.terminate()
        process.wait(timeout=10)
        shutil.rmtree(folder, ignore_errors=True)
    return client, stop


class RedisCrossCheck(unittest.TestCase):
    """Redis answers the same questions with its own data structures; the core must agree on every input."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.stop = _redis_or_skip(cls())

    @classmethod
    def tearDownClass(cls):
        cls.stop()

    def setUp(self):
        self.client.flushdb()

    def redis_reach(self, edges, start):
        """Forward walk over Redis sets, never through a hypothesis."""
        for e in edges:
            if ot._basis(e) != "hypothesis":
                self.client.sadd("out:" + e["source"], e["target"])
        seen, queue = set(start), list(start)
        while queue:
            for target in self.client.smembers("out:" + queue.pop(0)):
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        return seen - set(start)

    def redis_verdict(self, items, fields):
        """Uniqueness through HSETNX: the first entry claims a value, a different entry under it collides."""
        missing = collides = repeats = 0
        for item in items:
            if any(item.get(f) in (None, "") for f in fields):
                missing += 1
                continue
            value, text = "+".join(str(item[f]) for f in fields), json.dumps(item, sort_keys=True, ensure_ascii=False)
            if not self.client.hsetnx("key:" + "+".join(fields), value, text):
                if self.client.hget("key:" + "+".join(fields), value) != text:
                    collides += 1
                else:
                    repeats += 1
        return "incomplete" if missing else "collides" if collides else "repeat" if repeats else "key"

    def test_reach_agrees_with_redis(self):
        for seed in range(30):
            self.client.flushdb()
            edges = random_graph(seed)
            start = sorted({e["source"] for e in edges})[:2]
            with self.subTest(seed=seed):
                self.assertEqual({row["node"] for row in ot.reach(edges, start)["rows"]}, self.redis_reach(edges, start))

    def test_key_verdicts_agree_with_redis(self):
        for seed in range(30):
            rng = random.Random(seed)
            items = [{"id": rng.randint(1, 6), "run": rng.choice([1, 2, None]), "name": rng.choice("abc")} for _ in range(8)]
            items += rng.sample(items, 2)
            for fields in (("id",), ("id", "run"), ("name",), ("id", "name")):
                self.client.flushdb()
                with self.subTest(seed=seed, fields=fields):
                    self.assertEqual(ot.key_report(items, [fields])["+".join(fields)]["verdict"], self.redis_verdict(items, fields))


if __name__ == "__main__":
    unittest.main()
