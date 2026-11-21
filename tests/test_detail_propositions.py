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
