"""TOO の分類表と TOL のグラフ入力へ渡す投影。閉路検出は呼ばない。"""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from examples.sibling_format import (  # noqa: E402
    SCHEMA, TOL_COMMIT, TOO_COMMIT, classification, counts_agree, export_graph, main, project,
    relation_groups, render_relations_page, source_graph, write_relations_site,
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

    def test_rejected_tables_graphs_and_cli_paths(self):
        base = {
            "schema": "taxontoy-relations/1",
            "audit": {"dependsOn": "dependency"},
            "concepts": {"narrower": "hierarchy"},
            "cases": {"candidate": "hypothesis"},
            "direction": {"dependsOn": "forward", "narrower": "forward", "candidate": "forward"},
            "excluded": {"audit": ["observes"], "concepts": [], "cases": []},
        }
        for broken in (
            {}, [], {**base, "extra": 1},
            {**base, "direction": []}, {**base, "excluded": []},
            {**base, "excluded": {"audit": "observes", "concepts": [], "cases": []}},
            {**base, "excluded": {"audit": [""], "concepts": [], "cases": []}},
            {**base, "excluded": {"audit": [1], "concepts": [], "cases": []}},
            {**base, "direction": {"narrower": "forward", "candidate": "forward"}},
            {"": {"a": "b"}}, {1: {"a": "b"}}, {"audit": []}, {"audit": {"": "b"}},
            {"audit": {"a": ""}}, {"audit": {"a": 1}},
        ):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                classification(broken)
        for broken in (
            [], {}, {"edges": "no"}, {"edges": [], "nodes": {}}, {"edges": [], "nodes": [1]},
            {"edges": [], "nodes": [{"id": "a"}, {"id": "a"}]},
            {"edges": [], "nodes": [{"id": "a", "type": 1}]},
            {"edges": [], "nodes": [{"id": "a", "name": ""}]},
            {"edges": ["no"]}, {"edges": [{"source": "", "target": "b", "kind": "k"}]},
            {"edges": [{"source": "a", "target": "b", "kind": ""}]},
            {"edges": [{"source": "a", "target": "b", "relation": ""}]},
        ):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                project(broken)
        only_relation = project({"edges": [{"source": "a", "target": "b", "relation": "rel"}]})
        self.assertEqual(only_relation["edges"], [{"source": "a", "target": "b", "kind": "rel"}])
        groups = relation_groups(
            {"edges": [{"relation": "known", "source": "a", "target": "b"},
                       {"relation": "other", "source": "a", "target": "c"}]},
            {"known": "class"},
        )
        self.assertEqual(groups, {"classes": {"class": 1}, "unclassified": 1})
        agreed = {"classes": {"class": {"edges": 1}}, "unclassified_edges": 1}
        self.assertTrue(counts_agree(groups, agreed))
        self.assertFalse(counts_agree(groups, {"classes": {}, "unclassified_edges": 1}))
        self.assertFalse(counts_agree(groups, {"classes": {"class": {"edges": 1}}, "unclassified_edges": 0}))
        self.assertFalse(counts_agree(groups, {}))
        ready = {"schema": SCHEMA, "edges": []}
        concept_graph = {"schema": "ontautology-concept-graph/1", "edges": []}
        audit_graph = {"schema": "ontautology/1", "edges": []}
        self.assertIs(source_graph("audit", ready), ready)
        self.assertIs(source_graph("audit", audit_graph), audit_graph)
        self.assertIs(source_graph("concepts", ready), ready)
        self.assertIs(source_graph("concepts", concept_graph), concept_graph)
        self.assertIs(source_graph("cases", ready), ready)
        with self.assertRaises(ValueError):
            source_graph("audit", [])
        with self.assertRaises(ValueError):
            source_graph("nope", {})
        html = render_relations_page({
            "waves": {"audit": {
                "tool": {"name": "topontology"},
                "unclassified_edges": 0,
                "classes": {"dependency": {
                    "edges": 1, "incident_nodes": 1, "multiple_sources": [], "sample_cycles": [["a", "a"]],
                    "degree": {}, "weakly_connected_components": {"count": 1, "sizes": []},
                    "independent_cycles": None, "depth": None,
                }},
            }},
            "taxontoy": {"version": "0.1.0", "waves": {"audit": {"partition": {}}}},
        })
        self.assertIn("開いている", html)
        self.assertIn("（なし）", html)
        self.assertIn("不定<", html)
        self.assertEqual(render_relations_page({"waves": {}, "taxontoy": []}), render_relations_page({"waves": {}}))

        payload = {"schema": "ontautology/1", "nodes": [{"id": "a", "type": "T", "name": "n"}],
                   "edges": [{"source": "a", "target": "b", "relation": "dependsOn"}]}
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "in.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            output = folder / "out.json"
            table = folder / "table.json"
            table.write_text(json.dumps({"audit": {"dependsOn": "dependency"}}), encoding="utf-8")
            broken = folder / "broken.json"
            broken.write_text("{", encoding="utf-8")
            quiet = io.StringIO()
            with redirect_stdout(quiet), redirect_stderr(quiet):
                with patch("sys.stdin", io.StringIO(json.dumps(payload))):
                    self.assertEqual(main(["export", "audit", "-"]), 0)
                self.assertEqual(main(["export", "audit", str(source), "-o", str(output)]), 0)
                self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["schema"], SCHEMA)
                self.assertEqual(main(["check", str(output), str(table), "audit"]), 0)
                table.write_text(json.dumps({"cases": {"dependsOn": "dependency"}}), encoding="utf-8")
                self.assertEqual(main(["check", str(output), str(table), "audit"]), 1)
                self.assertEqual(main(["check", str(broken), str(table), "cases"]), 1)
                self.assertEqual(main(["check", str(folder / "missing.json"), str(table), "cases"]), 1)
                self.assertEqual(main(["page", str(ROOT / "examples/wave-profiles.json"), str(folder / "site")]), 0)
                self.assertTrue((folder / "site/index.html").is_file())
                program = ROOT / "examples/sibling_format.py"
                with patch.object(sys, "argv", ["sibling_format.py", "export", "audit", str(source), "-o", str(output)]):
                    with self.assertRaises(SystemExit) as caught:
                        exec(compile(program.read_text(encoding="utf-8"), str(program), "exec"),
                             {"__name__": "__main__", "__file__": str(program)})
                self.assertEqual(caught.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
