"""wave_relations と check_wave_report を、TOO と TOL の checkout なしで通す。

実物の CLI は CI の examples ジョブが固定コミットで実行する。ここはパスの切り方、
CLI の失敗、辺数が合わないときの停止、公開 JSON の回帰を見る。
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from examples import wave_relations as wr  # noqa: E402
from examples.sibling_format import classification, relation_groups  # noqa: E402


class WaveRelationTests(unittest.TestCase):
    def test_paths_stay_relative_inside_the_checkout(self):
        self.assertEqual(wr.as_relative("too/otl-relations.json"), Path("too/otl-relations.json"))
        self.assertEqual(wr.as_relative((ROOT / "README.md").resolve()), Path("README.md"))
        outside = Path(tempfile.gettempdir()).resolve()
        self.assertEqual(wr.as_relative(outside), outside)

    def test_cli_returns_json_and_surfaces_a_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            ok = folder / "ok.py"
            ok.write_text("import json\nprint(json.dumps({'ok': True}))\n", encoding="utf-8")
            self.assertEqual(wr.run_cli([str(ok)]), {"ok": True})
            bad = folder / "bad.py"
            bad.write_text("import sys\nsys.stderr.write('nope\\n')\nraise SystemExit(1)\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "nope"):
                wr.run_cli([str(bad)])
            silent = folder / "silent.py"
            silent.write_text("raise SystemExit(1)\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "exited 1"):
                wr.run_cli([str(silent)])

    def test_report_stops_when_the_tol_counts_disagree(self):
        table = {
            "audit": {"dependsOn": "dependency"},
            "concepts": {"narrower": "hierarchy"},
            "cases": {"candidate": "hypothesis"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "table.json"
            path.write_text(json.dumps(table), encoding="utf-8")

            def matching(classification_path, profile):
                graph = json.loads((ROOT / wr.EXPORTS / f"{profile}.json").read_text(encoding="utf-8"))
                groups = relation_groups(graph, classification(table)[profile])
                return {"classes": {name: {"edges": count} for name, count in groups["classes"].items()},
                        "unclassified_edges": groups["unclassified"], "profile": profile}

            with patch.object(wr, "coverage_cli", return_value={"ok": True}) as covered, \
                    patch.object(wr, "summarize_cli", side_effect=matching):
                found = wr.report(path)
            self.assertEqual(covered.call_count, 1)
            self.assertEqual(set(found["waves"]), set(table))
            self.assertIn("K002-share-only", found["case_status"])
            with patch.object(wr, "coverage_cli", return_value={"ok": True}), \
                    patch.object(wr, "summarize_cli", return_value={"classes": {}, "unclassified_edges": -1}):
                with self.assertRaisesRegex(RuntimeError, "一致しません"):
                    wr.report(path)


class CheckWaveReportTests(unittest.TestCase):
    def test_published_profile_passes_and_a_changed_count_fails(self):
        script = ROOT / "examples/check_wave_report.py"
        published = ROOT / "examples/wave-profiles.json"
        ok = subprocess.run([sys.executable, "-S", str(script), str(published)], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            report = json.loads(published.read_text(encoding="utf-8"))
            report["waves"]["audit"]["classes"]["dependency"]["edges"] = 0
            path.write_text(json.dumps(report), encoding="utf-8")
            bad = subprocess.run([sys.executable, "-S", str(script), str(path)], capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("一致しません", bad.stderr + bad.stdout)


if __name__ == "__main__":
    unittest.main()
