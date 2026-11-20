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


def _reversed(spec):
    """A concept spec with its elements in reverse order (the object form keeps its id)."""
    return {**spec, "elements": list(reversed(spec["elements"]))} if isinstance(spec, dict) else list(reversed(spec))


def _node(name, spec):
    """The graph node of a concept: its stable id when it has one, else its name."""
    return f"concept:{spec['id'] if isinstance(spec, dict) and 'id' in spec else name}"


class ConceptDefinitionTests(unittest.TestCase):
    def test_porygon_human_ai_comparison(self):
        corpus = json.loads(EXAMPLE_PATH.with_name("concepts-20261120.json").read_text(encoding="utf-8"))
        defined = ot.define_concepts(corpus)["concepts"]
        for name in ("ポリゴン2", "人間", "AI"):
            self.assertEqual(defined[name]["definition"]["roundtrip"], {"verdict": "unique", "matched": [name]})
        from tools.tautology import wobble
        spellings = {"ポリゴン": "ポリゴン", "ポリゴン２": "ポリゴン2", "ポリゴンＺ": "ポリゴンZ"}
        hits = wobble(corpus, list(spellings))["words"]
        for word, expected in spellings.items():
            self.assertEqual({hit["concept"] for hit in hits[word]["exact"]}, {expected})
        for query, expected in [
            (["タイプ:ノーマル"], ["ポリゴン", "ポリゴン2", "ポリゴンZ"]),
            (["特性候補:トレース"], ["ポリゴン", "ポリゴン2"]),
            (["進化元:ポリゴン"], ["ポリゴン2"]),
            (["形態:人型"], ["人間", "人型模型", "ヒューマノイド"]),
            (["形態:人型", "助数詞:人"], ["人間"]),
            (["生物種", "助数詞:体"], []),
            (["生物種", "助数詞:台"], []),
            (["形態:人型", "助数詞:体"], ["人型模型"]),
            (["形態:人型", "助数詞:台"], ["ヒューマノイド"]),
            (["対象:手法"], ["機械学習"]),
            (["対象:計算機"], ["コンピュータ"]),
            (["手法例:機械学習", "実行基盤例:コンピュータ"], ["AI", "AI搭載bot"]),
            (["入力から出力を推論"], ["AI", "AI搭載bot"]),
            (["用途:自動応答"], ["定型応答bot", "AI搭載bot"]),
            (["用途:自動応答", "入力から出力を推論"], ["AI搭載bot"]),
        ]:
            with self.subTest(query=query):
                self.assertEqual(ot.roundtrip_elements(corpus, query)["matched"], sorted(expected))

    def test_grammatical_gender_stays_on_language_specific_words(self):
        graph = json.loads(EXAMPLE_PATH.with_name("lexical-gender.json").read_text(encoding="utf-8"))
        corpus = json.loads(EXAMPLE_PATH.with_name("concepts-20261120.json").read_text(encoding="utf-8"))
        human = "concept:" + corpus["concepts"]["人間"]["id"]
        self.assertEqual(ot.check(graph["edges"], graph["nodes"]), [])
        for word, gender in (("de:Mädchen", "neuter"), ("es:persona", "feminine"),
                             ("fr:personne", "feminine"), ("hi:व्यक्ति", "masculine"),
                             ("pt:pessoa", "feminine")):
            language = word.split(":")[0]
            rows = ot.reach(graph["edges"], ["lex:" + word])["rows"]
            self.assertEqual({(row["edge"]["kind"], row["node"]) for row in rows},
                             {("canReferTo", human), ("grammaticalGender", f"grammar:{language}:{gender}")})
        self.assertEqual(ot.reach(graph["edges"], [human])["rows"], [])

    def test_japanese_english_labels_roundtrip_in_both_directions(self):
        from tools.tautology import wobble
        corpus = json.loads(EXAMPLE_PATH.with_name("concepts-20261120.json").read_text(encoding="utf-8"))
        translations = {
            "ポリゴン": "Porygon", "ポリゴン2": "Porygon2", "ポリゴンZ": "Porygon-Z",
            "人間": "human", "人型模型": "human figure model", "ヒューマノイド": "humanoid robot",
            "AI": "artificial intelligence", "機械学習": "machine learning", "コンピュータ": "computer",
            "定型応答bot": "scripted bot", "AI搭載bot": "AI-powered bot",
        }
        self.assertEqual(set(translations), set(corpus["concepts"]))
        words = wobble(corpus, [*translations, *translations.values()])["words"]
        for ja, en in translations.items():
            with self.subTest(ja=ja, en=en):
                expected = {(ja, corpus["concepts"][ja]["id"])}
                for label in (ja, en):
                    self.assertEqual({(hit["concept"], hit["id"]) for hit in words[label]["exact"]}, expected)
                concept = words[en]["exact"][0]["concept"]
                self.assertEqual(concept, ja)
                concept = words[ja]["exact"][0]["concept"]
                self.assertEqual([s[3:] for s in corpus["names"][concept] if s.startswith("英名:")], [en])

    def test_person_in_the_individual_human_sense(self):
        from tools.tautology import wobble
        corpus = json.loads(EXAMPLE_PATH.with_name("concepts-20261120.json").read_text(encoding="utf-8"))
        words = wobble(corpus, ["person", "Person", "legal person"])["words"]
        for word, tier in [("person", "exact"), ("Person", "notation")]:
            self.assertEqual({h["id"] for h in words[word][tier]}, {"C013-human"})
        self.assertFalse(any(words["legal person"].values()))

    def test_example_pairs_derive_genus_differentia_and_unique_roundtrip(self):
        corpus = _load_example()
        defined = ot.define_concepts(corpus)
        self.assertEqual(defined["similar_pairs"], 31)
        self.assertEqual(defined["unknown"], [])
        concepts = defined["concepts"]
        expected_genus = {
            "ギター": ["ボディ", "弦楽器", "楽器"],  # with ウクレレ・三味線・バイオリン the common part narrows
            "ピカチュウ": ["ポケモン"],  # ミミッキュ is no electric type, and only ライチュウ is a mouse too
            "鮭": ["サケ属", "サケ科", "遡河回遊魚", "食用", "魚類"],
            "iPhone": ["アプリ実行環境", "タッチパネル"],  # iPad is no smartphone, and its mobile link is only maybe
            "エナジードリンク": ["飲料"],  # カクテル has no caffeine
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
        # the models, riffs and open strings still tell ギター apart on their own; 6弦標準 alone no longer does
        self.assertEqual(after["differentia"]["minimal_keys"],
                         [["代表モデル:ストラトキャスター"], ["代表モデル:レスポール"], ["有名なリフ:Seven Nation Army"],
                          ["有名なリフ:Smoke on the Water"], ["開放弦:EADGBE"]])

    def test_subset_elements_report_unavoidable_collision_and_stay_hypothesis(self):
        corpus = _load_example()
        corpus["similar"].append(["ギター", "楽器の何か"])
        corpus["concepts"]["楽器の何か"] = ["楽器", "弦楽器", "撥弦"]
        entry = ot.define_concepts(corpus, ["楽器の何か"])["concepts"]["楽器の何か"]
        self.assertEqual(entry["status"], "collides")
        self.assertEqual(entry["basis"], "hypothesis")
        self.assertEqual(entry["differentia"]["unavoidable_collisions"], ["ウクレレ", "ギター", "ベース", "三味線"])
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
        reached = ot.reach(edges, ["elem:カフェイン含有"])  # カクテル has none, but it is similar to one that has: look again
        self.assertEqual({r["node"] for r in reached["rows"]}, {"concept:C004-energy-drink", "concept:カクテル", "concept:コーヒー"})
        why = ot.why(edges, "concept:C005-guitar", depth=1)
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
        self.assertEqual(sorted(observed), sorted(_node(name, spec) for name, spec in _load_example()["concepts"].items()))
        self.assertEqual({e["source"]: e["target"] for e in graph["edges"] if e["kind"] == "derived_from"},
                         {oid: snapshots[0]["id"] for oid in observed.values()})
        for edge in (e for e in graph["edges"] if e["kind"] == "hasElement"):
            with self.subTest(edge=(edge["source"], edge["target"])):
                # seen elements rest on the observation; a maybe link only on the snapshot that wrote it down
                self.assertEqual(edge["lock"], snapshots[0]["id"] if edge.get("maybe") else observed[edge["target"]])
        self.assertEqual(ot.check(graph["edges"], list(nodes)), [])

    def test_an_unobserved_concept_has_no_observation(self):
        corpus = _load_example()
        corpus["similar"].append({"left": "ギター", "right": "マンドリン", "basis": "hypothesis"})
        graph, nodes = self.graph(corpus)
        self.assertIn("concept:マンドリン", nodes)
        self.assertNotIn("concept:マンドリン", {e["target"] for e in graph["edges"] if e["kind"] == "observes"})

    def test_the_snapshot_ignores_input_order_and_follows_content(self):
        corpus = _load_example()
        flip = lambda side: {k: _reversed(v) for k, v in reversed(list(corpus[side].items()))}
        shuffled = {"similar": list(reversed(corpus["similar"])), "concepts": flip("concepts"), "names": flip("names"), "broader": flip("broader")}
        snapshot = lambda c: next(n["id"] for n in self.graph(c)[0]["nodes"] if n["type"] == "Snapshot")
        self.assertEqual(snapshot(corpus), snapshot(shuffled))
        for side, name, element in (("concepts", "ギター", "12弦もある"), ("names", "ギター", "読み:ぎたあ"), ("broader", "楽器", "区分:人工物")):
            changed = copy.deepcopy(corpus)
            spec = changed[side][name]
            (spec["elements"] if isinstance(spec, dict) else spec).append(element)
            self.assertNotEqual(snapshot(corpus), snapshot(changed))
        changed = copy.deepcopy(corpus)
        changed["concepts"]["ギター"]["id"] = "C099-guitar"
        self.assertNotEqual(snapshot(corpus), snapshot(changed))

    def test_names_are_the_observed_name_side_and_define_nothing(self):
        corpus = _load_example()
        graph, nodes = self.graph(corpus)
        observed = {e["target"]: e["source"] for e in graph["edges"] if e["kind"] == "observes"}
        named = [e for e in graph["edges"] if e["kind"] == "hasName"]
        self.assertIn(("name:読み:しゃけ", "concept:C006-salmon"), {(e["source"], e["target"]) for e in named})
        self.assertTrue(all(e["basis"] == "observed" and e["lock"] == observed[e["target"]] and nodes[e["source"]]["type"] == "Name"
                            for e in named))
        self.assertEqual(ot.define_concepts(corpus), ot.define_concepts({k: v for k, v in corpus.items() if k != "names"}))
        # the name of a concept nobody has looked at yet rests on the snapshot that wrote it down
        corpus["similar"].append(["ギター", "マンドリン"])
        corpus["names"]["マンドリン"] = ["英名:Mandolin"]
        graph, nodes = self.graph(corpus)
        edge = next(e for e in graph["edges"] if e["kind"] == "hasName" and e["target"] == "concept:マンドリン")
        self.assertEqual(nodes[edge["lock"]]["type"], "Snapshot")
        for bad in ({"names": []}, {"names": {"幽霊": ["英名:Ghost"]}}, {"names": {"ギター": "英名:Guitar"}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ot.concept_edges({**_load_example(), **bad})

    def test_the_upper_layer_is_drawn_from_above_and_changes_no_definition(self):
        corpus = _load_example()
        graph, nodes = self.graph(corpus)
        narrower = {(e["source"], e["target"]): e for e in graph["edges"] if e["kind"] == "narrower"}
        edge = narrower[("elem:区分:道具", "elem:楽器")]
        self.assertEqual((edge["basis"], nodes[edge["lock"]]["type"]), ("observed", "Snapshot"))
        # from above, reach touches everything under it: every fictional one, and nothing real
        under = {r["node"] for r in ot.reach(graph["edges"], ["elem:実在:しない"])["rows"]}
        self.assertTrue({"concept:C003-pikachu", "concept:C002-luigi", "concept:C007-spider-man"} <= under)
        self.assertFalse({"concept:C005-guitar", "concept:C006-salmon"} & under)
        self.assertEqual(ot.define_concepts(corpus), ot.define_concepts({k: v for k, v in corpus.items() if k != "broader"}))
        for bad in ({"a": ["b"], "b": ["a"]}, {"a": ["a"]}, {"a": "b"}, []):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ot.concept_edges({**corpus, "broader": bad})

    def test_a_stable_id_names_the_node_and_changes_no_definition(self):
        corpus = _load_example()
        graph, nodes = self.graph(corpus)
        # the ID does not depend on the language: the name hangs off it, and the node keeps the name to read
        self.assertEqual(nodes["concept:C006-salmon"]["name"], "鮭")
        self.assertNotIn("concept:鮭", nodes)
        self.assertIn(("name:英名:Salmon", "concept:C006-salmon"), {(e["source"], e["target"]) for e in graph["edges"] if e["kind"] == "hasName"})
        self.assertIn(("concept:C006-salmon", "concept:サクラマス"), {(e["source"], e["target"]) for e in graph["edges"] if e["kind"] == "similarTo"})
        plain = {**corpus, "concepts": {k: v["elements"] if isinstance(v, dict) else v for k, v in corpus["concepts"].items()}}
        self.assertEqual(ot.define_concepts(corpus), ot.define_concepts(plain))
        # one ID per concept: two concepts cannot share one, and an ID cannot be another concept's name
        for bad in ({"鮭": {"id": "X", "elements": ["魚"]}, "酒": {"id": "X", "elements": ["飲料"]}},
                    {"鮭": {"id": "サクラマス", "elements": ["魚"]}, "サクラマス": ["魚"]},
                    {"鮭": {"id": "", "elements": ["魚"]}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ot.concept_edges({"concepts": bad})

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
            "concepts": {k: _reversed(v) for k, v in reversed(list(corpus["concepts"].items()))},
        }
        out_a = self.run_cli("define", "-", data=json.dumps(corpus, ensure_ascii=False), seed="1")
        out_b = self.run_cli("define", "-", data=json.dumps(reversed_corpus, ensure_ascii=False), seed="99")
        # ピアノ has no similar concept (a near miss), so define answers and asks for a look (2).
        self.assertEqual(out_a.returncode, 2, out_a.stderr)
        self.assertEqual(out_b.returncode, 2, out_b.stderr)
        self.assertEqual(out_a.stdout, out_b.stdout)

    def test_core_cli_commands_read_concept_corpus_directly(self):
        p = self.run_cli("reach", str(EXAMPLE_PATH), "elem:カフェイン含有")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual({r["node"] for r in json.loads(p.stdout)["rows"]},
                         {"concept:C004-energy-drink", "concept:カクテル", "concept:コーヒー"})


if __name__ == "__main__":
    unittest.main()
