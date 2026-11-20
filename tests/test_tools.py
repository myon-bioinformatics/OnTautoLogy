"""tools/ — knowledgegraph, ontology, tautology. Each test states a judgement, not how it is computed.

Standard library only, except RedisCrossCheck: an independent answer from Redis for the same inputs, used to
try an idea with an outside module first. It is skipped without the redis package and a redis-server binary,
and fails instead of skipping in the CI job named redis.
"""
import json
import os
import random
import re
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
from gh_audit import gh_audit as ga  # noqa: E402
from tools import knowledgegraph, ontology, tautology  # noqa: E402


def edge(source, target, basis="observed", kind="dependsOn"):
    return {"kind": kind, "source": source, "target": target, "basis": basis}


def random_graph(seed, nodes=12, edges=24):
    """Edges among n0..n{nodes-1} with every basis, cycles and self-loops allowed."""
    rng = random.Random(seed)
    names = [f"n{i}" for i in range(nodes)]
    return [edge(rng.choice(names), rng.choice(names), rng.choice(ot.BASIS), rng.choice(("a", "b"))) for _ in range(edges)]


class OneWayDependency(unittest.TestCase):
    def test_generic_code_never_reads_the_github_audit(self):
        for path in [ROOT / "ontautology.py", *(ROOT / "tools").glob("*.py"),
                     *(ROOT / "ontautology_shared").glob("*.py")]:
            imports = "\n".join(re.findall(r"(?m)^(?:from|import) .*", path.read_text(encoding="utf-8")))
            with self.subTest(file=path.name):
                self.assertNotIn("gh_audit", imports)
                self.assertIsNone(re.search(r"\b(?:from|import) tools\b", imports))
                if path.name in ("ontology.py", "knowledgegraph.py") and path.parent.name == "tools":
                    self.assertIn("from ontautology_shared.", imports)
                elif path.name != "__init__.py" and path != ROOT / "ontautology.py":
                    self.assertIn("import ontautology as ot", imports)
        audit = "\n".join(re.findall(r"(?m)^(?:from|import) .*", (ROOT / "gh_audit/gh_audit.py").read_text(encoding="utf-8")))
        self.assertIn("import ontautology as ot", audit)

    def test_every_public_name_is_callable(self):
        for module in (ga, knowledgegraph, ontology, tautology):
            for name in (name for name in module.__all__ if not name.isupper()):  # upper case: a vocabulary, not a call
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
        self.assertIn("PullRequest", ontology.classes(ga.RELATIONS))
        self.assertEqual(ontology.classes({"implies": (("Rule",), "Rule")}), ["Rule"])

    def test_a_graph_in_its_vocabulary_has_no_violation(self):
        self.assertEqual(ontology.violations(self.graph(), ga.RELATIONS), [])
        example = ga.audit([json.loads((ROOT / "examples/audit-20261114.json").read_text(encoding="utf-8"))])
        self.assertEqual(ontology.violations(example, ga.RELATIONS), [])

    def test_every_violation_is_listed_and_nothing_is_repaired(self):
        graph = self.graph()
        graph["nodes"] += [{"id": "repo:a", "type": "Repository"}, {"id": "x", "type": "Ghost"}]
        graph["edges"] += [{"source": "repo:a", "relation": "belongsTo", "target": "pr:a#1"},
                           {"source": "pr:a#1", "relation": "mentions", "target": "repo:a"},
                           {"source": "pr:a#1", "relation": "belongsTo", "target": "nowhere"}]
        before = json.dumps(graph, sort_keys=True)
        kinds = [finding["kind"] for finding in ontology.violations(graph, ga.RELATIONS)]
        self.assertEqual(kinds, ["duplicate-node", "unknown-class", "domain-range", "unknown-relation", "missing-reference"])
        self.assertEqual(json.dumps(graph, sort_keys=True), before)

    def test_the_core_validate_rejects_what_violations_lists(self):
        graph = self.graph()
        graph["edges"].append({"source": "repo:a", "relation": "belongsTo", "target": "pr:a#1"})
        self.assertTrue(ontology.violations(graph, ga.RELATIONS))
        with self.assertRaises(ValueError):
            ga.validate({"schema": ga.KG_SCHEMA, **graph})

    def readme_vocabulary(self, heading):
        """(classes, {(class, relation, target class)}) from a README table of classes and outgoing relations."""
        section = (ROOT / "README.md").read_text(encoding="utf-8").split(heading + "\n", 1)[1].split("\n#", 1)[0]
        classes, triples = set(), set()
        for line in section.splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) != 3 or not cells[0].startswith("`"):
                continue
            name = cells[0].strip("`")
            classes.add(name)
            for part in cells[2].split("・"):
                if "→" in part:
                    relations, target = part.split("→")
                    triples |= {(name, relation, target.strip()) for relation in re.findall(r"`(\w+)`", relations)}
        return classes, triples

    def test_readme_tables_hold_exactly_the_code_vocabulary(self):
        classes, triples = self.readme_vocabulary("### 🔭 第一弾のクラスと関係")
        self.assertEqual(classes, set(ontology.classes(ga.RELATIONS)))
        self.assertEqual(triples, {(domain, relation, target) for relation, (domains, target) in ga.RELATIONS.items() for domain in domains})
        graph = ot.concept_edges(concepts())
        kinds = {node["id"]: node["type"] for node in graph["nodes"]}
        classes, triples = self.readme_vocabulary("### 🧩 第二弾のクラスと関係")
        self.assertEqual(classes, set(kinds.values()))
        self.assertEqual(triples, {(kinds[e["source"]], e["kind"], kinds[e["target"]]) for e in graph["edges"]})

    def test_readme_layer_diagram_draws_only_code_relations_as_solid(self):
        section = (ROOT / "README.md").read_text(encoding="utf-8").split("## 🧭 全体図（監視・中間・管理の3層）\n", 1)[1].split("\n## ", 1)[0]
        diagram = section.split("```mermaid\n", 1)[1].split("```", 1)[0]
        labels = dict(re.findall(r"(?m)^\s*(\w+)\[(\w+)", diagram))  # node id → class
        graph = ot.concept_edges(concepts())
        kinds = {node["id"]: node["type"] for node in graph["nodes"]}
        code = ({(domain, relation, target) for relation, (domains, target) in ga.RELATIONS.items() for domain in domains}
                | {(kinds[e["source"]], e["kind"], kinds[e["target"]]) for e in graph["edges"]})
        self.assertLessEqual(set(labels.values()), set(ontology.classes(ga.RELATIONS)) | set(kinds.values()))
        drawn = {"solid": 0, "dashed": 0}
        for source, arrow, relations, target in re.findall(r"(?m)^\s*(\w+) (<?-->|-\.->)\|([^|]+)\| (\w+)", diagram):
            for relation in (name.strip() for name in relations.split("/")):
                with self.subTest(edge=(source, relation, target)):
                    if arrow == "-.->":  # a design not yet in the code
                        self.assertNotIn(relation, {name for _, name, _ in code})
                        drawn["dashed"] += 1
                    else:
                        self.assertIn((labels[source], relation, labels[target]), code)
                        drawn["solid"] += 1
        self.assertTrue(drawn["solid"] and drawn["dashed"], drawn)
        for box, vocabulary in (("GH", set(ontology.classes(ga.RELATIONS))), ("SIM", set(kinds.values()))):
            inside = diagram.split(f"subgraph {box}[", 1)[1].split("\n    end", 1)[0]
            with self.subTest(middle=box):
                self.assertTrue(set(re.findall(r"(?m)^\s*\w+\[(\w+)", inside)) <= vocabulary)

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


