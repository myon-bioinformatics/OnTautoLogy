"""TOO の分類表と TOL のグラフ入力へ渡す投影。閉路検出は呼ばない。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from examples.sibling_format import (  # noqa: E402
    SCHEMA, TOL_COMMIT, TOO_COMMIT, classification, counts_agree, export_graph, project,
    relation_groups, render_relations_page, write_relations_site,
)
from gh_audit import gh_audit as ga  # noqa: E402

# TOO main 30c5ed689cb931bce3787e37056082ce8cb52b3d の弾ごとの対応。
# direction と excluded は taxontoy coverage が見る。holds false は表に無い。
ASSUMED = {
    "audit": {"dependsOn": "dependency", "duplicates": "overlap"},
    "concepts": {"narrower": "hierarchy", "similarTo": "similarity"},
    "cases": {
        "to_model": "unknown-element", "candidate": "hypothesis", "judgment": "judgment-record",
        "holds true": "affirmation",
    },
}


class ProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads((ROOT / "examples/audit-20261114.json").read_text(encoding="utf-8"))
        cls.corpus = json.loads((ROOT / "examples/concepts-20261115.json").read_text(encoding="utf-8"))
        cls.published = json.loads((ROOT / "examples/wave-profiles.json").read_text(encoding="utf-8"))

    def test_projection_keeps_audit_direction_and_drops_other_fields(self):
        graph = ga.audit([self.snapshot])
        exported = project(graph)
        self.assertEqual(exported["schema"], SCHEMA)
        self.assertEqual(project(exported), exported)
        self.assertTrue(all(set(node) <= {"id", "type", "name"} for node in exported["nodes"]))
        self.assertTrue(all(set(edge) == {"source", "target", "kind"} for edge in exported["edges"]))
        original = {(edge["source"], edge["target"]) for edge in graph["edges"] if edge["relation"] == "dependsOn"}
        copied = {(edge["source"], edge["target"]) for edge in exported["edges"] if edge["kind"] == "dependsOn"}
        flipped = {(edge["source"], edge["target"]) for edge in ga.edges_of(graph) if edge["kind"] == "dependsOn"}
        self.assertEqual(copied, original)
        self.assertNotEqual(copied, flipped)
        self.assertTrue(original)

    def test_assumed_table_matches_the_published_edge_counts(self):
        """#29 が固定した辺数を、TOL を起動せず投影と想定分類表だけで確かめる。"""
        table = classification(ASSUMED)
        for profile in ASSUMED:
            document = self.snapshot if profile == "audit" else self.corpus
            groups = relation_groups(export_graph(profile, document), table[profile])
            wave = self.published["waves"][profile]
            with self.subTest(profile=profile):
                self.assertEqual(groups["unclassified"], wave["unclassified_edges"])
                self.assertEqual(groups["classes"], {name: row["edges"] for name, row in wave["classes"].items()})

    def test_kind_wins_and_disagreement_is_rejected(self):
        graph = {"nodes": ["a"], "edges": [
            {"source": "a", "target": "b", "kind": "kept", "relation": "kept", "basis": "observed"},
        ]}
        exported = project(graph)
        self.assertEqual(exported["edges"], [{"source": "a", "target": "b", "kind": "kept"}])
        self.assertEqual({node["id"] for node in exported["nodes"]}, {"a", "b"})
        with self.assertRaises(ValueError):
            project({"edges": [{"source": "a", "target": "b", "kind": "one", "relation": "other"}]})
        with self.assertRaises(ValueError):
            project({"edges": [{"source": "a", "target": "b"}]})
        with self.assertRaises(ValueError):
            classification({"audit": {}})
        with self.assertRaises(ValueError):
            classification(["audit"])

    def test_counts_follow_tol_field_choice_without_comparing_cycles(self):
        groups = relation_groups(
            {"edges": [{"kind": "kind", "relation": "relation", "source": "a", "target": "b"}]},
            {"kind": "chosen", "relation": "other"},
        )
        self.assertEqual(groups, {"classes": {"chosen": 1, "other": 0}, "unclassified": 0})
        summary = {"classes": {"chosen": {"edges": 1, "sample_cycles": [["a", "b", "a"]]}, "other": {"edges": 0}},
                   "unclassified_edges": 0}
        self.assertTrue(counts_agree(groups, summary))
        summary["classes"]["chosen"]["edges"] = 2
        self.assertFalse(counts_agree(groups, summary))

    def test_taxontoy_table_does_not_treat_direction_as_a_profile(self):
        document = {
            "schema": "taxontoy-relations/1",
            "audit": {"dependsOn": "dependency"},
            "concepts": {"narrower": "hierarchy"},
            "cases": {"candidate": "hypothesis"},
            "direction": {"dependsOn": "forward", "narrower": "forward", "candidate": "forward"},
            "excluded": {"audit": ["observes"], "concepts": [], "cases": []},
        }
        self.assertEqual(set(classification(document)), {"audit", "concepts", "cases"})
        overlap = {**document, "excluded": {"audit": ["dependsOn"], "concepts": [], "cases": []}}
        with self.assertRaises(ValueError):
            classification(overlap)

    def test_page_keeps_old_columns_and_shows_added_metrics(self):
        added = {
            "edges": 2, "incident_nodes": 3, "multiple_sources": [], "sample_cycles": [],
            "degree": {"max_in": 1, "max_out": 1, "max_total": 2, "sources": 1, "sinks": 1},
            "weakly_connected_components": {"count": 1, "sizes": [3]},
            "independent_cycles": 0, "depth": None, "order_cycle": ["a", "b", "a"],
        }
        report = {"waves": {"audit": {
            "tool": {"name": "topontology", "version": "0.1.0"},
            "provenance": {
                "graph": {"path": "examples/tol-export/audit.json", "sha256": "ab" * 32},
                "classification": {"path": "too/otl-relations.json", "sha256": "cd" * 32},
                "profile": "audit",
            },
            "unclassified_edges": 4,
            "classes": {"dependency": added},
        }}}
        html = render_relations_page(report)
        self.assertIn("topontology 0.1.0", html)
        self.assertIn("ab" * 32, html)
        self.assertIn("不定（a → b → a）", html)
        self.assertIn(">0<", html)
        old = {"waves": {"audit": {"unclassified_edges": 0, "classes": {
            "dependency": {"edges": 1, "incident_nodes": 2, "multiple_sources": ["x"], "sample_cycles": []},
        }}}}
        previous = render_relations_page(old)
        self.assertIn(">1<", previous)
        self.assertIn(">—<", previous)

    def test_published_page_is_the_profile_table(self):
        html = render_relations_page(self.published)
        self.assertEqual((ROOT / "site/relations/index.html").read_text(encoding="utf-8"), html)
        self.assertEqual((ROOT / "site/relations/profiles.json").read_bytes(),
                         (ROOT / "examples/wave-profiles.json").read_bytes())
        self.assertIn(TOO_COMMIT, html)
        self.assertIn(TOL_COMMIT, html)
        self.assertIn("topontology", html)
        self.assertIn("独立閉路", html)
        self.assertIn("2,304", html)
        self.assertIn("K002-share-only", html)
        self.assertIn("食い違い", html)
        self.assertIn('href="relations/"', (ROOT / "site/index.html").read_text(encoding="utf-8"))

    def test_adapter_stays_out_of_the_core_and_pins_match_ci(self):
        for path in [ROOT / "ontautology.py", *(ROOT / "tools").glob("*.py"), *(ROOT / "gh_audit").glob("*.py")]:
            self.assertNotIn("sibling_format", path.read_text(encoding="utf-8"), path.name)
        workflow = (ROOT / ".github/workflows/wave-relations.yml").read_text(encoding="utf-8")
        pages = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(TOO_COMMIT, workflow)
        self.assertIn(TOL_COMMIT, workflow)
        self.assertNotIn("5c138352", workflow)
        self.assertNotIn("1d5ad6c", workflow)
        self.assertNotIn("workflow_dispatch", workflow)
        self.assertIn("examples/sibling_format.py page", pages)
        self.assertIn(TOO_COMMIT, readme)
        self.assertIn(TOL_COMMIT, readme)

    def test_cli_exports_and_rejects_a_broken_graph(self):
        script = str(ROOT / "examples/sibling_format.py")
        exported = subprocess.run(
            [sys.executable, "-S", script, "export", "cases", str(ROOT / "examples/concepts-20261115.json")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(exported.returncode, 0, exported.stderr)
        graph = json.loads(exported.stdout)
        self.assertEqual(graph["schema"], SCHEMA)
        self.assertTrue(all("markers" not in node for node in graph["nodes"]))
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "graph.json").write_text(exported.stdout, encoding="utf-8")
            (folder / "table.json").write_text(json.dumps({"cases": ASSUMED["cases"]}), encoding="utf-8")
            checked = subprocess.run(
                [sys.executable, "-S", script, "check", str(folder / "graph.json"), str(folder / "table.json"), "cases"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(json.loads(checked.stdout)["classes"]["affirmation"], 3)
            self.assertNotIn("negation", json.loads(checked.stdout)["classes"])
            broken = subprocess.run(
                [sys.executable, "-S", script, "check", str(folder / "table.json"), str(folder / "table.json"), "cases"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(broken.returncode, 1)
            write_relations_site(ROOT / "examples/wave-profiles.json", folder / "site")
            self.assertEqual((folder / "site/index.html").read_text(encoding="utf-8"),
                             (ROOT / "site/relations/index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
