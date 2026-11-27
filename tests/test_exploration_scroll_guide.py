import json
from pathlib import Path
import unittest

from tools.tautology import evaluate_nodes


class ExplorationScrollGuideTests(unittest.TestCase):
    def test_recommendation_changes_with_next_enemy_attack(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "exploration-scroll-guide.json"
        scenario = json.loads(path.read_text(encoding="utf-8"))

        result = evaluate_nodes(scenario, scenario["rule"], partial=True)
        rows = {row["id"]: row for row in result["nodes"]}
        self.assertEqual({key: row["verdict"] for key, row in rows.items()}, scenario["expected"])
        self.assertEqual(rows["check-intent"]["missing"], ["次が強攻撃"])