def concepts():
    """The example corpus; its ``seeds`` are the 〇〇 to define (edit the JSON to add more)."""
    return json.loads((ROOT / "examples/concepts-20261115.json").read_text(encoding="utf-8"))


def random_rule(rng, names, depth=3):
    """A random rule tree over ``names`` with every operator."""
    if depth == 0 or rng.random() < 0.3:
        return rng.choice(names)
    op = rng.choice(sorted(tautology.OPS))
    return [op, random_rule(rng, names, depth - 1)] if op == "NOT" else [op, *(random_rule(rng, names, depth - 1) for _ in range(rng.randint(0, 3)))]


def random_corpus(seed, size=8):
    rng = random.Random(seed)
    features = [f"f{i}" for i in range(6)]
    names = [f"c{i}" for i in range(size)]
    return {"concepts": {n: sorted(rng.sample(features, rng.randint(1, 5))) for n in names},
            "similar": [[a, b] for a, b in zip(names, names[1:]) if rng.random() < 0.7]}, features


class JudgeTests(unittest.TestCase):
    def test_operators_and_empty_cases(self):
        present = {"a"}
        self.assertEqual([tautology.holds([op, "a", "b"], present) for op in ("AND", "OR", "NAND", "NOR")], [False, True, True, False])
        self.assertTrue(tautology.holds(["NOT", "b"], present))
        self.assertEqual((tautology.holds(["AND"], set()), tautology.holds(["OR"], set())), (True, False))
        for bad in ([], ["XOR", "a"], ["NOT", "a", "b"], 3):
            with self.subTest(rule=bad), self.assertRaises(ValueError):
                tautology.holds(bad, present)

    def test_every_seed_has_a_reversible_definition_and_the_genus_alone_lets_the_neighbour_in(self):
        corpus = concepts()
        for seed in corpus["seeds"]:
            found = tautology.rules(corpus, seed)
            with self.subTest(seed=seed):
                self.assertIsNotNone(found["definition"])
                self.assertEqual(tautology.judge(corpus, seed, found["definition"])["verdict"], "reversible")
                genus = next(row for row in found["candidates"] if row["shape"] == "genus")
                self.assertEqual(genus["verdict"], "refuted")
                self.assertTrue(genus["fp"])
                self.assertFalse(genus["fn"])
                self.assertEqual(genus["propositions"], {"proposition": False, "contrapositive": False, "converse": True, "inverse": True})

    def test_command_line_rules_judge_and_equivalent(self):
        from test_ontautology import run_cli
        script, corpus_path = ROOT / "tools/tautology.py", str(ROOT / "examples/concepts-20261115.json")
        found = run_cli(script, "rules", corpus_path)
        self.assertEqual(found.returncode, 0, found.stderr)
        answer = json.loads(found.stdout)
        self.assertEqual(list(answer), concepts()["seeds"])
        self.assertEqual(answer["ギター"]["definition"], tautology.rules(concepts(), "ギター")["definition"])
        self.assertEqual(json.loads(run_cli(script, "rules", "-", "鮭", data=json.dumps(concepts())).stdout)["鮭"]["definition"],
                         tautology.rules(concepts(), "鮭")["definition"])
        genus = run_cli(script, "judge", corpus_path, "ギター", json.dumps(["AND", "弦楽器", "撥弦", "フレット"]))
        self.assertEqual((genus.returncode, json.loads(genus.stdout)["fp"]), (2, ["ウクレレ", "ベース"]))
        self.assertEqual(json.loads(run_cli(script, "judge", corpus_path, "ギター", "6弦標準").stdout)["verdict"], "reversible")
        self.assertEqual(run_cli(script, "equivalent", '["NOR", "a", "b"]', '["AND", ["NOT", "a"], ["NOT", "b"]]').returncode, 0)
        self.assertEqual(run_cli(script, "equivalent", '["NAND", "a", "b"]', '["NOR", "a", "b"]').returncode, 2)
        self.assertEqual(run_cli(script, "judge", corpus_path, "存在しない", "a").returncode, 1)

    def test_the_definition_is_built_from_what_the_concept_has(self):
        corpus = concepts()
        # five clues, any four; 配管工 is no key (マリオ has it too), and the name side (series, name origin) is not used
        clues = ["初登場年:1983", "帽子のマーク:L", "弟", "緑色", "誕生:マリオの2Pカラー"]
        four = [["AND", *(clue for j, clue in enumerate(clues) if j != left)] for left in reversed(range(len(clues)))]
        self.assertEqual(tautology.rules(corpus, "ルイージ")["definition"],
                         ["AND", "オーバーオール", "ゲームキャラクター", "人間", "任天堂", "帽子", ["OR", *four]])
        # ピアノ shares the genus of ギター without being similar, so excluding the neighbours is not enough there
        # three clues, any two: 6弦標準, a model, a riff (the key search stops at five, so 開放弦 is not among them)
        models = ["OR", "代表モデル:ストラトキャスター", "代表モデル:レスポール"]
        riffs = ["OR", "有名なリフ:Seven Nation Army", "有名なリフ:Smoke on the Water"]
        self.assertEqual(tautology.rules(corpus, "ギター")["definition"],
                         ["AND", "ボディ", "弦楽器", "楽器", ["OR", ["AND", "6弦標準", models], ["AND", "6弦標準", riffs], ["AND", models, riffs]]])
        for seed in corpus["seeds"]:
            with self.subTest(seed=seed):
                self.assertEqual(tautology.rules(corpus, seed)["candidates"][0]["shape"], "genus-most-differentia")

    def test_the_values_of_one_attribute_are_one_clue(self):
        # 別名 is one question in guess, so it is one clue here: either alias will do, and two aliases do not count twice
        corpus = {"seeds": ["鮭"], "similar": [["鮭", "サクラマス"], ["鮭", "スチールヘッド"]],
                  "concepts": {"鮭": ["魚", "別名:アキアジ", "別名:トキシラズ", "料理:ちゃんちゃん焼き"], "サクラマス": ["魚", "桜色"],
                               "スチールヘッド": ["魚", "虹色"]}}
        rule = tautology.rules(corpus, "鮭")["definition"]
        self.assertEqual(rule, ["AND", "魚", ["OR", ["AND", "料理:ちゃんちゃん焼き"], ["AND", ["OR", "別名:アキアジ", "別名:トキシラズ"]]]])
        self.assertTrue(tautology.holds(rule, {"魚", "別名:トキシラズ"}))
        self.assertFalse(tautology.holds(rule, {"魚"}))

    def test_one_key_shared_with_an_unseen_twin_is_not_enough(self):
        # 配管工 is only マリオ's and ルイージ's. With マリオ hidden it looks like a key of ルイージ; any one key would let
        # マリオ in, all but one of the three keeps him out.
        corpus = {"seeds": ["ルイージ"], "similar": [["ルイージ", "マリオ"], ["ルイージ", "ワリオ"]],
                  "concepts": {"ルイージ": ["人間", "配管工", "緑色", "弟"], "マリオ": ["人間", "配管工", "赤色", "兄"],
                               "ワリオ": ["人間", "黄色"]}}
        rule = tautology.rules(tautology._without(corpus, "マリオ"), "ルイージ")["definition"]
        self.assertEqual(rule, ["AND", "人間", ["OR", ["AND", "弟", "緑色"], ["AND", "弟", "配管工"], ["AND", "緑色", "配管工"]]])
        self.assertTrue(tautology.holds(["AND", "人間", ["OR", "配管工", "緑色", "弟"]], set(corpus["concepts"]["マリオ"])))
        self.assertEqual(tautology.holdout(corpus)["concepts"]["ルイージ"]["unseen"]["fp"], [])

    def test_a_nor_of_the_seen_neighbours_is_only_the_fallback(self):
        # With コーヒー hidden, "a drink that is not カクテル" is shorter and reversible on what is left, but it knows only
        # カクテル: the unseen コーヒー is not カクテル either. What エナジードリンク has comes first.
        corpus = {"seeds": ["エナジードリンク"], "similar": [["エナジードリンク", "コーヒー"], ["エナジードリンク", "カクテル"]],
                  "concepts": {"エナジードリンク": ["飲料", "カフェイン含有", "炭酸", "甘味料"], "コーヒー": ["飲料", "カフェイン含有", "苦味"],
                               "カクテル": ["飲料", "アルコール含有"]}}
        found = tautology.rules(tautology._without(corpus, "コーヒー"), "エナジードリンク")["candidates"]
        nor = next(row for row in found if row["shape"] == "genus-nor-neighbours")
        self.assertEqual((nor["verdict"], nor["atoms"] < found[0]["atoms"]), ("reversible", True))
        self.assertTrue(tautology.holds(nor["rule"], set(corpus["concepts"]["コーヒー"])))
        self.assertEqual(found[0]["shape"], "genus-most-differentia")
        self.assertEqual(tautology.holdout(corpus)["concepts"]["エナジードリンク"]["unseen"]["fp"], [])

    def test_holdout_shows_the_one_similar_trap(self):
        # With one similar concept, hiding it leaves only the far ピアノ to tell ギター from: a short key (撥弦)
        # is enough there, and the hidden ベース has it too, so the rebuilt definition lets ベース in.
        corpus = {"seeds": ["ギター"], "similar": [["ギター", "ベース"]],
                  "concepts": {"ギター": ["楽器", "撥弦", "6弦標準"], "ベース": ["楽器", "撥弦", "4弦標準", "低音主体"],
                               "ピアノ": ["楽器", "打弦", "鍵盤"]}}
        found = tautology.holdout(corpus)
        self.assertEqual(found["concepts"]["ギター"]["unseen"], {"tested": 2, "fp": ["ベース"], "undefined": []})
        self.assertEqual(found["summary"]["unseen"], {"tested": 2, "fp": 1, "rate": 0.5})

    def test_holdout_passes_when_the_hidden_one_is_still_excluded(self):
        corpus = {"seeds": ["ギター"], "similar": [["ギター", "ベース"], ["ギター", "ウクレレ"]],
                  "concepts": {"ギター": ["楽器", "撥弦", "6弦標準"], "ベース": ["楽器", "撥弦", "4弦標準"],
                               "ウクレレ": ["楽器", "撥弦", "4弦標準", "小型"]}}
        self.assertEqual(tautology.holdout(corpus)["summary"]["unseen"], {"tested": 2, "fp": 0, "rate": 0.0})
        from test_ontautology import run_cli
        done = run_cli(ROOT / "tools/tautology.py", "holdout", "-", data=json.dumps(corpus, ensure_ascii=False))
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_holdout_on_the_example_names_the_closest_unseen_neighbour(self):
        corpus = concepts()
        found = tautology.holdout(corpus)
        rows = found["concepts"]
        self.assertEqual(list(rows), corpus["seeds"])
        # every seed has ≥2 similar concepts and attributes that really differ (open strings, base stats, spawning,
        # cap mark …), and the definition needs all but one key: no unseen concept is let in
        for seed in corpus["seeds"]:
            with self.subTest(seed=seed):
                self.assertEqual(rows[seed]["unseen"]["fp"], [])
        summary = found["summary"]
        self.assertEqual(summary["unseen"]["tested"], sum(r["unseen"]["tested"] for r in rows.values()))
        self.assertEqual(summary["unseen"]["fp"], sum(len(r["unseen"]["fp"]) for r in rows.values()))
        self.assertEqual(summary["unseen"]["rate"], round(summary["unseen"]["fp"] / summary["unseen"]["tested"], 4))
        # 🎭 every AND part is needed; an OR of shortest keys survives losing any one of them
        self.assertEqual(rows["ギター"]["masked"]["fn"], sorted(["ボディ", "弦楽器", "楽器"]))
        self.assertEqual(rows["ピカチュウ"]["masked"]["fn"], ["ポケモン"])
        from test_ontautology import run_cli
        self.assertEqual(run_cli(ROOT / "tools/tautology.py", "holdout", str(ROOT / "examples/concepts-20261115.json"), "ギター").returncode, 0)

    def test_only_the_shortest_keys_are_used(self):
        # With ウクレレ hidden, 中高音主体 ∧ 撥弦 also tells ギター from the rest; used as a key it would let ウクレレ in.
        corpus = {"similar": [["ギター", "ベース"], ["ギター", "ウクレレ"]],
                  "concepts": {"ギター": ["楽器", "撥弦", "中高音主体", "6弦標準"], "ベース": ["楽器", "撥弦", "低音主体", "4弦標準"],
                               "ウクレレ": ["楽器", "撥弦", "中高音主体", "4弦標準"], "ピアノ": ["楽器", "打弦", "中高音主体"]}}
        masked = tautology._without(corpus, "ウクレレ")
        keys = ot.define_concepts(masked, ["ギター"])["concepts"]["ギター"]["differentia"]["minimal_keys"]
        self.assertEqual(keys, [["6弦標準"], ["中高音主体", "撥弦"]])
        rule = tautology.rules(masked, "ギター")["definition"]
        self.assertNotIn("中高音主体", tautology.atoms(rule))
        self.assertFalse(tautology.holds(rule, set(corpus["concepts"]["ウクレレ"])))

    def test_masking_removes_the_concept_and_its_pairs_in_either_shape(self):
        corpus = {"similar": [["a", "b"], {"left": "b", "right": "c"}, {"source": "a", "target": "c"}],
                  "concepts": [{"id": "a", "elements": ["x"]}, {"id": "b", "elements": ["y"]}]}
        masked = tautology._without(corpus, "a")
        self.assertEqual(masked["concepts"], [{"id": "b", "elements": ["y"]}])
        self.assertEqual(masked["similar"], [{"left": "b", "right": "c"}])
        self.assertEqual(tautology._without({"concepts": {"a": ["x"], "b": ["y"]}}, "b")["concepts"], {"a": ["x"]})
        beside = tautology._without({"concepts": {"a": ["x"], "b": ["y"]}, "names": {"a": ["英名:A"], "b": ["英名:B"]}, "maybe": {"a": ["z"]}}, "a")
        self.assertEqual((beside["names"], beside["maybe"]), ({"b": ["英名:B"]}, {}))

    def test_counts_add_up_and_fn_refutes_the_converse(self):
        corpus = concepts()
        rule = ["AND", "弦楽器", "6弦標準", "存在しない要素"]
        found = tautology.judge(corpus, "ギター", rule)
        self.assertEqual((found["fn"], found["fp"], found["verdict"]), (["ギター"], [], "refuted"))
        self.assertEqual(found["propositions"]["converse"], False)
        self.assertEqual(found["tp"] + found["tn"] + len(found["fp"]) + len(found["fn"]), len(corpus["concepts"]))

    def test_unobserved_concepts_go_to_the_judgment_model(self):
        corpus = concepts()
        corpus["similar"].append({"left": "ギター", "right": "マンドリン", "basis": "hypothesis"})
        found = tautology.judge(corpus, "ギター", ["AND", "6弦標準"])
        self.assertEqual((found["to_model"], found["verdict"], found["basis"]), (["マンドリン"], "undecided", "hypothesis"))
        self.assertEqual(tautology.rules(corpus, "マンドリン")["to_model"], ["マンドリン"])

    def test_one_more_concept_can_refute_a_reversible_definition(self):
        corpus = concepts()
        rule = tautology.rules(corpus, "ギター")["definition"]
        corpus["concepts"]["ギターのコピー"] = list(corpus["concepts"]["ギター"]["elements"])  # the elements, not the ID
        self.assertEqual(tautology.judge(corpus, "ギター", rule)["fp"], ["ギターのコピー"])

    def test_de_morgan_is_proof_and_a_wrong_rewrite_has_a_counterexample(self):
        self.assertEqual(tautology.equivalent(["NOR", "a", "b"], ["AND", ["NOT", "a"], ["NOT", "b"]])["basis"], "proof")
        self.assertEqual(tautology.equivalent(["NAND", "a", "b"], ["OR", ["NOT", "a"], ["NOT", "b"]])["basis"], "proof")
        self.assertTrue(tautology.equivalent(["OR", "a", ["NOT", "a"]], ["AND"])["equivalent"])
        wrong = tautology.equivalent(["NAND", "a", "b"], ["NOR", "a", "b"])
        self.assertFalse(wrong["equivalent"])
        self.assertNotEqual(tautology.holds(["NAND", "a", "b"], set(wrong["counterexample"])),
                            tautology.holds(["NOR", "a", "b"], set(wrong["counterexample"])))
        with self.assertRaises(ValueError):
            tautology.equivalent(["AND", *(f"x{i}" for i in range(17))], ["AND"])

    def test_random_rules_rewritten_by_de_morgan_stay_equivalent(self):
        for seed in range(40):
            rng = random.Random(seed)
            a, b = random_rule(rng, list("pqrs")), random_rule(rng, list("pqrs"))
            with self.subTest(seed=seed):
                self.assertTrue(tautology.equivalent(["NOR", a, b], ["NOT", ["OR", a, b]])["equivalent"])
                self.assertTrue(tautology.equivalent(["NAND", a, b], ["NOT", ["AND", a, b]])["equivalent"])
                self.assertFalse(tautology.equivalent(a, ["NOT", a])["equivalent"])

    def test_a_definition_and_its_rewrite_judge_the_same(self):
        corpus = concepts()
        for seed in corpus["seeds"]:
            rule = tautology.rules(corpus, seed)["definition"]
            rewrite = ["NOT", ["NAND", rule]]
            with self.subTest(seed=seed):
                self.assertTrue(tautology.equivalent(rule, rewrite)["equivalent"])
                self.assertEqual(tautology.judge(corpus, seed, rewrite)["matched"], tautology.judge(corpus, seed, rule)["matched"])


