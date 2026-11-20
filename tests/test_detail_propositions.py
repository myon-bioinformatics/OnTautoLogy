import unittest

from examples.detail_propositions import ROOT, replay, run


class DetailPropositions(unittest.TestCase):
    def test_wave_two_matrix(self):
        report = run(ROOT / "examples/detail-propositions.json")
        self.assertFalse(report["mismatches"])
        self.assertGreaterEqual(len(report["questions"]), 16)
        self.assertEqual(report["questions"]["berry-projection"]["logical_form"], "tautology")
        self.assertEqual(report["questions"]["bass-note-names"]["logical_form"], "contingent")

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
