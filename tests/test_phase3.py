"""第三弾の試作。安定 ID、属性名の言語と種別、観測と判断の分離、揺らしの往復。

第二弾の例（concepts-20261115.json）のグラフと定義は変えない。
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ontautology as ot  # noqa: E402
from tools import tautology  # noqa: E402

PHASE2 = ROOT / "examples/concepts-20261115.json"
PHASE3 = ROOT / "examples/concepts-20261117.json"
# 第二弾の例を concept_edges したグラフ。ID も往復も足す前のバイト列。
PHASE2_GRAPH = "944830d505dafaea2a9b6163f20757e150a678aa54e2c7bdf32027c4abbf156b"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def has_hangul(text):
    """ハングル音節（U+AC00–U+D7A3）が一つでもあるか。表記そのものはソースに置かない。"""
    return any(0xAC00 <= ord(ch) <= 0xD7A3 for ch in text)


class Phase2Unchanged(unittest.TestCase):
    """ID が無いコーパスは、これまでと同じグラフになる。"""

    def test_the_phase2_graph_and_snapshot_stay_put(self):
        corpus = load(PHASE2)
        graph = ot.concept_edges(corpus)
        blob = json.dumps(graph, ensure_ascii=False, sort_keys=True)
        self.assertEqual(hashlib.sha256(blob.encode()).hexdigest(), PHASE2_GRAPH)
        self.assertEqual(len(graph["nodes"]), 290)
        self.assertEqual(len(graph["edges"]), 568)
        self.assertNotIn("concept_id", next(node for node in graph["nodes"] if node["id"] == "concept:鮭"))
        self.assertTrue(all(node["type"] != "Judgment" for node in graph["nodes"]))

    def test_an_optional_id_does_not_change_the_definition(self):
        corpus = {"concepts": {"鮭": ["魚", "食用"], "酒": ["飲料"]}, "similar": [["鮭", "酒"]]}
        tagged = {"concepts": {"鮭": {"id": "C006-salmon", "notation": "salmon", "elements": ["魚", "食用"]},
                               "酒": ["飲料"]}, "similar": [["鮭", "酒"]]}
        self.assertEqual(ot.define_concepts(corpus), ot.define_concepts(tagged))
        graph = ot.concept_edges(tagged)
        nodes = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual(nodes["concept:C006-salmon"]["name"], "鮭")
        self.assertEqual(nodes["concept:C006-salmon"]["notation"], "salmon")
        self.assertIn("concept:酒", nodes)
        self.assertNotIn("concept_id", nodes["concept:酒"])
        with self.assertRaises(ValueError):
            ot.concept_edges({"concepts": {"鮭": {"id": "C006-salmon", "elements": ["魚"]},
                                           "酒": {"id": "C006-salmon", "elements": ["飲料"]}}, "similar": []})


class NamesAndIds(unittest.TestCase):
    """属性名が言語と種別になる。略語:Spidey はスパイダーマンで、別概念にはしない。"""

    def setUp(self):
        self.corpus = load(PHASE3)
        self.index = tautology.name_index(self.corpus)

    def labels(self, concept):
        return [row for row in self.index["labels"] if row["concept"] == concept]

    def test_spidey_is_the_abbreviation_of_the_same_concept(self):
        rows = self.labels("スパイダーマン")
        by_via = {row["via"]: row for row in rows}
        self.assertEqual(by_via["略語:Spidey"]["kind"], "abbr")
        self.assertEqual(by_via["英名:Spider-Man"]["lang"], "en")
        self.assertEqual(by_via["英名:Spider-Man"]["kind"], "pref")
        self.assertEqual(by_via["読み:すぱいだーまん"]["kind"], "variant")
        self.assertEqual(by_via["別名:スパイダー"]["kind"], "alt")
        self.assertEqual({row["id"] for row in rows}, {"C007-spider-man"})
        self.assertEqual(sorted(self.corpus["names"]["スパイダーマン"]),
                         ["別名:スパイダー", "略語:Spidey", "英名:Spider-Man", "読み:すぱいだーまん"])
        self.assertFalse(has_hangul(PHASE3.read_text(encoding="utf-8")))
        self.assertFalse(has_hangul((ROOT / "README.md").read_text(encoding="utf-8")))

    def test_japanese_names_are_not_merged_and_homophones_are_not_identity(self):
        self.assertEqual(self.index["ids"]["鮭"], "C006-salmon")
        self.assertEqual(self.index["ids"]["ギター"], "C005-guitar")
        self.assertNotEqual(self.index["ids"]["ギター"], self.index["ids"]["鮭"])
        self.assertEqual(self.index["ids"]["バットマン"], "バットマン")
        salmon = {row["via"] for row in self.labels("鮭")}
        self.assertIn("英名:Salmon", salmon)
        self.assertNotIn("同音語:酒", salmon)
        self.assertFalse(any(row["text"] == "エスカ" for row in self.index["labels"]))

    def test_lookup_of_the_abbreviation_stays_on_spider_man(self):
        found = tautology.wobble(self.corpus, ["Spidey", "Spidy", "Spider-Man"])["words"]
        self.assertEqual([(hit["concept"], hit["via"]) for hit in found["Spidey"]["exact"]],
                         [("スパイダーマン", "略語:Spidey")])
        self.assertEqual([(hit["concept"], hit["via"]) for hit in found["Spidy"]["near"]],
                         [("スパイダーマン", "略語:Spidey")])
        self.assertEqual(found["Spider-Man"]["exact"][0]["via"], "英名:Spider-Man")
        self.assertNotIn("Spidey", self.corpus["concepts"])
        self.assertNotEqual(self.index["ids"]["スパイダーマン"], self.index["ids"]["ピカチュウ"])

    def test_each_new_word_has_two_similars_and_the_old_definitions_stay(self):
        phase2 = load(PHASE2)
        for seed in ("ギター", "ピカチュウ", "鮭", "iPhone", "エナジードリンク", "ルイージ"):
            with self.subTest(seed=seed):
                self.assertEqual(tautology.rules(phase2, seed)["definition"], tautology.rules(self.corpus, seed)["definition"])
        for seed in ("スパイダーマン", "AIエージェント", "インシデント", "不安", "エスカレーション"):
            similars = [pair for pair in self.corpus["similar"] if seed in (pair["left"], pair["right"])]
            with self.subTest(seed=seed):
                self.assertGreaterEqual(len(similars), 2)
                self.assertIsNotNone(tautology.rules(self.corpus, seed)["definition"])
        self.assertEqual(self.corpus["seeds"],
                         ["iPhone", "ルイージ", "ピカチュウ", "エナジードリンク", "鮭", "ギター",
                          "スパイダーマン", "AIエージェント", "インシデント", "不安", "エスカレーション"])


class WatchAndJudgment(unittest.TestCase):
    """担当と役割はフィールド。判断は別記録で、外部候補は hypothesis のまま。"""

    def test_actor_and_role_are_fields_and_a_candidate_is_not_promoted(self):
        corpus = load(PHASE3)
        graph = ot.concept_edges(corpus)
        nodes = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual(ot.check(graph["edges"], list(nodes)), [])
        types = {node["type"] for node in nodes.values()}
        self.assertNotIn("Actor", types)
        self.assertNotIn("Role", types)
        speech = next(node for node in nodes.values() if node.get("statement") and node["type"] == "Observation")
        self.assertEqual((speech["actor"], speech["role"]), ("担当A", "記録者"))
        self.assertNotEqual(speech["actor"], speech["role"])
        self.assertIn("evidence", speech)
        self.assertEqual(speech["context"], "障害対応")
        judgment = next(node for node in nodes.values() if node["type"] == "Judgment")
        self.assertEqual((judgment["actor"], judgment["role"], judgment["basis"]), ("担当B", "判断者", "hypothesis"))
        self.assertNotEqual(judgment["id"], speech["id"])
        rests = [edge for edge in graph["edges"] if edge["kind"] == "restsOn"]
        self.assertTrue(rests)
        self.assertTrue(all(edge["basis"] == "hypothesis" and edge["target"] == speech["id"] for edge in rests))
        candidate = next(edge for edge in graph["edges"] if edge.get("candidate"))
        self.assertEqual((candidate["basis"], candidate["claimed_basis"], candidate["label_kind"]), ("hypothesis", "proof", "abbr"))
        self.assertEqual(ot.reach(graph["edges"], [candidate["source"]])["rows"], [])
        self.assertEqual(nodes["concept:C006-salmon"]["concept_id"], "C006-salmon")
        self.assertEqual(nodes["concept:バットマン"]["name"], "バットマン")


class RoundTripReport(unittest.TestCase):
    """揺らしの往復は、当てっこと同じ指標で、別概念に当たっても ID をまとめない。"""

    def metrics(self, report):
        return {key: report[key] for key in ("trials", "returned", "false_merges", "accuracy", "mean_questions", "max_questions", "rate")}

    def test_phase2_roundtrip_matches_the_recorded_baseline(self):
        found = tautology.wobble(load(PHASE2))
        self.assertEqual([(row["pair"], row["similar"]) for row in found["near"]],
                         [(["ピカチュウ", "ピチュー"], True), (["マリオ", "ワリオ"], False), (["ルイージ", "ワルイージ"], True)])
        self.assertEqual(self.metrics(found["roundtrip"]),
                         {"trials": 78, "returned": 78, "false_merges": 8, "accuracy": 0.8974,
                          "mean_questions": 2.79, "max_questions": 11, "rate": 1.0})
        self.assertEqual(self.metrics(found["roundtrip_seeds"]),
                         {"trials": 24, "returned": 24, "false_merges": 2, "accuracy": 0.9167,
                          "mean_questions": 4.0, "max_questions": 11, "rate": 1.0})
        ids = tautology.name_index(load(PHASE2))["ids"]
        self.assertNotEqual(ids["ピカチュウ"], ids["ピチュー"])
        self.assertNotEqual(ids["ルイージ"], ids["ワルイージ"])

    def test_eleven_words_return_and_the_two_near_misses_stay_separate(self):
        found = tautology.wobble(load(PHASE3))
        self.assertEqual(self.metrics(found["roundtrip_seeds"]),
                         {"trials": 44, "returned": 44, "false_merges": 2, "accuracy": 0.9545,
                          "mean_questions": 4.0, "max_questions": 11, "rate": 1.0})
        pairs = {(row["concept"], row["other"]) for row in found["roundtrip_seeds"]["examples"]}
        self.assertEqual(pairs, {("ピカチュウ", "ピチュー"), ("ルイージ", "ワルイージ")})
        ids = tautology.name_index(load(PHASE3))["ids"]
        self.assertNotEqual(ids["ピカチュウ"], ids["ピチュー"])
        self.assertNotEqual(ids["ルイージ"], ids["ワルイージ"])

    def test_guess_baselines_keep_their_settings(self):
        corpus = load(PHASE2)
        plain = tautology.guess_report(corpus, lies=0, sure=1)["summary"]
        tolerant = tautology.guess_report(corpus, lies=1, sure=1)["summary"]
        self.assertEqual((plain["honest"]["mean_questions"], plain["honest"]["max_questions"], plain["honest"]["rate"]),
                         (4.43, 8, 1.0))
        self.assertEqual((plain["forget"]["reached"], plain["unseen"]["reached"]), (210, 27))
        self.assertEqual((tolerant["honest"]["mean_questions"], tolerant["honest"]["max_questions"], tolerant["honest"]["rate"]),
                         (8.25, 15, 1.0))
        self.assertEqual((tolerant["forget"]["rate"], tolerant["unseen"]["rate"]), (1.0, 1.0))


class MaskAndCli(unittest.TestCase):
    def test_masking_drops_phase3_side_records(self):
        corpus = {"concepts": {"a": ["x"], "b": ["y"]}, "names": {"a": ["略語:A"]},
                  "labels": {"a": [{"text": "aa", "lang": "en", "kind": "abbr"}]},
                  "observations": [{"concept": "a", "actor": "担当A", "role": "記録者"}],
                  "candidates": [{"concept": "a", "text": "aaa", "lang": "en", "kind": "abbr", "basis": "observed"}]}
        masked = tautology._without(corpus, "a")
        self.assertEqual(masked["names"], {})
        self.assertEqual(masked["labels"], {})
        self.assertEqual(masked["observations"], [])
        self.assertEqual(masked["candidates"], [])

    def test_cli_reports_the_abbreviation_and_asks_for_a_look_when_a_name_is_in_the_thing_side(self):
        from test_ontautology import run_cli
        done = run_cli(ROOT / "tools/tautology.py", "wobble", str(PHASE3), "Spidey")
        self.assertEqual(done.returncode, 2, done.stderr.decode())
        answer = json.loads(done.stdout)
        self.assertEqual(answer["words"]["Spidey"]["exact"][0]["via"], "略語:Spidey")
        self.assertEqual(answer["roundtrip_seeds"]["rate"], 1.0)
        self.assertGreater(answer["roundtrip_seeds"]["false_merges"], 0)


if __name__ == "__main__":
    unittest.main()