class GuessTests(unittest.TestCase):
    """🎯 The guessing game: questions until one candidate is left, honest / forgetting / unseen."""

    def test_honest_play_reaches_every_concept_and_uses_attribute_questions(self):
        corpus = concepts()
        report = tautology.guess_report(corpus)
        honest = report["summary"]["honest"]
        self.assertEqual((honest["reached"], honest["games"]), (len(corpus["concepts"]), len(corpus["concepts"])))
        # finding the one takes no more than the yes / no estimate; confirming it is the question on top
        self.assertLessEqual(tautology.guess_report(corpus, sure=0)["summary"]["honest"]["mean_questions"], report["estimate"])
        self.assertIn("開放弦:?", [q["ask"] for q in report["honest"]["ギター"]["questions"]])
        self.assertEqual(tautology.guess_report(corpus), report)  # the same questions every time

    def test_forgetting_needs_tolerance_and_tolerance_costs_questions(self):
        corpus = concepts()
        strict, lenient = tautology.guess_report(corpus), tautology.guess_report(corpus, lies=1)
        self.assertLess(strict["summary"]["forget"]["rate"], 1.0)
        self.assertGreater(lenient["summary"]["forget"]["rate"], strict["summary"]["forget"]["rate"])
        self.assertGreater(lenient["summary"]["honest"]["mean_questions"], strict["summary"]["honest"]["mean_questions"])
        # answers the candidate failed count against its confidence: tolerance no longer lets an unseen one through
        self.assertGreaterEqual(lenient["summary"]["unseen"]["rate"], strict["summary"]["unseen"]["rate"])
        self.assertEqual(lenient["summary"]["unseen"]["rate"], 1.0)

    def test_an_unseen_target_should_end_in_no_guess(self):
        corpus = concepts()
        unseen = tautology.guess(corpus, "鮭", known=False)
        # the upper layer leaves the other two fish; 料理 is no dish either has, so no one is left to name
        self.assertEqual((unseen["guess"], unseen["reached"]), (None, True))
        self.assertEqual([(q["ask"], q["answer"]) for q in unseen["questions"]], [("区分:?", ["生き物"]), ("料理:?", ["ちゃんちゃん焼き", "ルイベ", "塩焼き"])])
        # without iPhone, iPad is left; asking what only iPad has (アクセサリ: Apple Pencil) tells it is not iPad
        unseen = tautology.guess(corpus, "iPhone", known=False)
        confirm = [q for q in unseen["questions"] if q.get("confirm")]
        self.assertEqual((unseen["guess"], [(q["ask"], q["answer"]) for q in confirm]), (None, [("アクセサリ:?", ["MagSafe"])]))
        self.assertTrue(tautology.guess(corpus, "ピアノ", known=True)["reached"])

    def test_confirming_stops_at_the_confidence_asked_for_and_misses_a_hidden_twin(self):
        corpus = concepts()
        for sure, confirms in ((0, []), (1, ["帽子のマーク:?"]), (2, ["帽子のマーク:?", "誕生:?"])):
            with self.subTest(sure=sure):  # each answer no one else gives is one whole identification
                game = tautology.guess(corpus, "ルイージ", sure=sure)
                self.assertEqual((game["guess"], game["confidence"], [q["ask"] for q in game["questions"] if q.get("confirm")]),
                                 ("ルイージ", sure, confirms))
        self.assertEqual(tautology.guess(corpus, "iPhone", known=False, sure=0)["guess"], "iPad")  # no confirming: the old trap
        # ミミッキュ unseen: ピカチュウ survives the failed タイプ answer (lies 1) and is the one left after 種族値とくこう;
        # that failure counts against it, and the confirming answer (種族値HP) fails too
        failed = tautology.guess(corpus, "ミミッキュ", known=False, lies=1)
        self.assertEqual((failed["guess"], failed["confidence"], failed["questions"][-1]["ask"]), (None, -1.52, "種族値HP:?"))
        # カフェイン含有 is shared only with the unseen エナジードリンク, so it looks like コーヒー's own: confirmed wrongly
        twin = tautology.guess(corpus, "エナジードリンク", known=False)
        self.assertEqual((twin["guess"], [q["ask"] for q in twin["questions"] if q.get("confirm")]), ("コーヒー", ["カフェイン含有"]))
        # forgetting the element it confirms with is the price: with no tolerance the right one is not named
        forgot = tautology.guess(corpus, "ルイージ", forget=["帽子のマーク:L"])
        self.assertEqual(forgot["guess"], None)

    def test_a_maybe_link_never_counts_against_a_candidate(self):
        corpus = {"concepts": {"a": ["x", "y"], "b": ["x"], "c": ["z"]}, "maybe": {"b": ["y"]}}
        game = tautology.guess(corpus, "a")
        self.assertIsNone(game["guess"])  # b might have y, so nothing tells a from b
        self.assertEqual(tautology.guess({**corpus, "maybe": {}}, "a")["guess"], "a")
        with self.assertRaises(ValueError):
            tautology.guess({**corpus, "maybe": {"ghost": ["y"]}}, "a")

    def test_maybe_links_are_hypotheses_in_the_graph_and_change_no_definition(self):
        corpus = concepts()
        graph = ot.concept_edges(corpus)
        maybe = [e for e in graph["edges"] if e.get("maybe")]
        self.assertEqual(sorted((e["source"], e["target"]) for e in maybe),
                         [("elem:アクセサリ:Sペン", "concept:Android"), ("elem:エレキ", "concept:ベース"),
                          ("elem:モバイル通信", "concept:iPad"),
                          ("elem:有名なリフ:Seven Nation Army", "concept:ベース"), ("elem:流通名:トラウトサーモン", "concept:スチールヘッド"),
                          ("elem:炭酸", "concept:カクテル"), ("elem:缶入り", "concept:C004-energy-drink"), ("elem:金属弦", "concept:C005-guitar"),
                          ("elem:黄色", "concept:ミミッキュ")])
        self.assertTrue(all(e["basis"] == "hypothesis" for e in maybe))
        self.assertEqual(ot.reach(graph["edges"], ["elem:金属弦"])["rows"], [])
        without = {k: v for k, v in corpus.items() if k != "maybe"}
        self.assertEqual(ot.define_concepts(corpus), ot.define_concepts(without))

    def test_command_line_guess(self):
        from test_ontautology import run_cli
        script, corpus_path = ROOT / "tools/tautology.py", str(ROOT / "examples/concepts-20261115.json")
        done = run_cli(script, "guess", corpus_path, "ギター", "ピカチュウ", "--lies", "1")
        self.assertEqual(done.returncode, 0, done.stderr)
        answer = json.loads(done.stdout)
        self.assertEqual((answer["lies"], answer["sure"], sorted(answer["honest"])), (1, 1.0, ["ギター", "ピカチュウ"]))
        sure = json.loads(run_cli(script, "guess", corpus_path, "ルイージ", "--sure", "2").stdout)
        self.assertEqual((sure["sure"], len([q for q in sure["honest"]["ルイージ"]["questions"] if q.get("confirm")])), (2.0, 2))
        self.assertEqual(run_cli(script, "guess", corpus_path, "存在しない").returncode, 1)

    def test_the_upper_layer_splits_the_groups_in_one_question(self):
        corpus = concepts()
        flat = {k: v for k, v in corpus.items() if k != "broader"}
        upper, plain = tautology.guess_report(corpus)["summary"]["honest"], tautology.guess_report(flat)["summary"]["honest"]
        self.assertEqual((upper["reached"], plain["reached"]), (upper["games"], plain["games"]))
        self.assertLess(upper["mean_questions"], plain["mean_questions"])  # 11 groups that shared nothing above their genus
        game = tautology.guess(corpus, "ギター")
        self.assertEqual((game["questions"][0]["ask"], game["questions"][0]["answer"]), ("区分:?", ["道具"]))
        # forgetting 楽器 is one wrong answer: what is above it is still known
        self.assertEqual(tautology.guess(corpus, "ギター", forget=["楽器"])["questions"][0]["answer"], ["道具"])


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


