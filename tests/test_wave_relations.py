"""wave_relations と check_wave_report を、TOO と TOL の checkout なしで通す。

実物の CLI は CI の examples ジョブが固定コミットで実行する。ここはパスの切り方、
CLI の失敗、辺数が合わないときの停止、公開 JSON の回帰を見る。
"""
import importlib.util
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
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


def load_vendored(name, relpath):
    """Load a vendored file by path under a repo-unique name (cli_args README: Loading a vendored copy)."""
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / relpath)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


run_cli = load_vendored("ontautology_cli_args", "vendor/cli_args.py").run_cli


class WaveRelationTests(unittest.TestCase):
    def test_omitted_table_uses_the_marker_or_the_short_name(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            anchor = root / "app" / "tool.py"
            anchor.parent.mkdir()
            anchor.write_text("", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TAXONTOY_ROOT", None)
                self.assertEqual(wr.default_classification(anchor), Path("too") / "otl-relations.json")
                table = root / "TaxOntOy" / "otl-relations.json"
                table.parent.mkdir()
                table.write_text("{}\n", encoding="utf-8")
                self.assertEqual(wr.default_classification(anchor), table.resolve())
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(wr, "report", side_effect=ValueError("分類表がない")):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = wr.main([])
        self.assertEqual(code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "wave_relations: 分類表がない\n")
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(wr, "report", return_value={"ok": True}):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = wr.main(["given.json"])
        self.assertEqual(code, 0)
        self.assertIn('"ok": true', stdout.getvalue())
        script = ROOT / "examples" / "wave_relations.py"
        missing = run_cli(
            script, "missing-classification.json",
            python_options=("-S",), cwd=ROOT,
        )
        self.assertEqual(missing.returncode, 1)
        self.assertNotIn("Traceback", missing.stderr)
        self.assertEqual(missing.stderr.count("\n"), 1)
        self.assertTrue(missing.stderr.startswith("wave_relations: "))

    def test_short_checkout_wins_over_a_sibling(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            short = folder / "too" / "taxontoy.py"
            short.parent.mkdir()
            short.write_text("", encoding="utf-8")
            sibling = folder / "TaxOntOy" / "taxontoy.py"
            sibling.parent.mkdir()
            sibling.write_text("", encoding="utf-8")
            _touch_marker = folder / "TaxOntOy" / "otl-relations.json"
            _touch_marker.write_text("{}\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TAXONTOY_ROOT", None)
                os.environ.pop("TOPONTOLOGY_ROOT", None)
                self.assertEqual(
                    wr.checkout_script("too", "TaxOntOy", "taxontoy.py", base=folder),
                    short,
                )
                short.unlink()
                self.assertEqual(
                    wr.checkout_script("too", "TaxOntOy", "taxontoy.py", base=folder),
                    sibling.resolve(),
                )
                sibling.unlink()
                _touch_marker.unlink()
                with self.assertRaises(wr.onto_path.RootError):
                    wr.checkout_script("too", "TaxOntOy", "taxontoy.py", base=folder)

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
        with tempfile.TemporaryDirectory() as directory, patch.object(wr, "EXPORTS", Path(directory) / "exports"):
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
        ok = run_cli(script, str(published), python_options=("-S",))
        self.assertEqual(ok.returncode, 0, ok.stderr)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            report = json.loads(published.read_text(encoding="utf-8"))
            report["waves"]["audit"]["classes"]["dependency"]["edges"] = 0
            path.write_text(json.dumps(report), encoding="utf-8")
            bad = run_cli(script, str(path), python_options=("-S",))
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("一致しません", bad.stderr + bad.stdout)


class PinnedTaxOntOyTests(unittest.TestCase):
    def test_wave_relations_runs_against_the_pinned_checkout(self):
        too_sha = "c80f39cd9a5359403fdfce0fec9be4605594c8eb"
        tol_sha = "d61c3fc6bc813966357dfc8f614217aaf50d2c15"
        workflow = (ROOT / ".github/workflows/wave-relations.yml").read_text(encoding="utf-8")
        self.assertIn(too_sha, workflow)
        self.assertIn(tol_sha, workflow)
        with tempfile.TemporaryDirectory(prefix="otl-wave-") as directory:
            workspace = Path(directory)
            shutil.copytree(ROOT / "examples", workspace / "examples",
                            ignore=shutil.ignore_patterns("tol-export", "__pycache__"))
            shutil.copytree(ROOT / "ontautology_shared", workspace / "ontautology_shared",
                            ignore=shutil.ignore_patterns("__pycache__"))

            def checkout(name, repository, sha):
                destination = workspace / name
                existing = ROOT / name
                if existing.exists() or existing.is_symlink():
                    head = subprocess.check_output(
                        ["git", "-C", str(existing), "rev-parse", "HEAD"], text=True).strip()
                    self.assertEqual(head, sha, name)
                    destination.symlink_to(existing, target_is_directory=True)
                    return
                subprocess.run(["git", "init", "--quiet", str(destination)], check=True)
                subprocess.run(["git", "fetch", "--quiet", "--depth=1",
                                f"https://github.com/myon-bioinformatics/{repository}.git", sha],
                               cwd=destination, check=True)
                subprocess.run(["git", "checkout", "--quiet", "--detach", sha], cwd=destination, check=True)

            with ThreadPoolExecutor(max_workers=2) as pool:
                too = pool.submit(checkout, "too", "TaxOntOy", too_sha)
                tol = pool.submit(checkout, "tol", "TopOntoLogy", tol_sha)
                too.result()
                tol.result()
            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(ROOT), env.get("PYTHONPATH"))))
            env["ONTO_ROOT"] = str(workspace / "ontautology_shared" / "_onto")
            env["OTL_ROOT"] = str(ROOT)
            result = run_cli(
                workspace / "examples/wave_relations.py", "too/otl-relations.json",
                python_options=("-S",), cwd=workspace, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["taxontoy"]["tool"], "taxontoy")
            self.assertEqual(report["taxontoy"]["version"], "0.6.0")
            self.assertTrue(report["taxontoy"]["ok"])
            self.assertEqual(report["taxontoy"]["errors"], [])
            published = json.loads((ROOT / "examples/wave-profiles.json").read_text(encoding="utf-8"))
            self.assertEqual(report, published)
            path = workspace / "report.json"
            path.write_text(result.stdout, encoding="utf-8")
            checked = run_cli(
                ROOT / "examples/check_wave_report.py", str(path),
                python_options=("-S",), cwd=workspace,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr + checked.stdout)


if __name__ == "__main__":
    unittest.main()
