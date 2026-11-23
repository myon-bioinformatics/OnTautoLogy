"""TOO の分類表と TOL のグラフ入力へ渡す投影。閉路検出は呼ばない。"""
import dis
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TARGET = str((ROOT / "examples" / "sibling_format.py").resolve())
_SEEN_LINES = set()
_SEEN_ARCS = set()
_PENDING = {}
_COVER_DIR = Path(tempfile.mkdtemp(prefix="sibling-format-cover-"))
_JUMP_PREFIXES = (
    "POP_JUMP_IF_",
    "POP_JUMP_FORWARD_IF_",
    "POP_JUMP_BACKWARD_IF_",
    "JUMP_IF_",
)
_UNTRACED_OPS = {"CACHE", "END_FOR", "EXTENDED_ARG", "RESUME"}


def _conditional(opname):
    return opname == "FOR_ITER" or opname.startswith(_JUMP_PREFIXES)


def _qual(code):
    return f"{code.co_firstlineno}:{code.co_qualname}"


def _hook(frame, event, arg):
    if os.path.realpath(frame.f_code.co_filename) != _TARGET:
        return None
    frame.f_trace_opcodes = True
    if event == "line":
        _SEEN_LINES.add(frame.f_lineno)
    elif event == "opcode":
        code = frame.f_code
        key = id(frame)
        offset = frame.f_lasti
        pending = _PENDING.get(key)
        if pending is not None:
            _SEEN_ARCS.add((pending[0], pending[1], offset))
            del _PENDING[key]
        real = offset
        name = dis.opname[code.co_code[real]]
        while name == "EXTENDED_ARG":
            real += 2
            name = dis.opname[code.co_code[real]]
        if _conditional(name):
            _PENDING[key] = (_qual(code), real)
    elif event == "return":
        _PENDING.pop(id(frame), None)
    return _hook


sys.settrace(_hook)
from examples.sibling_format import (  # noqa: E402
    SCHEMA, SCHEMA_V1, SCHEMA_V2, SCHEMA_V3, TOL_COMMIT, TOO_COMMIT, classification, counts_agree,
    export_graph, main, project, relation_groups, render_relations_page, source_graph, tol_table,
    write_relations_site,
)
from gh_audit import gh_audit as ga  # noqa: E402