class WobbleTests(unittest.TestCase):
    """🔤 Shaking the names: notation folded as TalkCompress does, one character apart, names in the thing side."""

    def test_notation_folds_width_case_separators_kana_and_long_vowels(self):
        fold = tautology._notation
        self.assertEqual({fold(word) for word in ("ピカチュウ", "ピカチュー", "ぴかちゅう", "ﾋﾟｶﾁｭｳ")}, {"ぴかちゅう"})
        self.assertEqual(fold("メイド イン ワリオ"), fold("メイドインワリオ"))
        self.assertEqual((fold("ＩＰｈｏｎｅ"), fold("ルイージ"), fold("パーン")), ("iphone", "るいいじ", "ぱあん"))
        self.assertEqual(fold("ンー"), "んー")  # no vowel before the mark: it stays

    def test_one_character_apart(self):
        apart = tautology._one_apart
        self.assertTrue(all(apart(a, b) for a, b in (("まりお", "わりお"), ("ぴちゅう", "ぴかちゅう"), ("るいじ", "るいいじ"),
                                                    ("ab", "ba"), ("andriod", "android"))))  # two neighbours swapped is one slip too
        self.assertFalse(any(apart(a, b) for a, b in (("まりお", "まりお"), ("abcd", "ab"), ("abc", "cba"), ("abcd", "badc"))))

    def test_shaking_a_name_on_purpose(self):
        kinds = lambda word: {kind for kind, _ in tautology._shake(word)}
        self.assertEqual(dict(tautology._shake("ピカチュウ")[:2]), {"kana": "ぴかちゅう", "long": "ピカチュー"})
        self.assertEqual(kinds("Spider-Man"), {"width", "case", "space", "drop", "swap"})
        self.assertEqual(tautology._shake("鮭"), [])  # one character: nothing to drop or swap, no kana to swap
        self.assertTrue(all(variant != "ルイージ" for _, variant in tautology._shake("ルイージ")))

    def test_shaken_names_come_back_and_a_slip_onto_a_neighbour_is_only_counted(self):
        found = tautology.wobble(concepts())
        shaken = found["shaken"]
        # notation folds back every time and lands on no one else
        self.assertEqual((shaken["notation"]["rate"], shaken["notation"]["false_merges"]), (1.0, 0))
        self.assertTrue(all(shaken["kinds"][kind]["rate"] == 1.0 for kind in ("kana", "long", "width", "case", "space")))
        # one slip mostly comes back; ピカチュウ minus カ is ピチュー's notation, so the first answer is the neighbour
        self.assertGreater(shaken["typo"]["rate"], 0.9)
        self.assertIn({"concept": "ピカチュウ", "other": "ピチュー", "via": "ピカチュウ", "kind": "drop", "query": "ピチュウ"}, shaken["merges"])
        # a slip before ー changes how ー reads: エスカ(レ)ーション is two apart once folded, so it stays a miss
        self.assertIn({"concept": "エスカレーション", "via": "エスカレーション", "kind": "drop", "query": "エスカーション"}, shaken["misses"])
        self.assertEqual(found["summary"]["shaken"], {"notation": 1.0, "typo": shaken["typo"]["rate"]})
        self.assertEqual(found["words"], {})
        hit = tautology.wobble(concepts(), ["しゃけ"])["words"]["しゃけ"]
        self.assertEqual([(row["concept"], row["id"]) for row in hit["exact"]], [("鮭", "C006-salmon")])

    def test_the_example_shows_near_names_and_a_name_inside_the_thing_side(self):
        found = tautology.wobble(concepts())
        self.assertEqual([(row["pair"], row["similar"]) for row in found["near"]],
                         [(["ピカチュウ", "ピチュー"], True), (["マリオ", "ワリオ"], False), (["ルイージ", "ワルイージ"], True)])
        # the genus and the family are named after 鮭 (さけ); in Latin the genus is Oncorhynchus, with no name in it
        self.assertEqual((found["rephrase"], found["same"]), ({"鮭": ["サケ属", "サケ科"]}, []))

    def test_words_are_looked_up_on_three_tiers(self):
        words = tautology.wobble(concepts(), ["シャケ", "酒", "salmon", "ﾙｲｰｼﾞ", "るいじ"])["words"]
        pick = lambda word, tier: [(hit["concept"], hit["via"]) for hit in words[word][tier]]
        self.assertEqual(pick("シャケ", "notation"), [("鮭", "読み:しゃけ")])
        self.assertEqual(pick("酒", "exact"), [("鮭", "同音語:酒")])  # a word that sounds the same, not 鮭 itself
        self.assertEqual(pick("salmon", "notation"), [("鮭", "英名:Salmon")])
        self.assertEqual((pick("ﾙｲｰｼﾞ", "notation"), pick("ﾙｲｰｼﾞ", "near")), ([("ルイージ", "ルイージ")], [("ワルイージ", "ワルイージ")]))
        self.assertEqual(pick("るいじ", "near"), [("ルイージ", "ルイージ")])  # 類似 is one character from ルイージ

    def test_a_shared_form_splits_and_words_of_one_character_are_not_near(self):
        corpus = {"concepts": {"鮭": ["魚", "白鮭"], "酒": ["飲料"], "竹": ["植物"], "笹": ["植物"]},
                  "names": {"鮭": ["読み:さけ"], "酒": ["読み:さけ"]}}
        found = tautology.wobble(corpus)
        self.assertEqual(found["same"], [{"form": "さけ", "concepts": ["酒", "鮭"]}])
        self.assertEqual(found["near"], [])  # 竹 and 笹 are one character apart, as any two words of one character
        self.assertEqual(found["rephrase"], {"鮭": ["白鮭"]})
        from test_ontautology import run_cli
        script = ROOT / "tools/tautology.py"
        self.assertEqual(run_cli(script, "wobble", "-", data=json.dumps(corpus, ensure_ascii=False)).returncode, 2)
        clean = {**corpus, "concepts": {**corpus["concepts"], "鮭": ["魚"]}}
        done = run_cli(script, "wobble", "-", "さけ", data=json.dumps(clean, ensure_ascii=False))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([hit["concept"] for hit in json.loads(done.stdout)["words"]["さけ"]["exact"]], ["酒", "鮭"])

    def test_names_change_neither_definitions_nor_the_guessing_game(self):
        # asking for a name is calling the answer: the thing side alone defines and is asked about
        corpus = concepts()
        without = {k: v for k, v in corpus.items() if k != "names"}
        for seed in ("鮭", "ルイージ"):
            with self.subTest(seed=seed):
                self.assertEqual(tautology.rules(corpus, seed), tautology.rules(without, seed))
                self.assertEqual(tautology.guess(corpus, seed), tautology.guess(without, seed))


