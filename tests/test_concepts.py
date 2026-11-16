"""第二弾 (phase 2) — concept similarity, genus/differentia definitions and roundtrip checks (ontautology.py)."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ontautology as ot  # noqa: E402
from gh_audit import gh_audit as ga  # noqa: E402
from test_ontautology import run_cli  # noqa: E402

EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "examples/concepts-20261115.json"
SCRIPT_PATH = Path(__file__).resolve().parent.parent / "ontautology.py"


def _load_example():
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


class ConceptDefinitionTests(unittest.TestCase):
    def test_six_example_pairs_derive_genus_differentia_and_unique_roundtrip(self):
        corpus = _load_example()
        defined = ot.define_concepts(corpus)
        self.assertEqual(defined["similar_pairs"], 6)
        self.assertEqual(defined["unknown"], [])
        concepts = defined["concepts"]
        expected_genus = {
            "ギター": ["フレット", "ボディ", "弦楽器", "撥弦", "楽器"],
            "ピカチュウ": ["でんきタイプ", "ねずみ分類", "ポケモン"],
            "鮭": ["サケ属", "サケ科", "遡河回遊魚", "食用", "魚類"],
            "iPhone": ["アプリ実行環境", "スマートフォン", "タッチパネル", "モバイル通信"],
            "エナジードリンク": ["カフェイン含有", "覚醒目的", "飲料"],
            "マリオ": ["オーバーオール", "ゲームキャラクター", "人間", "任天堂", "帽子", "配管工"],
        }
        for name, genus in expected_genus.items():
            with self.subTest(concept=name):
                entry = concepts[name]
                self.assertEqual(entry["status"], "unique")
                self.assertEqual(entry["basis"], "derived")
                self.assertEqual(entry["genus"]["all_common"], genus)
                self.assertEqual(entry["definition"]["roundtrip"], {"verdict": "unique", "matched": [name]})
                self.assertTrue(entry["definition"]["differentia"])

    def test_counterexample_breaks_roundtrip_and_forces_stronger_differentia(self):
        corpus = _load_example()
        before = ot.define_concepts(corpus, ["ギター"])["concepts"]["ギター"]
        self.assertIn(["6弦標準"], before["differentia"]["minimal_keys"])

        # Add a counterexample (Aoi-style): a 6-string bass shares 6弦標準 with ギター.
        with_counter = copy.deepcopy(corpus)
        with_counter["similar"].append({"left": "ギター", "right": "6弦ベース", "basis": "observed"})
        with_counter["concepts"]["6弦ベース"] = ["楽器", "弦楽器", "撥弦", "フレット", "ボディ", "6弦標準", "低音主体"]

        rt = ot.roundtrip_elements(with_counter, ["6弦標準"])
        self.assertEqual(rt["verdict"], "collides")
        self.assertEqual(rt["matched"], ["6弦ベース", "ギター"])

        after = ot.define_concepts(with_counter, ["ギター"])["concepts"]["ギター"]
        self.assertEqual(after["status"], "unique")
        self.assertNotIn(["6弦標準"], after["differentia"]["minimal_keys"])
        self.assertEqual(after["differentia"]["minimal_keys"], [["中高音主体"]])

    def test_subset_elements_report_unavoidable_collision_and_stay_hypothesis(self):
        corpus = _load_example()
        corpus["similar"].append(["ギター", "楽器の何か"])
        corpus["concepts"]["楽器の何か"] = ["楽器", "弦楽器", "撥弦"]
        entry = ot.define_concepts(corpus, ["楽器の何か"])["concepts"]["楽器の何か"]
        self.assertEqual(entry["status"], "collides")
        self.assertEqual(entry["basis"], "hypothesis")
        self.assertEqual(entry["differentia"]["unavoidable_collisions"], ["ギター", "ベース"])
        self.assertEqual(entry["definition"]["roundtrip"]["verdict"], "collides")

    def test_unobserved_similar_peer_or_hypothesis_link_prevents_derived_promotion(self):
        corpus = {
            "similar": [{"left": "ギター", "right": "ウクレレ", "basis": "observed"}],
            "concepts": {"ギター": ["楽器", "弦楽器", "6弦標準"]},
        }
        entry = ot.define_concepts(corpus, ["ギター"])["concepts"]["ギター"]
        self.assertEqual(entry["status"], "incomplete")
        self.assertEqual(entry["basis"], "hypothesis")
        self.assertEqual(entry["unobserved_similar"], ["ウクレレ"])
        self.assertIsNone(ot.define_concepts(corpus, ["ウクレレ"])["concepts"]["ウクレレ"]["elements"])

        guess_only = {
            "similar": [{"left": "ギター", "right": "ベース", "basis": "hypothesis"}],
            "concepts": {"ギター": ["楽器", "6弦"], "ベース": ["楽器", "4弦"]},
        }
        guessed = ot.define_concepts(guess_only, ["ギター"])["concepts"]["ギター"]
        self.assertEqual(guessed["status"], "unique")
        self.assertEqual(guessed["basis"], "hypothesis")

    def test_core_graph_projection_supports_check_reach_why_and_ladder(self):
        corpus = _load_example()
        projected = ot.concept_edges(corpus)
        nodes = [n["id"] for n in projected["nodes"]]
        edges = projected["edges"]
        self.assertEqual(ot.check(edges, nodes), [])
        reached = ot.reach(edges, ["elem:カフェイン含有"])
        self.assertEqual({r["node"] for r in reached["rows"]}, {"concept:エナジードリンク", "concept:コーヒー"})
        why = ot.why(edges, "concept:ギター", depth=1)
        self.assertTrue(any(r["edge"]["kind"] == "similarTo" and r["edge"]["source"] == "concept:ベース" for r in why["rows"]))
        counts = ot.ladder(edges)["basis"]
        self.assertGreater(counts["observed"], 0)
        self.assertGreater(counts["derived"], 0)


class WatchLayerTests(unittest.TestCase):
    """👀 The watch layer is the one phase 1 uses: Snapshot per corpus, Observation per observed concept."""

    def graph(self, corpus=None):
        found = ot.concept_edges(corpus or _load_example())
        return found, {n["id"]: n for n in found["nodes"]}

    def test_every_observed_concept_has_one_observation_from_the_one_snapshot(self):
        graph, nodes = self.graph()
        snapshots = [n for n in nodes.values() if n["type"] == "Snapshot"]
        self.assertEqual(len(snapshots), 1)
        observed = {e["target"]: e["source"] for e in graph["edges"] if e["kind"] == "observes"}
        self.assertEqual(sorted(observed), sorted(f"concept:{name}" for name in _load_example()["concepts"]))
        self.assertEqual({e["source"]: e["target"] for e in graph["edges"] if e["kind"] == "derived_from"},
                         {oid: snapshots[0]["id"] for oid in observed.values()})
        for edge in (e for e in graph["edges"] if e["kind"] == "hasElement"):
            with self.subTest(edge=(edge["source"], edge["target"])):
                self.assertEqual(edge["lock"], observed[edge["target"]])
        self.assertEqual(ot.check(graph["edges"], list(nodes)), [])

    def test_an_unobserved_concept_has_no_observation(self):
        corpus = _load_example()
        corpus["similar"].append({"left": "ギター", "right": "ウクレレ", "basis": "hypothesis"})
        graph, nodes = self.graph(corpus)
        self.assertIn("concept:ウクレレ", nodes)
        self.assertNotIn("concept:ウクレレ", {e["target"] for e in graph["edges"] if e["kind"] == "observes"})

    def test_the_snapshot_ignores_input_order_and_follows_content(self):
        corpus = _load_example()
        shuffled = {"similar": list(reversed(corpus["similar"])),
                    "concepts": {k: list(reversed(v)) for k, v in reversed(list(corpus["concepts"].items()))}}
        snapshot = lambda c: next(n["id"] for n in self.graph(c)[0]["nodes"] if n["type"] == "Snapshot")
        self.assertEqual(snapshot(corpus), snapshot(shuffled))
        changed = copy.deepcopy(corpus)
        changed["concepts"]["ギター"].append("12弦もある")
        self.assertNotEqual(snapshot(corpus), snapshot(changed))

    def test_captured_at_is_the_observation_time_and_must_carry_a_timezone(self):
        corpus = dict(_load_example(), captured_at="2026-11-16T18:00:00+09:00")
        graph, nodes = self.graph(corpus)
        self.assertEqual({n.get("observed_at") for n in nodes.values() if n["type"] == "Observation"}, {"2026-11-16T18:00:00+09:00"})
        self.assertTrue(all(e.get("observed_at") == "2026-11-16T18:00:00+09:00" for e in graph["edges"] if e["kind"] in ("observes", "hasElement")))
        self.assertNotIn("observed_at", next(n for n in self.graph()[1].values() if n["type"] == "Observation"))
        with self.assertRaises(ValueError):
            ot.concept_edges(dict(_load_example(), captured_at="2026-11-16T18:00:00"))

    def test_the_watch_layer_is_shared_with_phase_one(self):
        graph, nodes = self.graph()
        triples = {(nodes[e["source"]]["type"], e["kind"], nodes[e["target"]]["type"]) for e in graph["edges"]}
        watch = {triple for triple in triples if triple[0] == "Observation"}
        self.assertEqual(watch, {("Observation", "observes", "Concept"), ("Observation", "derived_from", "Snapshot")})
        self.assertEqual(ga.RELATIONS["derived_from"], (("Observation",), "Snapshot"))
        self.assertIn("Observation", ga.RELATIONS["observes"][0])
        self.assertIs(ga.digest, ot.digest)
        self.assertIs(ga.timestamp, ot.timestamp)


class ConceptCliTests(unittest.TestCase):
    def run_cli(self, *args, data="", seed="1"):
        return run_cli(SCRIPT_PATH, *args, data=data, seed=seed)

    def test_define_and_roundtrip_cli_exit_codes_and_determinism(self):
        corpus = _load_example()
        p_ok = self.run_cli("roundtrip", str(EXAMPLE_PATH), "カフェイン含有", "炭酸", "飲料")
        self.assertEqual(p_ok.returncode, 0, p_ok.stderr)
        self.assertEqual(json.loads(p_ok.stdout)["matched"], ["エナジードリンク"])

        p_col = self.run_cli("roundtrip", str(EXAMPLE_PATH), "カフェイン含有", "飲料")
        self.assertEqual(p_col.returncode, 2, p_col.stderr)
        self.assertEqual(json.loads(p_col.stdout)["verdict"], "collides")

        p_empty = self.run_cli("roundtrip", str(EXAMPLE_PATH), "存在しない要素")
        self.assertEqual(p_empty.returncode, 2, p_empty.stderr)
        self.assertEqual(json.loads(p_empty.stdout)["verdict"], "empty")

        p_unknown = self.run_cli("define", str(EXAMPLE_PATH), "未知の単語")
        self.assertEqual(p_unknown.returncode, 2, p_unknown.stderr)
        self.assertEqual(json.loads(p_unknown.stdout)["unknown"], ["未知の単語"])

        reversed_corpus = {
            "schema": corpus["schema"],
            "similar": list(reversed(corpus["similar"])),
            "concepts": {k: list(reversed(v)) for k, v in reversed(list(corpus["concepts"].items()))},
        }
        out_a = self.run_cli("define", "-", data=json.dumps(corpus, ensure_ascii=False), seed="1")
        out_b = self.run_cli("define", "-", data=json.dumps(reversed_corpus, ensure_ascii=False), seed="99")
        self.assertEqual(out_a.returncode, 0, out_a.stderr)
        self.assertEqual(out_b.returncode, 0, out_b.stderr)
        self.assertEqual(out_a.stdout, out_b.stdout)

    def test_core_cli_commands_read_concept_corpus_directly(self):
        p = self.run_cli("reach", str(EXAMPLE_PATH), "elem:カフェイン含有")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual({r["node"] for r in json.loads(p.stdout)["rows"]},
                         {"concept:エナジードリンク", "concept:コーヒー"})


if __name__ == "__main__":
    unittest.main()
