"""wave_relations と check_wave_report を、TOO と TOL の checkout なしで通す。

実物の CLI は CI の examples ジョブが固定コミットで実行する。ここはパスの切り方、
CLI の失敗、辺数が合わないときの停止、公開 JSON の回帰を見る。
"""
import json
import os
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


class PinnedTaxOntOyTests(unittest.TestCase):
    def test_wave_relations_runs_against_the_pinned_checkout(self):
        too_sha = "8621f2261d694af0de35e103ad2387872ca10b99"
        tol_sha = "d8880c9e55a0ce502dbf54a128bcaf471f0efc0e"
        workflow = (ROOT / ".github/workflows/wave-relations.yml").read_text(encoding="utf-8")
        self.assertIn(too_sha, workflow)
        self.assertIn(tol_sha, workflow)
        created = []
        try:
            for name, url, sha in (
                ("too", "https://github.com/myon-bioinformatics/TaxOntOy.git", too_sha),
                ("tol", "https://github.com/myon-bioinformatics/TopOntoLogy.git", tol_sha),
            ):
                link = ROOT / name
                if link.exists() or link.is_symlink():
                    head = subprocess.check_output(
                        ["git", "-C", str(link), "rev-parse", "HEAD"], text=True).strip()
                    self.assertEqual(head, sha, name)
                    continue
                repo = Path(tempfile.mkdtemp(prefix=f"otl-{name}-")) / name
                subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
                subprocess.run(
                    ["git", "-C", str(repo), "remote", "add", "origin", url],
                    check=True, capture_output=True, text=True)
                subprocess.run(
                    ["git", "-C", str(repo), "fetch", "--depth", "1", "origin", sha],
                    check=True, capture_output=True, text=True)
                subprocess.run(
                    ["git", "-C", str(repo), "checkout", "--detach", "FETCH_HEAD"],
                    check=True, capture_output=True, text=True)
                link.symlink_to(repo, target_is_directory=True)
                created.append(link)
            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join(["tol", "ontautology_shared/_onto"])
            result = subprocess.run(
                [sys.executable, "-S", "examples/wave_relations.py", "too/otl-relations.json"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["taxontoy"]["tool"], "taxontoy")
            self.assertEqual(report["taxontoy"]["version"], "0.2.0")
            self.assertTrue(report["taxontoy"]["ok"])
            self.assertEqual(report["taxontoy"]["errors"], [])
            published = json.loads((ROOT / "examples/wave-profiles.json").read_text(encoding="utf-8"))
            self.assertEqual(report, published)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "report.json"
                path.write_text(result.stdout, encoding="utf-8")
                checked = subprocess.run(
                    [sys.executable, "-S", str(ROOT / "examples/check_wave_report.py"), str(path)],
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                )
            self.assertEqual(checked.returncode, 0, checked.stderr + checked.stdout)
        finally:
            for link in created:
                if link.is_symlink():
                    link.unlink()


if __name__ == "__main__":
    unittest.main()
