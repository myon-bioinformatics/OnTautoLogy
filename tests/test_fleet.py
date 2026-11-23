"""Fleet contracts through the parent's shared checks (vendor/fleet_check.py): lock, action pins, Node entry.

Node runs every tool through vendor/py_launch.cjs, so no per-tool .mjs/.cjs wrapper is kept here.
"""
import inspect
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import ontautology as ot  # noqa: E402
from gh_audit import gh_audit as ga  # noqa: E402
from vendor import fleet_check as fleet  # noqa: E402

EXAMPLE = ROOT / "examples/audit-20261114.json"
needs_node = unittest.skipIf(fleet.node() is None, "Node 26+ not available (set NODE)")


def launch(*args):
    """``node vendor/py_launch.cjs --env-var PYTHON ARGS`` with PYTHON set to this interpreter."""
    env = {**os.environ, "PYTHON": sys.executable, "PYTHONIOENCODING": "utf-8"}
    env.pop("PY_LAUNCH_ERROR_FORMAT", None)
    return subprocess.run([fleet.node(), str(ROOT / "vendor/py_launch.cjs"), "--env-var", "PYTHON", *args],
                          cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)


class FleetContracts(unittest.TestCase):
    def test_vendor_lock_matches_checked_in_bytes(self):
        onto_dir = Path("ontautology_shared/_onto")
        onto_sources = {(onto_dir / name).as_posix(): ("myon-bioinformatics/ONTO", upstream) for name, upstream in (
            ("ontology.py", "ontology.py"),
            ("knowledgegraph.py", "knowledgegraph.py"), ("LICENSE", "LICENSE"))}
        rows = fleet.check_lock(ROOT, sources={
            **onto_sources,
            "vendor/pythdragoras.py": ("myon-bioinformatics/PythDRagoras", "pythdragoras.py"),
            "vendor/PythDRagoras-LICENSE": ("myon-bioinformatics/PythDRagoras", "LICENSE"),
            "vendor/py_launch.cjs": (fleet.PARENT, "py_launch.cjs"),
            "vendor/fleet_check.py": (fleet.PARENT, "fleet_check.py"),
            "vendor/myon-bioinformatics-LICENSE": (fleet.PARENT, "LICENSE"),
            "vendor/cli_args.py": ("myon-bioinformatics/cli_args", "cli_args.py"),
            "vendor/cli_args-LICENSE": ("myon-bioinformatics/cli_args", "LICENSE"),
        })
        self.assertEqual(sorted(set(rows) - set(onto_sources)), sorted(str(p.relative_to(ROOT).as_posix()) for p in (ROOT / "vendor").iterdir()
                                              if p.is_file()))

    def test_standalone_core_copies_match_the_onto_source(self):
        from ontautology_shared._onto import knowledgegraph, ontology
        # ontautology.py is also distributed on its own, without any sibling modules.
        for standalone, upstream in ((ot.key_report, ontology.key_report),
                                     (ot.cycles, knowledgegraph.relation_cycles)):
            expected = inspect.getsource(upstream).replace("def " + upstream.__name__ + "(",
                                                          "def " + standalone.__name__ + "(", 1)
            self.assertEqual(inspect.getsource(standalone), expected)

    def test_workflow_actions_are_pinned_by_full_sha_with_version(self):
        self.assertTrue(fleet.check_actions(ROOT))

    def test_ci_provisions_node_before_tests(self):
        floor = None if os.name == "nt" else 26  # a bare "bash" on Windows is the WSL launcher
        job = fleet.workflow_job(ROOT, "test", node_floor=floor)
        self.assertLess(job.index("actions/setup-node@"), job.index("node_major="))
        self.assertLess(job.index("node_major="), job.index("-m unittest"))

    def test_no_per_tool_wrapper_and_readme_documents_the_direct_command(self):
        self.assertEqual(sorted(p.name for p in ROOT.glob("*.[cm]js")), [])
        self.assertIn("node vendor/py_launch.cjs -- ontautology.py", (ROOT / "README.md").read_text(encoding="utf-8"))


@needs_node
class NodeEntry(unittest.TestCase):
    def test_node_matches_python(self):
        cases = {"help": (["--help"], 0), "bogus": (["bogus"], 2), "not-a-graph": (["check", str(EXAMPLE)], 1)}
        for name, (args, expected) in cases.items():
            with self.subTest(case=name):
                via_node, via_python = fleet.node_parity(ROOT, "ontautology.py", "PYTHON", *args)
                self.assertEqual(via_python[0], expected, via_python[2])
                self.assertEqual(via_node, via_python)

    def test_concept_definitions_through_node_are_the_python_answer(self):
        corpus = str(ROOT / "examples/concepts-20261115.json")
        for tool, args in (("ontautology.py", ("define", corpus, "ギター")), ("tools/tautology.py", ("rules", corpus))):
            with self.subTest(tool=tool):
                via_node, via_python = fleet.node_parity(ROOT, tool, "PYTHON", *args)
                self.assertEqual(via_python[0], 0, via_python[2])
                self.assertEqual(via_node, via_python)

    def test_stdin_audit_through_node_is_the_python_answer(self):
        document = EXAMPLE.read_text(encoding="utf-8")
        via_node, via_python = fleet.node_parity(ROOT, "gh_audit/gh_audit.py", "PYTHON", "audit", "-", input=document)
        self.assertEqual(via_node, via_python)
        self.assertEqual(json.loads(via_node[1]), ga.audit([json.loads(document)]))

    def test_core_and_tools_are_callable_by_name_from_node(self):
        edges = [{"kind": "k", "source": "a", "target": "b", "basis": "proof"},
                 {"kind": "k", "source": "b", "target": "c", "basis": "hypothesis"}]
        for script, target, request, expected in (
                ("ontautology.py", "reach", [edges, ["a"]], ot.reach(edges, ["a"])),
                ("tools/tautology.py", "standing", [edges, "c"], {"node": "c", "level": "hypothesis", "edges": 2, "tautology": False}),
                ("tools/ontology.py", "identity", [[{"id": 1}, {"id": 2}], [["id"]]], {"key": ["id"], "report": ot.key_report([{"id": 1}, {"id": 2}], [("id",)])}),
                ("tools/knowledgegraph.py", "topological_order", [edges], {"order": ["a", "b", "c"], "cycle": None})):
            with self.subTest(script=script, target=target):
                done = launch("--call", target, "--", script, *(json.dumps(arg) for arg in request))
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(json.loads(done.stdout), json.loads(json.dumps(expected)))

    def test_vendored_launcher_keeps_its_contract(self):
        fleet.launcher_contract(ROOT)


if __name__ == "__main__":
    unittest.main()


# 🧰 Scripts: 📝 each one describes itself and ⌨️ one that reads sys.argv declares its arguments (argparse /
# cli_args). Read with ast, never run; the portfolio's script catalog reads the same facts.

class ScriptsDescribeThemselves(unittest.TestCase):
    def test_every_script_has_a_description_and_declared_arguments(self):
        fleet.check_scripts(fleet.repo_root(__file__))