class CasesTests(unittest.TestCase):
    """📋 Observed cases (who said what, in which role) and the judgments people made, kept apart (#19)."""

    def test_the_example_cases_and_their_status(self):
        found = tautology.cases(concepts())
        rows = found["cases"]
        self.assertEqual({cid: row["status"] for cid, row in rows.items()},
                         {"K001-night-db": "confirmed", "K002-share-only": "disputed", "K003-shift-change": "pending", "K004-first-word": "judged"})
        self.assertEqual({k: rows["K001-night-db"]["candidate"][k] for k in ("concept", "id", "basis")},
                         {"concept": "エスカレーション", "id": "C011-escalation", "basis": "hypothesis"})
        # the manager called a share-only message an escalation; the concepts say status report: worth a look
        self.assertEqual((rows["K002-share-only"]["candidate"]["concept"], rows["K002-share-only"]["judgments"][0]["agrees"]), ("状況報告", False))
        self.assertEqual((rows["K003-shift-change"]["to_model"], rows["K003-shift-change"]["missing"]), (["引き継ぎメモを書く"], ["いつまで", "どう"]))
        # 連絡 alone fits all three: no candidate, and the person in charge decided
        self.assertEqual((rows["K004-first-word"]["candidate"], rows["K004-first-word"]["fits"]), (None, ["エスカレーション", "担当引き継ぎ", "状況報告"]))
        self.assertEqual(found["summary"]["roles"], {"cases": {"一次対応": 3, "夜勤": 1}, "judgments": {"課長": 1, "障害対応の責任者": 2}})
        self.assertNotIn("担当A", json.dumps(found["summary"], ensure_ascii=False))  # people are a record, not a count

    def test_judgments_change_no_definition_and_no_candidate(self):
        corpus = concepts()
        unjudged = {**corpus, "judgments": []}
        candidate = lambda c: {cid: row["candidate"] for cid, row in tautology.cases(c)["cases"].items()}
        self.assertEqual(candidate(corpus), candidate(unjudged))
        self.assertEqual(set(tautology.cases(unjudged)["summary"]) - {"roles"}, set(tautology.cases(corpus)["summary"]) - {"roles"})
        bare = {k: v for k, v in corpus.items() if k not in ("cases", "judgments")}
        self.assertEqual(ot.define_concepts(corpus), ot.define_concepts(bare))
        self.assertEqual(tautology.rules(corpus, "エスカレーション")["definition"], tautology.rules(bare, "エスカレーション")["definition"])
        for bad in ({"cases": [{"id": "x"}, {"id": "x"}]}, {"judgments": [{"case": "幽霊", "concept": "不安", "holds": True}]},
                    {"judgments": [{"case": "K001-night-db", "concept": "不安", "holds": "yes"}]},
                    {"judgments": [{"case": "K001-night-db", "concept": "未知", "holds": True}]}, {"cases": {}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                tautology.cases({**corpus, **bad})

    def test_stage_views(self):
        from test_ontautology import run_cli
        diagram = ROOT / "tools/knowledgegraph.py"
        corpus = ROOT / "examples/concepts-20261115.json"
        audit = run_cli(ROOT / "gh_audit/gh_audit.py", "audit", str(ROOT / "examples/audit-20261114.json"))
        self.assertEqual(audit.returncode, 0, audit.stderr)
        first = run_cli(diagram, "-", "--focus", "repo:myon-bioinformatics/Aoi", data=audit.stdout.decode())
        second = run_cli(diagram, str(corpus), "--focus", "elem:連絡")
        for result, relation in ((first, "belongsTo"), (second, "hasElement")):
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(relation, result.stdout.decode())
        cases = run_cli(ROOT / "tools/tautology.py", "cases", str(corpus), "--graph")
        self.assertEqual(cases.returncode, 2, cases.stderr)
        third = run_cli(diagram, "-", data=cases.stdout.decode())
        self.assertEqual(third.returncode, 0, third.stderr)
        for label in ("confirmed", "disputed", "pending", "judged", "hypothesis", "holds true", "to_model"):
            self.assertIn(label, third.stdout.decode())

    def test_command_line_cases(self):
        from test_ontautology import run_cli
        script = ROOT / "tools/tautology.py"
        done = run_cli(script, "cases", str(ROOT / "examples/concepts-20261115.json"))
        self.assertEqual(done.returncode, 2, done.stderr)  # one case is disputed
        corpus = concepts()
        corpus["judgments"] = [j for j in corpus["judgments"] if j["case"] != "K002-share-only"]
        done = run_cli(script, "cases", "-", data=json.dumps(corpus, ensure_ascii=False))
        self.assertEqual((done.returncode, json.loads(done.stdout)["summary"]["pending"]), (0, 2), done.stderr)


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

    def redis_matched(self, corpus, rule):
        """The concepts a rule lets in, by set algebra: AND=SINTER, OR=SUNION, NOT/NAND/NOR=SDIFF from all."""
        self.client.sadd("all", *corpus["concepts"])
        for name, elements in corpus["concepts"].items():
            for element in elements:
                self.client.sadd("has:" + element, name)
        counter = iter(range(1 << 30))

        def store(part):
            if isinstance(part, str):
                return "has:" + part
            key, op, inner = f"tmp:{next(counter)}", part[0], [store(p) for p in part[1:]]
            if op in ("AND", "NAND"):
                self.client.sinterstore(key, *inner) if inner else self.client.sunionstore(key, "all")
            else:
                self.client.sunionstore(key, *inner) if inner else self.client.delete(key)
            if op in ("NOT", "NAND", "NOR"):
                self.client.sdiffstore(key, "all", key)
            return key
        return sorted(self.client.smembers(store(rule)))

    def test_rule_judgements_agree_with_redis_set_algebra(self):
        for seed in range(30):
            corpus, features = random_corpus(seed)
            rng = random.Random(seed)
            for _ in range(5):
                rule = random_rule(rng, features)
                self.client.flushdb()
                with self.subTest(seed=seed, rule=rule):
                    self.assertEqual(tautology.judge(corpus, "c0", rule)["matched"], self.redis_matched(corpus, rule))

    def test_genus_and_differentia_agree_with_sinter_and_sdiff(self):
        corpus = concepts()
        defined = ot.define_concepts(corpus)["concepts"]
        for name, spec in corpus["concepts"].items():
            self.client.sadd("elem:" + name, *(spec["elements"] if isinstance(spec, dict) else spec))  # a seed carries its ID
        for pair in corpus["similar"]:
            left, right = pair["left"], pair["right"]
            with self.subTest(pair=(left, right)):
                self.assertEqual(sorted(self.client.sinter("elem:" + left, "elem:" + right)), defined[left]["genus"]["by_similar"][right]["common"])
                self.assertEqual(sorted(self.client.sdiff("elem:" + left, "elem:" + right)), defined[left]["differentia"]["vs_similar"][right]["only_target"])

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
