import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from examples.relation_holdout import replay


class RelationHoldout(unittest.TestCase):
    def test_direction_abstention_and_hidden_record_independence(self):
        corpus = json.loads((ROOT / "examples/concepts-20261120.json").read_text(encoding="utf-8"))
        word = "AI搭載bot"
        clues = ["用途:自動応答", "入力から出力を推論"]
        result = replay(corpus, word, clues)
        stages = result["stages"]
        purpose = (word, "sharesPurposeWith", "C021-scripted-bot")
        application = (word, "applicationOf", "C014-ai-system")
        for stage, expected in zip(stages, [set(), {purpose}, {purpose, application}], strict=True):
            self.assertEqual({(r["source"], r["kind"], r["target"]) for r in stage["relations"]}, expected)
            self.assertEqual(stage["equivalence"], "undetermined")
        corpus["concepts"][word]["elements"] = ["poisoned"]
        corpus["names"][word] = ["英名:poisoned"]
        corpus["similar"].append({"left": word, "right": "コンピュータ"})
        self.assertEqual(replay(corpus, word, clues), result)
        control = replay(corpus, word, ["用途:自動応答", "応答方式:固定文の照合"])
        self.assertEqual([r["kind"] for r in control["stages"][-1]["relations"]], ["sharesPurposeWith"])
