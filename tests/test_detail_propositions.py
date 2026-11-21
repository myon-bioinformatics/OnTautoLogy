import json
import unittest

from examples.detail_propositions import ROOT, argument_variants, replay, run


class DetailPropositions(unittest.TestCase):
    def test_wave_two_matrix(self):
        report = run(ROOT / "examples/detail-propositions.json")
        self.assertFalse(report["mismatches"])
        self.assertGreaterEqual(len(report["questions"]), 16)
        self.assertEqual(report["questions"]["berry-projection"]["logical_form"], "tautology")
        self.assertEqual(report["questions"]["bass-note-names"]["logical_form"], "contingent")

    def test_substitution_keeps_source_and_other_arguments_fixed(self):
        patterns = run(ROOT / "examples/detail-propositions.json")["argument_patterns"]
        pika = patterns["ピカチュウが働きかける対象と手段"]
        self.assertIsNone(pika["baseline_markers"]["during"])
        rows = pika["variants"]
        self.assertEqual([row["changed_slot"] for row in rows], [None, 0, 0, 1, 1])
        self.assertEqual([[o["id"] for o in row["observations"] if o["verdict"] == "holds"] for row in rows],
                         [["金"], ["プラチナ"], ["ルビー"], [], []])
        self.assertTrue(rows[1]["mapped"])
        self.assertEqual(rows[1]["observations"][0]["missing"], ["revive"])
        self.assertFalse(rows[-1]["mapped"])
        self.assertIsNone(rows[-1]["values"][1])
        bass = patterns["開放弦の音名と実音"]["variants"]
        self.assertEqual([o["verdict"] for o in bass[-1]["observations"]], ["violated", "holds"])

    def test_wave_two_variants_preserve_sources_and_change_exactly_one_slot(self):
        groups = json.loads((ROOT / "examples/detail-propositions.json").read_text(encoding="utf-8"))
        editions = json.loads((ROOT / "examples/pokedex-editions.json").read_text(encoding="utf-8"))
        by_name = {entry["name"]: entry["editions"] for entry in editions.values()}
        for topic, pattern in run(ROOT / "examples/detail-propositions.json")["argument_patterns"].items():
            group = groups[topic]
            slots = group["argument_pattern"]["slots"]
            base = tuple(slot["values"][0] for slot in slots)
            sources = {}
            for label, obs in group["observations"].items():
                source = by_name[obs["concept"]][obs["edition"]] if "edition" in obs else obs
                sources[label] = source["source"]
            rows = pattern["variants"]
            self.assertEqual(len(rows), 1 + sum(len(s["values"]) - 1 for s in slots))
            self.assertEqual(len({row["values"] for row in rows}), len(rows))
            for row in rows:
                with self.subTest(topic=topic, values=row["values"]):
                    values = row["values"]
                    self.assertEqual(len(values), len(slots))
                    for value, slot in zip(values, slots):
                        self.assertIn(value, slot["values"])
                    changed = [i for i, value in enumerate(values) if value != base[i]]
                    self.assertEqual(changed, [] if row["changed_slot"] is None else [row["changed_slot"]])
                    self.assertCountEqual([(o["id"], o["source"]) for o in row["observations"]], sources.items())

    def test_same_source_distinguishes_unmapped_from_missing_evidence(self):
        patterns = run(ROOT / "examples/detail-propositions.json")["argument_patterns"]
        rows = {row["values"]: row for row in patterns["ピカチュウが働きかける対象と手段"]["variants"]}
        for values, mapped, rule in [
            (("弱った仲間", "電気"), True, "revive"),
            (("硬い木の実", "しっぽ"), False, None),
            (("硬い木の実", None), False, None),
        ]:
            with self.subTest(values=values):
                row = rows[values]
                gold, = (o for o in row["observations"] if o["id"] == "金")
                self.assertEqual((row["mapped"], row["rule"], gold["verdict"]), (mapped, rule, "unknown"))
                if mapped:
                    self.assertEqual(gold["missing"], [rule])
                else:
                    self.assertFalse(gold.get("missing"))

    def test_three_arguments_including_two_under_the_same_marker(self):
        slots = [{"marker": "with", "role": role, "values": ["A", "B"]} for role in ("相手", "道具", "素材")]
        pattern = {"predicate": "作業する", "slots": slots, "bindings": []}
        report = argument_variants(pattern, [{"id": "case"}], {"case": {"source": "case"}})
        self.assertEqual(len(report["baseline_markers"]["with"]), 3)
        self.assertEqual(len(report["variants"]), 4)
        pattern["bindings"] = [{"values": ["A", "B", "B"], "rule": "作業"}]
        with self.assertRaisesRegex(ValueError, "binding"):
            argument_variants(pattern, [], {})

    def test_losing_evidence_changes_the_verdict_but_not_the_expectation(self):
        questions = [{"id": "pitch", "text": "音高まで一致するか", "rule": "同音高", "expect": {"標準": "violated"}}]
        observation = {"concept": "ベース", "source": "調弦資料", "facts": {"同音高": False}}
        group = {"調弦": {"observations": {"標準": observation}, "questions": questions}}
        words = {"ベース": ("概念教材", "ベース", [])}
        self.assertFalse(replay(group, words, {})["mismatches"])
        observation["facts"].clear()
        result = replay(group, words, {})
        self.assertEqual(result["mismatches"], [["pitch", "標準"]])
        row, = result["questions"]["pitch"]["observations"]
        self.assertEqual((row["verdict"], row["missing"]), ("unknown", ["同音高"]))
