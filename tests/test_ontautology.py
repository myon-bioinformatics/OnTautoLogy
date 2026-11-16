"""The generic core: walks, cycles, order, findings, keys, command line. Each test states a judgement. Standard library only."""
import contextlib
import io
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ontautology as ot  # noqa: E402


def run_cli(script, *args, data='{}', seed='1'):
    """``python -S script ARGS`` with ``data`` on stdin and a fixed hash seed; shared by every command-line test."""
    return subprocess.run([sys.executable, '-S', str(script), *args], input=data.encode('utf-8'), capture_output=True,
                          env={**os.environ, 'PYTHONHASHSEED': seed})


class JsonTransport(unittest.TestCase):
    script = Path(__file__).resolve().parent.parent / 'ontautology.py'

    def run_cli(self, *args, **options):
        return run_cli(self.script, *args, **options)

    def test_stdin_order_is_stable_across_seeds_and_input_order(self):
        edges = [e('before', 'a', 'b'), e('before', 'b', 'a'), e('before', 'b', 'c')]
        answers = []
        for seed in ('1', '2', '3'):
            p = self.run_cli('order', '-', data=json.dumps({'edges': edges, 'nodes': ['d','c','b','a']}), seed=seed)
            self.assertEqual(p.returncode, 2, p.stderr)
            answers.append(json.loads(p.stdout)); edges.reverse()
        self.assertEqual(answers, [dict(batches=[['d']], cycle=['a','b','a'], blocked=['a','b','c'])]*3)

    def test_stdin_reuse_and_invalid_json_are_input_errors(self):
        for args,data in [(('order','-'),'{'), (('reach','-','a'),'{"edges": [{"kind": "k"}]}')]:
            p=self.run_cli(*args,data=data)
            self.assertEqual(p.returncode,1);self.assertEqual(p.stdout,b'');self.assertIn(b'ontautology:',p.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node is optional')
    def test_node_transports_same_json_and_exit_code_without_shell(self):
        request=json.dumps({'edges':[e('before','a','b'),e('before','b','a')],'nodes':['d']})
        direct=self.run_cli('order','-',data=request)
        js="const {spawnSync}=require('node:child_process');const r=spawnSync(process.argv[1],['-S',process.argv[2],'order','-'],{input:require('node:fs').readFileSync(0)});if(r.error)throw r.error;process.stdout.write(r.stdout);process.stderr.write(r.stderr);process.exit(r.status??1)"
        p=subprocess.run(['node','-e',js,sys.executable,str(self.script)],input=request.encode(),capture_output=True)
        self.assertEqual(p.returncode,direct.returncode);self.assertEqual(json.loads(p.stdout),json.loads(direct.stdout))


def e(kind, source, target, **more):
    return {"kind": kind, "source": source, "target": target, **more}


CHAIN = [e("vendor", "tool:tool.py", "app:vendor/tool.py", lock="app:vendor.lock.json"),
         e("vendor", "app:vendor/tool.py", "relay:vendor/tool.py", lock="relay:vendor.lock.json"),
         e("tested_by", "app:vendor/tool.py", "app:tests/test_tool.py", basis="derived"),
         e("derived_from", "web:", "app:receipt.json", basis="hypothesis"),
         e("implies", "rule:narrow", "rule:wide", basis="proof")]


class Walks(unittest.TestCase):
    def test_a_change_reaches_direct_and_indirect_targets_with_the_edge_that_says_so(self):
        found = ot.reach(CHAIN, ["tool:tool.py"])
        by = {row["node"]: row for row in found["rows"]}
        self.assertEqual({k: v["depth"] for k, v in by.items()},
                         {"app:vendor/tool.py": 1, "relay:vendor/tool.py": 2, "app:tests/test_tool.py": 2})
        self.assertEqual(by["relay:vendor/tool.py"]["via"], ["tool:tool.py", "app:vendor/tool.py", "relay:vendor/tool.py"])
        self.assertEqual(by["relay:vendor/tool.py"]["edge"]["lock"], "relay:vendor.lock.json")

    def test_an_unrelated_or_unknown_start_asks_for_nothing(self):
        self.assertEqual(ot.reach(CHAIN, ["relay:vendor/tool.py"])["rows"], [])
        found = ot.reach(CHAIN, ["nowhere:x"])
        self.assertEqual((found["rows"], found["unknown"]), ([], ["nowhere:x"]))

    def test_a_guess_is_shown_but_decides_nothing_downstream(self):
        edges = CHAIN + [e("verified_by", "app:receipt.json", "app:report.md")]
        found = ot.reach(edges, ["web:"])
        self.assertEqual((found["rows"], [c["node"] for c in found["candidates"]]), ([], ["app:receipt.json"]))

    def test_why_walks_back_and_one_guess_keeps_the_chain_from_reading_as_proven(self):
        edges = [e("derived_from", "data", "judgement", basis="observed"), e("supports", "judgement", "verdict", basis="proof"),
                 e("derived_from", "rumour", "data", basis="hypothesis")]
        rows = ot.why(edges, "verdict")["rows"]
        self.assertEqual([(r["edge"]["source"], r["depth"], r["weakest"]) for r in rows],
                         [("judgement", 1, "proof"), ("data", 2, "observed"), ("rumour", 3, "hypothesis")])
        shallow = ot.why(edges, "verdict", depth=1)
        self.assertEqual((len(shallow["rows"]), shallow["cut"]), (1, True))  # says it stopped, not that nothing is there
        self.assertEqual(ot.why(edges, "rumour"), {"node": "rumour", "rows": [], "cut": False, "truncated": False})

    def test_walks_agree_with_brute_force_on_random_graphs(self):
        seed = random.SystemRandom().randrange(1 << 32)
        rng = random.Random(seed)
        for _ in range(60):
            names = [f"n{i}" for i in range(rng.randrange(2, 9))]
            edges = [e("k", rng.choice(names), rng.choice(names)) for _ in range(rng.randrange(0, 14))]
            start = rng.choice(names)
            closure, grew = {start}, True
            while grew:
                grew = False
                for edge in edges:
                    if edge["source"] in closure and edge["target"] not in closure:
                        closure.add(edge["target"])
                        grew = True
            self.assertEqual({r["node"] for r in ot.reach(edges, [start])["rows"]}, closure - {start}, f"seed={seed}")
            for row in ot.reach(edges, [start])["rows"]:  # every chain is a real path of that length
                self.assertEqual(len(row["via"]), row["depth"] + 1, f"seed={seed}")
                self.assertTrue(all(any(x["source"] == a and x["target"] == b for x in edges)
                                    for a, b in zip(row["via"], row["via"][1:])), f"seed={seed}")
            has_cycle = any(edge["source"] in {r["node"] for r in ot.reach(edges, [edge["target"]])["rows"]} | {edge["target"]}
                            for edge in edges)
            self.assertEqual(bool(ot.cycles(edges)), has_cycle, f"seed={seed}")
            self.assertEqual(ot.order(edges)["cycle"] is not None, has_cycle, f"seed={seed}")


class CyclesAndOrder(unittest.TestCase):
    def test_a_cycle_is_reported_and_the_rest_is_still_walked_and_ordered(self):
        edges = [e("derived_from", "a:x", "a:y"), e("derived_from", "a:y", "a:x"), e("derived_from", "b:p", "b:q")]
        self.assertEqual(ot.cycles(edges), [["a:x", "a:y", "a:x"]])
        self.assertEqual([r["node"] for r in ot.reach(edges, ["b:p"])["rows"]], ["b:q"])
        self.assertEqual([r["node"] for r in ot.reach(edges, ["a:x"])["rows"]], ["a:y"])
        self.assertEqual(ot.order(edges[2:]), {"batches": [["b:p"], ["b:q"]], "cycle": None, "blocked": []})
        found = ot.order(edges + [e("derived_from", "a:y", "a:z")])
        self.assertEqual(found["batches"], [["b:p"], ["b:q"]])  # the cycle stops itself and what waits on it, nothing else
        self.assertEqual((set(found["cycle"]), found["blocked"]), ({"a:x", "a:y"}, ["a:x", "a:y", "a:z"]))

    def test_order_puts_sources_first_keeps_same_numbers_apart_and_includes_lone_nodes(self):
        edges = [e("depends_on", "tool:#5", "app:#5"), e("depends_on", "app:#5", "app:#6")]
        self.assertEqual(ot.order(edges, nodes=["relay:#5"])["batches"], [["relay:#5", "tool:#5"], ["app:#5"], ["app:#6"]])


class Findings(unittest.TestCase):
    def test_bad_shape_unknown_basis_missing_reference_and_two_contents_are_found(self):
        edges = [e("vendor", "a", "b", lock="r", pin="1"), e("vendor", "a", "b", lock="r", pin="2"),
                 e("vendor", "a", "ghost"), {"kind": "vendor", "source": "a"}, e("vendor", "a", "b", lock="r2", basis="certain")]
        kinds = sorted(f["kind"] for f in ot.check(edges, nodes=["a", "b"]))
        self.assertEqual(kinds, ["basis", "duplicate-id", "missing-reference", "shape"])

    def test_the_same_statement_at_another_time_is_another_observation(self):
        edges = [e("observed_in", "run", "case", lock="r", observed_at="2026-10-01", state="failure"),
                 e("observed_in", "run", "case", lock="r", observed_at="2026-10-02", state="success")]
        self.assertEqual(ot.check(edges), [])  # the retry does not replace the first failure

    def test_ladder_counts_what_is_proven_and_what_is_only_seen(self):
        found = ot.ladder(CHAIN)
        self.assertEqual(found["basis"], {"hypothesis": 1, "derived": 1, "observed": 2, "proof": 1})
        self.assertEqual(found["kinds"]["implies"], {"edges": 1, "proof": 1})
        self.assertEqual(found["kinds"]["vendor"], {"edges": 2, "proof": 0})


class Keys(unittest.TestCase):
    def test_a_handle_becomes_a_key_only_while_it_is_complete_and_unique(self):
        rows = [{"id": "a", "run": 1, "job": "x"}, {"id": "b", "run": 1, "job": None}, {"id": "c", "run": 2, "job": "x"}]
        report = ot.key_report(rows, [("id",), ("run",), ("job",), ("run", "id")])
        self.assertEqual([report[k]["verdict"] for k in ("id", "run", "job", "run+id")], ["key", "collides", "incomplete", "key"])
        again = ot.key_report(rows + [dict(rows[0])], [("id",)])["id"]
        self.assertEqual((again["verdict"], again["repeats"], again["collisions"]), ("repeat", 1, 0))
        broken = ot.key_report(rows + [{"id": "a", "run": 9, "job": "y"}], [("id",)])["id"]  # one more entry demotes it
        self.assertEqual((broken["verdict"], broken["examples"]), ("collides", ["a"]))


class CommandLine(unittest.TestCase):
    def run_cli(self, data, *argv):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = ot.main([argv[0], str(path), *argv[1:]])
        return code, out.getvalue()

    def test_exit_codes_separate_answered_needs_a_look_and_input_error(self):
        graph = {"edges": CHAIN, "items": [{"id": "a"}, {"id": "a", "x": 1}]}
        code, out = self.run_cli(graph, "reach", "tool:tool.py")
        self.assertEqual((code, len(json.loads(out)["rows"])), (0, 3))
        self.assertEqual(self.run_cli(graph, "reach", "nowhere:x")[0], 2)
        self.assertEqual(self.run_cli(graph, "keys", "id")[0], 2)
        self.assertEqual(self.run_cli(graph, "ladder")[0], 0)
        self.assertEqual(self.run_cli({"edges": [e("k", "a", "b"), e("k", "b", "a")]}, "order")[0], 2)
        self.assertEqual(self.run_cli("{not json", "check")[0], 1)
        self.assertEqual(self.run_cli({"edges": [{"kind": "k"}]}, "reach", "a")[0], 1)
        with self.assertRaises(SystemExit):  # argparse: why needs a node
            self.run_cli(graph, "why")

    def test_output_is_the_same_for_the_same_input_in_any_edge_order(self):
        shuffled = list(reversed(CHAIN))
        self.assertEqual(self.run_cli({"edges": CHAIN}, "reach", "tool:tool.py")[1],
                         self.run_cli({"edges": shuffled}, "reach", "tool:tool.py")[1])