# TOO main c80f39cd9a5359403fdfce0fec9be4605594c8eb の弾ごとの対応。
# direction と excluded は taxontoy coverage が見る。holds false は表に無い。
# similarTo は mutual なので、TOL と同じく往復を畳んでから数える。
ASSUMED = {
    "audit": {"dependsOn": "dependency", "duplicates": "overlap"},
    "concepts": {"narrower": "hierarchy", "similarTo": "similarity"},
    "cases": {
        "to_model": "unknown-element", "candidate": "hypothesis", "judgment": "judgment-record",
        "holds true": "affirmation",
    },
}
ASSUMED_DIRECTIONS = {
    "dependsOn": "forward",
    "duplicates": "undirected",
    "narrower": "forward",
    "similarTo": "mutual",
    "to_model": "forward",
    "candidate": "forward",
    "judgment": "forward",
    "holds true": "forward",
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
            groups = relation_groups(
                export_graph(profile, document), table[profile], ASSUMED_DIRECTIONS)
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
        bare = render_relations_page({
            "waves": {"audit": {
                "provenance": {"graph": {"sha256": "ab"}, "classification": {"sha256": "cd"}},
                "unclassified_edges": 0,
                "classes": {"dependency": {
                    "edges": 1, "incident_nodes": 1, "multiple_sources": [], "sample_cycles": [],
                    "weakly_connected_components": {"sizes": [1]},
                }},
            }},
            "taxontoy": {"version": "0.2.0"},
        })
        self.assertIn(">ab<", bare)
        self.assertIn(">—<", bare)
        self.assertNotIn("TOO の被覆", bare)

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


def _stamp(since="2026-11-14", reason="recorded", relation=None):
    body = {"since": since, "reason": reason}
    if relation is not None:
        body["relation"] = relation
    return body


def _version(schema):
    document = {
        "schema": schema,
        "audit": {"dependsOn": "dependency", "duplicates": "overlap"},
        "concepts": {"narrower": "hierarchy", "similarTo": "similarity"},
        "cases": {"candidate": "hypothesis", "holds true": "affirmation"},
        "direction": {
            "candidate": "forward", "dependsOn": "forward", "duplicates": "undirected",
            "holds true": "forward", "narrower": "forward", "similarTo": "mutual",
        },
        "excluded": {"audit": ["blocks"], "concepts": [], "cases": []},
    }
    if schema in (SCHEMA_V2, SCHEMA_V3):
        document["properties"] = {
            "classes": {
                "dependency": {"acyclic": _stamp(since="2024-02-29")},
                "negation": {"acyclic": _stamp(since="2000-02-29", reason="leap")},
                "hierarchy": {
                    "acyclic": _stamp(since="2026-11-15", reason="no cycle"),
                    "transitive": _stamp(since="2026-01-31", reason="narrows"),
                },
                "overlap": {},
                "similarity": {"symmetric": _stamp(since="2026-11-15", reason="both ways")},
            },
            "relations": {
                "blocks": {"inverse_of": _stamp(relation="dependsOn")},
                "candidate": {"acyclic": _stamp(reason="open")},
                "dependsOn": {"inverse_of": _stamp(relation="blocks")},
                "duplicates": {"symmetric": _stamp(reason="either way")},
                "narrower": {"disjoint_with": [
                    _stamp(relation="blocks", since="2026-11-15"),
                    _stamp(relation="similarTo", since="2026-11-15", reason="distinct"),
                ]},
                "similarTo": {"transitive": _stamp(since="2026-11-15", reason="shared")},
            },
        }
    if schema == SCHEMA_V3:
        document["excluded"] = {
            "audit": [{"relation": "blocks", "kind": "out_of_scope", "since": "2026-11-21", "reason": "test"}],
            "concepts": [],
            "cases": [],
        }
        document["repos"] = {"vendor": "dependency"}
        document["direction"]["vendor"] = "forward"
        document["excluded"]["repos"] = []
        document["properties"]["relations"]["vendor"] = {"acyclic": _stamp(reason="copy")}
    return document


class RelationTableV2Tests(unittest.TestCase):
    def test_version_2_keeps_profiles_and_reads_declarations(self):
        found = classification(_version(SCHEMA_V2))
        self.assertEqual(set(found), {"audit", "concepts", "cases"})
        self.assertEqual(found["audit"]["dependsOn"], "dependency")
        self.assertNotIn("properties", found)
        self.assertEqual(classification(_version(SCHEMA_V1))["concepts"]["narrower"], "hierarchy")
        empty = _version(SCHEMA_V2)
        empty["properties"] = {"classes": {}, "relations": {}}
        self.assertEqual(set(classification(empty)), {"audit", "concepts", "cases"})

    def test_version_3_reads_object_exclusions_and_optional_repos(self):
        found = classification(_version(SCHEMA_V3))
        self.assertEqual(set(found), {"audit", "concepts", "cases"})
        self.assertEqual(found["audit"]["dependsOn"], "dependency")
        self.assertNotIn("repos", found)
        without_repos = _version(SCHEMA_V3)
        del without_repos["repos"]
        del without_repos["excluded"]["repos"]
        del without_repos["direction"]["vendor"]
        del without_repos["properties"]["relations"]["vendor"]
        self.assertEqual(set(classification(without_repos)), {"audit", "concepts", "cases"})
        down = tol_table(_version(SCHEMA_V3))
        self.assertEqual(down["schema"], SCHEMA_V2)
        self.assertEqual(down["excluded"]["audit"], ["blocks"])
        self.assertNotIn("repos", down)
        unchanged = _version(SCHEMA_V2)
        self.assertIs(tol_table(unchanged), unchanged)
        self.assertEqual(tol_table("raw"), "raw")

    def test_version_3_domain_and_range_declarations(self):
        document = _version(SCHEMA_V3)
        document["properties"]["relations"]["belongsTo"] = {
            "domain": {
                "types": ["File", "PullRequest"],
                "since": "2026-11-21",
                "reason": "source types",
            },
            "range": {
                "types": ["Repository"],
                "since": "2026-11-21",
                "reason": "target type",
            },
        }
        document["excluded"]["audit"].append({
            "relation": "belongsTo", "kind": "out_of_scope", "since": "2026-11-21", "reason": "typed",
        })
        self.assertEqual(classification(document)["audit"]["dependsOn"], "dependency")
        samples = []

        def add(message, mutate):
            body = _version(SCHEMA_V3)
            body["properties"]["relations"]["belongsTo"] = {
                "domain": {
                    "types": ["File"],
                    "since": "2026-11-21",
                    "reason": "ok",
                },
            }
            body["excluded"]["audit"].append({
                "relation": "belongsTo", "kind": "out_of_scope", "since": "2026-11-21", "reason": "typed",
            })
            mutate(body)
            samples.append((message, body))

        add("properties.relations.belongsTo.domain must be an object",
            lambda doc: doc["properties"]["relations"]["belongsTo"].__setitem__("domain", []))
        add("properties.relations.belongsTo.domain has unexpected field note",
            lambda doc: doc["properties"]["relations"]["belongsTo"]["domain"].__setitem__("note", "x"))
        add("properties.relations.belongsTo.domain missing since",
            lambda doc: doc["properties"]["relations"]["belongsTo"]["domain"].__delitem__("since"))
        add("properties.relations.belongsTo.domain invalid since",
            lambda doc: doc["properties"]["relations"]["belongsTo"]["domain"].__setitem__("since", "2026-02-31"))
        add("properties.relations.belongsTo.domain missing reason",
            lambda doc: doc["properties"]["relations"]["belongsTo"]["domain"].__delitem__("reason"))
        add("properties.relations.belongsTo.domain missing reason",
            lambda doc: doc["properties"]["relations"]["belongsTo"]["domain"].__setitem__("reason", ""))
        add("properties.relations.belongsTo.domain missing reason",
            lambda doc: doc["properties"]["relations"]["belongsTo"]["domain"].__setitem__("reason", " padded "))
        add("properties.relations.belongsTo.domain missing reason",
            lambda doc: doc["properties"]["relations"]["belongsTo"]["domain"].__setitem__("reason", 1))
        add("properties.relations.belongsTo.domain missing types",
            lambda doc: doc["properties"]["relations"]["belongsTo"]["domain"].__delitem__("types"))
        add("properties.relations.belongsTo.domain missing types",
            lambda doc: doc["properties"]["relations"]["belongsTo"]["domain"].__setitem__("types", []))
        add("properties.relations.belongsTo.domain.types[0] must be a non-empty string",
            lambda doc: doc["properties"]["relations"]["belongsTo"]["domain"].__setitem__("types", [""]))
        add("properties.relations.belongsTo.domain.types must be sorted and unique",
            lambda doc: doc["properties"]["relations"]["belongsTo"]["domain"].__setitem__(
                "types", ["PullRequest", "File"]))
        add("properties.relations.belongsTo.domain.types must be sorted and unique",
            lambda doc: doc["properties"]["relations"]["belongsTo"]["domain"].__setitem__(
                "types", ["File", "File"]))
        add("excluded.audit must be an array",
            lambda doc: doc["excluded"].__setitem__("audit", "blocks"))
        add("excluded.audit[1] must be a string or object",
            lambda doc: doc["excluded"]["audit"].__setitem__(1, 3))
        for message, document in samples:
            with self.subTest(message=message):
                with self.assertRaises(ValueError) as caught:
                    classification(document)
                self.assertEqual(str(caught.exception), message)

    def test_each_version_rejects_a_different_key_set(self):
        extra_v1 = _version(SCHEMA_V1)
        extra_v1["properties"] = {"classes": {}, "relations": {}}
        missing_v2 = _version(SCHEMA_V2)
        del missing_v2["properties"]
        extra_v2 = _version(SCHEMA_V2)
        extra_v2["note"] = "no"
        extra_v3 = _version(SCHEMA_V3)
        extra_v3["note"] = "no"
        for document, message in (
            (extra_v1, "taxontoy-relations/1 has unexpected keys"),
            (missing_v2, "taxontoy-relations/2 has unexpected keys"),
            (extra_v2, "taxontoy-relations/2 has unexpected keys"),
            (extra_v3, "taxontoy-relations/3 has unexpected keys"),
        ):
            with self.subTest(message=message):
                with self.assertRaises(ValueError) as caught:
                    classification(document)
                self.assertEqual(str(caught.exception), message)
                self.assertNotIn("\n", message)

    def test_unknown_schema_is_one_line(self):
        samples = {
            "taxontoy-relations/9": "unsupported table schema: taxontoy-relations/9",
            "a\nb": "unsupported table schema: a b",
            "": "unsupported table schema: empty",
            "   ": "unsupported table schema: empty",
            None: "unsupported table schema: NoneType",
        }
        for schema, message in samples.items():
            document = _version(SCHEMA_V1)
            document["schema"] = schema
            with self.subTest(schema=schema):
                with self.assertRaises(ValueError) as caught:
                    classification(document)
                self.assertEqual(str(caught.exception), message)
                self.assertEqual(str(caught.exception).splitlines(), [message])

    def test_bad_declarations_name_the_field(self):
        samples = []

        def add(message, mutate):
            document = _version(SCHEMA_V2)
            mutate(document)
            samples.append((message, document))

        add("properties must be an object", lambda doc: doc.__setitem__("properties", []))
        add("properties has unexpected keys", lambda doc: doc["properties"].__setitem__("extra", {}))
        add("properties.classes must be an object", lambda doc: doc["properties"].__setitem__("classes", []))
        add("properties.relations must be an object", lambda doc: doc["properties"].__setitem__("relations", []))
        add("properties.classes.nope unknown class", lambda doc: doc["properties"]["classes"].__setitem__("nope", {}))
        add("properties.classes.hierarchy must be an object",
            lambda doc: doc["properties"]["classes"].__setitem__("hierarchy", []))
        add("properties.classes.hierarchy unknown property reflexive",
            lambda doc: doc["properties"]["classes"]["hierarchy"].__setitem__("reflexive", _stamp()))
        add("class hierarchy symmetric and acyclic contradict",
            lambda doc: doc["properties"]["classes"]["hierarchy"].__setitem__("symmetric", _stamp()))
        add("properties.relations.ghost unknown relation",
            lambda doc: doc["properties"]["relations"].__setitem__("ghost", {}))
        add("properties.relations.dependsOn must be an object",
            lambda doc: doc["properties"]["relations"].__setitem__("dependsOn", []))
        add("properties.relations.dependsOn unknown property reflexive",
            lambda doc: doc["properties"]["relations"]["dependsOn"].__setitem__("reflexive", _stamp()))
        add("properties.relations.dependsOn.inverse_of unknown relation",
            lambda doc: doc["properties"]["relations"]["dependsOn"]["inverse_of"].__setitem__("relation", "ghost"))
        add("inverse pairs not mutually declared: blocks dependsOn",
            lambda doc: doc["properties"]["relations"].__delitem__("blocks"))
        add("properties.relations.narrower.disjoint_with must be a non-empty array",
            lambda doc: doc["properties"]["relations"]["narrower"].__setitem__("disjoint_with", "similarTo"))
        add("properties.relations.narrower.disjoint_with must be a non-empty array",
            lambda doc: doc["properties"]["relations"]["narrower"].__setitem__("disjoint_with", []))
        add("properties.relations.dependsOn.disjoint_with disjoint with itself",
            lambda doc: doc["properties"]["relations"]["dependsOn"].__setitem__(
                "disjoint_with", [_stamp(relation="dependsOn")]))
        add("properties.relations.dependsOn.disjoint_with unknown relation",
            lambda doc: doc["properties"]["relations"]["dependsOn"].__setitem__(
                "disjoint_with", [_stamp(relation="ghost")]))
        add("properties.relations.narrower.disjoint_with must be sorted and unique",
            lambda doc: doc["properties"]["relations"]["narrower"].__setitem__("disjoint_with", [
                _stamp(relation="similarTo"), _stamp(relation="blocks")]))
        add("properties.relations.narrower.disjoint_with must be sorted and unique",
            lambda doc: doc["properties"]["relations"]["narrower"].__setitem__("disjoint_with", [
                _stamp(relation="blocks"), _stamp(relation="blocks")]))
        add("relation duplicates symmetric and acyclic contradict",
            lambda doc: doc["properties"]["relations"]["duplicates"].__setitem__("acyclic", _stamp()))
        add("similarTo symmetric and acyclic contradict",
            lambda doc: doc["properties"]["relations"]["similarTo"].__setitem__("acyclic", _stamp()))
        add("properties.classes.dependency.acyclic missing since",
            lambda doc: doc["properties"]["classes"]["dependency"]["acyclic"].__delitem__("since"))
        add("properties.classes.dependency.acyclic invalid since",
            lambda doc: doc["properties"]["classes"]["dependency"]["acyclic"].__setitem__("since", "2026-02-31"))
        add("properties.classes.dependency.acyclic invalid since",
            lambda doc: doc["properties"]["classes"]["dependency"]["acyclic"].__setitem__("since", 20261114))
        add("properties.classes.dependency.acyclic invalid since",
            lambda doc: doc["properties"]["classes"]["dependency"]["acyclic"].__setitem__("since", "2026/11/14"))
        for bad_day in ("2026-00-10", "2026-13-01", "2026-11-00", "2023-02-29", "1900-02-29", "2026-04-31", "2026-11-31"):
            add("properties.classes.dependency.acyclic invalid since",
                lambda doc, day=bad_day: doc["properties"]["classes"]["dependency"]["acyclic"].__setitem__("since", day))
        add("properties.classes.dependency.acyclic missing reason",
            lambda doc: doc["properties"]["classes"]["dependency"]["acyclic"].__delitem__("reason"))
        add("properties.classes.dependency.acyclic missing reason",
            lambda doc: doc["properties"]["classes"]["dependency"]["acyclic"].__setitem__("reason", ""))
        add("properties.classes.dependency.acyclic missing reason",
            lambda doc: doc["properties"]["classes"]["dependency"]["acyclic"].__setitem__("reason", " padded "))
        add("properties.classes.dependency.acyclic missing reason",
            lambda doc: doc["properties"]["classes"]["dependency"]["acyclic"].__setitem__("reason", 1))
        add("properties.classes.dependency.acyclic has unexpected field note",
            lambda doc: doc["properties"]["classes"]["dependency"]["acyclic"].__setitem__("note", "x"))
        add("properties.relations.dependsOn.inverse_of must be an object",
            lambda doc: doc["properties"]["relations"]["dependsOn"].__setitem__("inverse_of", []))
        add("properties.relations.dependsOn.inverse_of missing relation",
            lambda doc: doc["properties"]["relations"]["dependsOn"]["inverse_of"].__delitem__("relation"))
        add("properties.relations.dependsOn.inverse_of missing relation",
            lambda doc: doc["properties"]["relations"]["dependsOn"]["inverse_of"].__setitem__("relation", ""))
        add("properties.relations.dependsOn.inverse_of missing relation",
            lambda doc: doc["properties"]["relations"]["dependsOn"]["inverse_of"].__setitem__("relation", " blocks "))
        add("properties.relations.dependsOn.inverse_of has unexpected field note",
            lambda doc: doc["properties"]["relations"]["dependsOn"]["inverse_of"].__setitem__("note", "x"))
        for message, document in samples:
            with self.subTest(message=message):
                with self.assertRaises(ValueError) as caught:
                    classification(document)
                self.assertEqual(str(caught.exception), message)
                self.assertNotIn("\n", message)

    def test_cli_accepts_version_2_and_rejects_unknown_schema(self):
        script = str(ROOT / "examples" / "sibling_format.py")
        graph = {"edges": [{"source": "a", "target": "b", "kind": "dependsOn"}]}
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
            table = folder / "table.json"
            table.write_text(json.dumps(_version(SCHEMA_V2)), encoding="utf-8")
            checked = subprocess.run(
                [sys.executable, "-S", script, "check", str(folder / "graph.json"), str(table), "audit"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(json.loads(checked.stdout)["classes"]["dependency"], 1)
            # Parent-process check so coverage sees the direction-dict branch in main.
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(["check", str(folder / "graph.json"), str(table), "audit"]), 0)
            self.assertEqual(json.loads(out.getvalue())["classes"]["dependency"], 1)
            schemaless = folder / "schemaless.json"
            schemaless.write_text(json.dumps({"audit": {"dependsOn": "dependency"}}), encoding="utf-8")
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(["check", str(folder / "graph.json"), str(schemaless), "audit"]), 0)
            self.assertEqual(json.loads(out.getvalue())["classes"]["dependency"], 1)
            table.write_text(json.dumps(_version("taxontoy-relations/9")), encoding="utf-8")
            rejected = subprocess.run(
                [sys.executable, "-S", script, "check", str(folder / "graph.json"), str(table), "audit"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
        self.assertEqual(rejected.returncode, 1)
        self.assertEqual(rejected.stderr.splitlines(), ["unsupported table schema: taxontoy-relations/9"])

    def test_mutations_of_the_real_source_are_killed(self):
        source = (ROOT / "examples" / "sibling_format.py").read_text(encoding="utf-8")

        def load(text):
            namespace = {
                "__name__": "sibling_format_mutant",
                "__file__": str(ROOT / "examples" / "sibling_format.py"),
            }
            exec(compile(text, "<sibling-format-mutant>", "exec"), namespace)  # noqa: S102
            return namespace["classification"]

        def killed(text, check):
            try:
                check(load(text))
            except Exception:
                return True
            return False

        drop = 'SCHEMA_V2 = "taxontoy-relations/2"\n'
        self.assertEqual(source.count(drop), 1)

        def accepts_v2(classify):
            found = classify(_version(SCHEMA_V2))
            if set(found) != {"audit", "concepts", "cases"} or found["cases"]["holds true"] != "affirmation":
                raise AssertionError(found)

        self.assertTrue(killed(source.replace(drop, 'SCHEMA_V2 = "taxontoy-relations/dropped"\n', 1), accepts_v2))
        accepts_v2(classification)

        since = "    return day <= last\n"
        self.assertEqual(source.count(since), 1)

        def rejects_bad_since(classify):
            bad = _version(SCHEMA_V2)
            bad["properties"]["classes"]["dependency"]["acyclic"]["since"] = "2026-02-31"
            try:
                classify(bad)
            except ValueError as error:
                if str(error) == "properties.classes.dependency.acyclic invalid since":
                    return
            raise AssertionError("bad since was accepted")

        self.assertTrue(killed(source.replace(since, "    return True\n", 1), rejects_bad_since))
        rejects_bad_since(classification)

        unknown = "        _unsupported(schema)\n"
        self.assertEqual(source.count(unknown), 1)

        def rejects_unknown(classify):
            document = _version(SCHEMA_V1)
            document["schema"] = "taxontoy-relations/9"
            try:
                classify(document)
            except ValueError as error:
                if str(error) == "unsupported table schema: taxontoy-relations/9":
                    return
            raise AssertionError("unknown schema was accepted")

        swapped = source.replace(unknown, "        return _read_version(document, SCHEMA_V1)\n", 1)
        self.assertTrue(killed(swapped, rejects_unknown))
        rejects_unknown(classification)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            graph = folder / "graph.json"
            table = folder / "table.json"
            graph.write_text('{"edges": []}', encoding="utf-8")
            table.write_text(json.dumps(_version(SCHEMA_V1)), encoding="utf-8")
            with patch("examples.sibling_format.classification", side_effect=TypeError("boom")):
                with self.assertRaises(TypeError):
                    main(["check", str(graph), str(table), "audit"])


_WRAPPER = r"""
import dis, os, runpy, sys
from pathlib import Path
script, dest = sys.argv[1], sys.argv[2]
sys.argv = [script, *sys.argv[3:]]
target = os.path.realpath(script)
lines, arcs, pending = set(), set(), {}
prefixes = ("POP_JUMP_IF_", "POP_JUMP_FORWARD_IF_", "POP_JUMP_BACKWARD_IF_", "JUMP_IF_")

def conditional(opname):
    return opname == "FOR_ITER" or opname.startswith(prefixes)

def qual(code):
    return f"{code.co_firstlineno}:{code.co_qualname}"

def hook(frame, event, arg):
    if os.path.realpath(frame.f_code.co_filename) != target:
        return None
    frame.f_trace_opcodes = True
    if event == "line":
        lines.add(frame.f_lineno)
    elif event == "opcode":
        code = frame.f_code
        key = id(frame)
        offset = frame.f_lasti
        prev = pending.get(key)
        if prev is not None:
            arcs.add((prev[0], prev[1], offset))
            del pending[key]
        real = offset
        name = dis.opname[code.co_code[real]]
        while name == "EXTENDED_ARG":
            real += 2
            name = dis.opname[code.co_code[real]]
        if conditional(name):
            pending[key] = (qual(code), real)
    elif event == "return":
        pending.pop(id(frame), None)
    return hook

sys.settrace(hook)
status = 0
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as exc:
    status = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
finally:
    sys.settrace(None)
    body = ["LINES", *(str(number) for number in sorted(lines)), "ARCS"]
    body.extend(f"{ident}\t{src}\t{dst}" for ident, src, dst in sorted(arcs))
    Path(dest).write_text("\n".join(body) + "\n", encoding="utf-8")
raise SystemExit(status)
"""


def _static_arcs(code):
    arcs = set()
    blocks = []

    def walk(block):
        blocks.append(block)
        for const in block.co_consts:
            if hasattr(const, "co_code"):
                walk(const)

    walk(code)
    for block in blocks:
        insns = [ins for ins in dis.get_instructions(block) if ins.opname not in {"CACHE", "EXTENDED_ARG"}]
        ident = _qual(block)
        for index, ins in enumerate(insns):
            if not _conditional(ins.opname):
                continue
            fall = next(item.offset for item in insns[index + 1:] if item.opname not in _UNTRACED_OPS)
            target = next(item.offset for item in insns if item.offset >= ins.argval and item.opname not in _UNTRACED_OPS)
            arcs.add((ident, ins.offset, fall))
            arcs.add((ident, ins.offset, target))
    return arcs


class ZCoverageTests(unittest.TestCase):
    def test_statements_and_branches_are_fully_executed(self):
        dest = _COVER_DIR / "cli.txt"
        cli = subprocess.run(
            [sys.executable, "-S", "-c", _WRAPPER, _TARGET, str(dest),
             "export", "cases", str(ROOT / "examples" / "concepts-20261115.json")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(cli.returncode, 0, cli.stderr)
        child_lines, child_arcs, section = set(), set(), None
        for line in dest.read_text(encoding="utf-8").splitlines():
            if line in {"LINES", "ARCS"}:
                section = line
                continue
            if section == "LINES":
                child_lines.add(int(line))
            elif section == "ARCS":
                ident, src, dst = line.split("\t")
                child_arcs.add((ident, int(src), int(dst)))
        self.assertTrue(child_lines, "CLI subprocesses did not record executed lines")
        source = Path(_TARGET).read_text(encoding="utf-8")
        total = len(source.splitlines())
        compiled = compile(source, _TARGET, "exec")
        executable = set()

        def walk(block):
            for _start, _end, lineno in block.co_lines():
                if lineno:
                    executable.add(lineno)
            for const in block.co_consts:
                if hasattr(const, "co_lines"):
                    walk(const)

        walk(compiled)
        seen_lines = set(_SEEN_LINES) | child_lines
        executed = executable & seen_lines
        excluded = set(range(1, total + 1)) - executable
        unexecuted = executable - seen_lines
        self.assertEqual(len(executed) + len(excluded) + len(unexecuted), total)
        arcs = _static_arcs(compiled)
        seen_arcs = set(_SEEN_ARCS) | child_arcs
        executed_arcs = arcs & seen_arcs
        excluded_arcs = set()
        unexecuted_arcs = arcs - seen_arcs
        self.assertEqual(len(executed_arcs) + len(excluded_arcs) + len(unexecuted_arcs), len(arcs))
        guard = next(number for number, line in enumerate(source.splitlines(), start=1) if line.startswith("if __name__"))
        self.assertIn(guard, child_lines)
        sys.stderr.write(
            f"statements executed={len(executed)} excluded={len(excluded)} "
            f"unexecuted={len(unexecuted)} total={total}\n"
            f"branches executed={len(executed_arcs)} excluded={len(excluded_arcs)} "
            f"unexecuted={len(unexecuted_arcs)} total={len(arcs)}\n"
        )
        if unexecuted or unexecuted_arcs:
            lines = source.splitlines()
            preview = "\n".join(f"{number}: {lines[number - 1]}" for number in sorted(unexecuted))
            arc_preview = "\n".join(repr(item) for item in sorted(unexecuted_arcs)[:40])
            self.fail(f"unexecuted lines {len(unexecuted)}\n{preview}\nunexecuted branches {len(unexecuted_arcs)}\n{arc_preview}")


if __name__ == "__main__":
    unittest.main()
