"""Each test states a judgement the graph must get right, not how it is computed. Standard library only."""
import contextlib
import copy
import io
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ontautology as ot  # noqa: E402


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


# ---------------------------------------------------------------- cross-repository audit

def row(number, **changes):
    return {"repository": "demo", "number": number, "state": "調査中", "head_sha": "a" * 40,
            "base_sha": "b" * 40, "main_sha": "b" * 40, "base": "main", "merged": False,
            "mergeable": None, "contained_in_main": None, "files": [], "dependencies": [], **changes}


def snapshot(*rows, at="2026-11-14T14:00:00Z"):
    return {"schema": "integration-audit/3", "captured_at": at, "records": list(rows)}


class TemporalGraphTests(unittest.TestCase):
    def test_overlap_is_repository_scoped_and_not_a_conflict(self):
        graph = ot.audit([snapshot(row(1, files=["README.md"]), row(2, files=["README.md"]),
                                row(3, repository="other", files=["README.md"]))])
        overlaps = [e for e in graph["edges"] if e["relation"] == "overlapsWith"]
        self.assertEqual(len(overlaps), 1)
        self.assertIn("not a conflict", overlaps[0]["basis"])
        self.assertEqual(overlaps[0]["target"], "pr:myon-bioinformatics/demo#2")

    def test_merge_and_main_containment_are_independent(self):
        graph = ot.audit([snapshot(row(1, merged=True), row(2, contained_in_main=True))])
        self.assertEqual(ot.plan(graph)["order"], ["pr:myon-bioinformatics/demo#1"])
        obs = [n for n in graph["nodes"] if n["type"] == "Observation"]
        self.assertIsNone(obs[0]["mergeable"])

    def test_missing_dependency_blocks_transitively(self):
        graph = ot.audit([snapshot(row(1, dependencies=["demo#99"]), row(2, dependencies=["demo#1"]), row(3))])
        result = ot.plan(graph)
        self.assertEqual(result["order"], ["pr:myon-bioinformatics/demo#3"])
        self.assertEqual(len(result["blocked"]), 2)
        self.assertEqual(result["missing"]["pr:myon-bioinformatics/demo#1"], ["pr:myon-bioinformatics/demo#99"])

    def test_cycle_does_not_block_independent_component(self):
        graph = ot.audit([snapshot(row(1, dependencies=["demo#2"]), row(2, dependencies=["demo#1"]),
                                row(3, dependencies=["demo#2"]), row(4))])
        result = ot.plan(graph)
        self.assertTrue(result["cycle"])
        self.assertEqual(len(result["blocked"]), 3)
        self.assertEqual(result["order"], ["pr:myon-bioinformatics/demo#4"])

    def test_latest_observation_replaces_dependencies_without_deleting_history(self):
        old = snapshot(row(1, dependencies=["demo#99"]))
        new = snapshot(row(1, dependencies=[], head_sha="c" * 40), at="2026-11-15T00:00:00+09:00")
        graph = ot.audit([old, new])
        self.assertEqual(len([n for n in graph["nodes"] if n["type"] == "Observation"]), 2)
        self.assertFalse(ot.plan(graph)["missing"])
        self.assertTrue(any(e["relation"] == "dependsOn" for e in graph["edges"]))

    def test_equal_timestamp_conflicts_are_reported(self):
        graph = ot.audit([snapshot(row(1)), snapshot(row(1, head_sha="c" * 40))])
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            ot.plan(graph)

    def test_workflow_outcomes_are_scoped_by_sha_attempt_and_observation(self):
        runs = [{"id": 12, "run_attempt": 1, "name": "Minimal stdlib distributions", "head_sha": "a" * 40,
                 "conclusion": "failure", "status": "completed"},
                {"id": 12, "run_attempt": 2, "name": "Minimal stdlib distributions", "head_sha": "a" * 40,
                 "conclusion": "cancelled", "status": "completed"}]
        graph = ot.audit([snapshot(row(1, runs=runs))])
        nodes = [n for n in graph["nodes"] if n["type"] == "WorkflowRun"]
        self.assertEqual(len(nodes), 2)
        edges = [e for e in graph["edges"] if e["relation"] == "hasRun"]
        self.assertEqual({e["conclusion"] for e in edges}, {"failure", "cancelled"})
        self.assertTrue(all(e["scope"] == "pr_head" for e in edges))

    def test_history_does_not_assert_timeless_dependency_in_rdf(self):
        graph = ot.audit([snapshot(row(1, dependencies=["demo#2"]), row(2))])
        text = ot.turtle(graph)
        self.assertIn("a rdf:Statement", text)
        self.assertIn("rdf:predicate ot:dependsOn", text)
        self.assertNotIn("> ot:dependsOn <", text)
        self.assertIn("rdfs:domain ot:Observation", text)

    def test_validation_rejects_bad_sha_unknown_classes_and_dangling_edges(self):
        with self.assertRaises(ValueError):
            ot.audit([snapshot(row(1, head_sha="short"))])
        graph = ot.audit([snapshot(row(1))])
        broken = copy.deepcopy(graph)
        broken["nodes"][0]["type"] = "Unknown"
        with self.assertRaises(ValueError):
            ot.validate(broken)
        broken = copy.deepcopy(graph)
        broken["edges"][0]["target"] = "missing"
        with self.assertRaises(ValueError):
            ot.validate(broken)

    def test_observation_requires_timezone_and_boolean_facts(self):
        with self.assertRaises(ValueError):
            ot.audit([snapshot(row(1), at="2026-11-14T14:00:00")])
        with self.assertRaises(ValueError):
            ot.audit([snapshot(row(1, merged="false"))])

    def test_repeated_snapshot_is_idempotent_and_output_deterministic(self):
        doc = snapshot(row(1, files=["b", "a", "a"]))
        self.assertEqual(ot.audit([doc]), ot.audit([doc, doc]))

    def test_unknown_file_list_differs_from_observed_empty_list(self):
        graph = ot.audit([snapshot(row(1, files=None), row(2, files=[]))])
        observations = [n for n in graph["nodes"] if n["type"] == "Observation"]
        self.assertEqual({n["files_observed"] for n in observations}, {False, True})

    def test_cli_works_without_site_packages_and_returns_error_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "audit.json", Path(tmp) / "graph.json"
            source.write_text(json.dumps(snapshot(row(1))))
            script = str(Path(__file__).resolve().parent.parent / "ontautology.py")
            result = subprocess.run([sys.executable, "-S", script, "audit", str(source), "-o", str(output)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text())["schema"], "ontautology/1")
            source.write_text("{}")
            result = subprocess.run([sys.executable, "-S", script, "audit", str(source)], capture_output=True)
            self.assertEqual(result.returncode, 1)  # input error; 2 is kept for "answered, needs a look"
            self.assertNotIn(b"Traceback", result.stderr)

    def test_a_run_is_tied_to_its_own_commit_never_assumed_to_be_the_pr_head(self):
        runs = [{"id": 7, "run_attempt": 1, "head_sha": "d" * 40, "conclusion": "success"},  # an older head
                {"id": 7, "run_attempt": 2, "head_sha": "a" * 40, "conclusion": "failure"},
                {"id": 8, "conclusion": "success"}]                                        # head not collected
        graph = ot.audit([snapshot(row(1, runs=runs))])
        at = {e["source"]: e["target"].rsplit("@", 1)[1] for e in graph["edges"] if e["relation"] == "runsAt"}
        self.assertEqual(sorted(at.values()), ["a" * 40, "d" * 40])
        self.assertEqual(sum(n["type"] == "WorkflowRun" for n in graph["nodes"]), 3)
        self.assertFalse(any("unknown" in source for source in at))  # no commit is invented for the third run

    def test_the_site_observation_export_is_unwrapped(self):
        graph = ot.audit([{"aoi_integration": snapshot(row(1))}])
        self.assertEqual(graph, ot.audit([snapshot(row(1))]))

    def test_core_walks_answer_on_an_audit_graph(self):
        graph = ot.audit([snapshot(row(1, files=["tool.py"]), row(2, dependencies=["demo#1"]), row(3, files=["tool.py"]))])
        edges = ot.edges_of(graph)
        self.assertEqual(ot.check(edges, [n["id"] for n in graph["nodes"]]), [])
        reached = {r["node"] for r in ot.reach(edges, ["file:myon-bioinformatics/demo:tool.py"])["rows"]}
        prs = {n for n in reached if n.startswith("pr:")}
        self.assertEqual(prs, {"pr:myon-bioinformatics/demo#%d" % n for n in (1, 2, 3)})  # touched by 1 and 3, and 2 waits on 1
        rests = {r["edge"]["source"] for r in ot.why(edges, "pr:myon-bioinformatics/demo#2", depth=1)["rows"]}
        self.assertIn("pr:myon-bioinformatics/demo#1", rests)
        overlaps = [(e["source"][-1], e["target"][-1], e["basis"]) for e in edges if e["kind"] == "overlapsWith"]
        self.assertEqual(sorted(overlaps), [("1", "3", "derived"), ("3", "1", "derived")])  # no direction: both ways
        self.assertEqual(ot.cycles([e for e in edges if e["kind"] == "dependsOn"]), [])  # touching the same file is not a dependency cycle


class ExtendedAuditTests(unittest.TestCase):
    def test_evidence_kind_is_payload_not_node_type(self):
        graph = ot.audit([snapshot(row(1, evidence=[{"kind": "PR metadata", "url": "https://github.com/o/r/pull/1"}]))])
        evidence = next(n for n in graph["nodes"] if n["type"] == "Evidence")
        self.assertEqual(evidence["kind"], "PR metadata")
        self.assertIn("ot:kind", ot.turtle(graph))


    def test_typed_entities_and_job_attempts(self):
        run={'id':7,'run_attempt':2,'name':'CI','jobs':[{'id':8,'name':'unit','conclusion':'cancelled'}]}
        doc=snapshot(row(1,contained_in_main=False,runs=[run],issues=[{'number':10}],
            reviews=[{'id':11,'commit_id':'a'*40,'state':'COMMENTED'}],pins=[{'sha':'c'*40}],
            artifacts=[{'name':'dist.py','source_sha':'d'*40}],evidence=[{'url':'https://github.com/o/r'}],
            gaps=[{'reason':'required checks unknown'}],tasks=[{'id':'verify','phase':'再検証','state':'着手中'}],
            completion_records=[{'title':'merge verified','evidence_url':'https://github.com/o/r','verified_sha':'e'*40}]))
        graph=ot.audit([doc]);types={n['type'] for n in graph['nodes']}
        self.assertTrue({'Issue','Review','Job','FixedSHA','Artifact','Evidence','EvidenceGap','MainGap','Task','CompletionRecord'}<=types)
        edge=next(e for e in graph['edges'] if e['relation']=='hasJob')
        self.assertEqual(edge['conclusion'],'cancelled');self.assertIn('attempt:2',edge['target'])
        self.assertFalse(any(e['relation']=='runsAt' for e in graph['edges']))
        self.assertIn('ot:hasJob',ot.turtle(graph))

    def test_main_gap_is_explicit_and_not_sha_inequality(self):
        graph=ot.audit([snapshot(row(1,contained_in_main=None,head_sha='c'*40))])
        self.assertFalse(any(n['type']=='MainGap' for n in graph['nodes']))

    def test_complete_needs_verified_sha_and_evidence(self):
        for changes in ({'tasks':[{'id':'done','state':'完了'}]}, {'completion_records':[{}]}):
            with self.assertRaisesRegex(ValueError,'needs evidence_url'):
                ot.audit([snapshot(row(1,**changes))])

    def test_task_order_is_distinct_from_pr_dependency(self):
        graph=ot.audit([snapshot(row(1,tasks=[{'id':'fix','phase':'修正'}, {'id':'test','after':['fix'],'phase':'再検証'}]))])
        self.assertTrue(any(e['relation']=='precedes' for e in graph['edges']))
        self.assertFalse(any(e['relation']=='dependsOn' for e in graph['edges']))
        with self.assertRaisesRegex(ValueError,'unknown task'):
            ot.audit([snapshot(row(1,tasks=[{'id':'test','after':['missing']}]))])

    def test_diff_ignores_timestamp_but_reports_job_outcome(self):
        values={'runs':[{'id':7,'run_attempt':1,'head_sha':'a'*40,'name':'CI','jobs':[{'id':8,'conclusion':'failure'}]}]}
        old=ot.audit([snapshot(row(1,**values))])
        later=snapshot(row(1,**values),at='2026-11-15T01:00:00Z')
        self.assertFalse(ot.observation_diff(old,ot.audit([later]))['changed'])
        later['records'][0]['runs'][0]['jobs'][0]['conclusion']='success'
        self.assertEqual(len(ot.observation_diff(old,ot.audit([later]))['changed']),1)

    def test_diff_preserves_added_removed(self):
        diff=ot.observation_diff(ot.audit([snapshot(row(1))]),ot.audit([snapshot(row(2))]))
        self.assertEqual(diff['added'],['pr:myon-bioinformatics/demo#2'])
        self.assertEqual(diff['removed'],['pr:myon-bioinformatics/demo#1'])

    def test_history_keeps_review_outcomes_separate(self):
        doc=snapshot(row(1,reviews=[{'id':1,'state':'APPROVED'}]))
        later=snapshot(row(1,reviews=[{'id':1,'state':'DISMISSED'}]),at='2026-11-15T01:00:00Z')
        graph=ot.audit([doc,later]);self.assertEqual(sum(n['type']=='Review' for n in graph['nodes']),2)
        self.assertTrue(all(e.get('observation') for e in graph['edges'] if e['relation']=='hasReview'))

    def test_diff_cli_is_stdlib_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'graph.json';path.write_text(json.dumps(ot.audit([snapshot(row(1))])))
            script=str(Path(__file__).resolve().parent.parent / 'ontautology.py')
            result=subprocess.run([sys.executable,'-S',script,'diff',str(path),str(path)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['changed'],[])

class WorkflowProvenance(unittest.TestCase):
    def example(self):
        return json.loads((Path(__file__).resolve().parent.parent /
                           "examples/audit-20261114.json").read_text(encoding="utf-8"))

    def target(self, document):
        return next(run for row in document["records"] for run in row.get("postmerge_runs", [])
                    if run["id"] == 43602131802)

    def claim(self, graph):
        run = next(node for node in graph["nodes"] if node.get("run_id") == 43602131802)
        return next(edge for edge in graph["edges"]
                    if edge["relation"] == "hasRun" and edge["target"] == run["id"])

    def test_event_and_workflow_identity_survive_json_and_turtle(self):
        graph = ot.audit([self.example()])
        claim = self.claim(json.loads(json.dumps(graph)))
        self.assertEqual((claim["event"], claim["workflow_id"], claim["scope"]),
                         ("workflow_run", 401581886, "main"))
        rdf = ot.turtle(graph)
        self.assertIn('ot:event "workflow_run"', rdf)
        self.assertIn('ot:workflow_id 401581886', rdf)

    def test_each_metadata_change_is_a_graph_diff(self):
        before = self.example()
        for field, value in (("event", "push"), ("workflow_id", 99)):
            with self.subTest(field=field):
                after = copy.deepcopy(before)
                self.target(after)[field] = value
                changes = ot.observation_diff(ot.audit([before]), ot.audit([after]))["changed"]
                self.assertEqual([change["pr"] for change in changes],
                                 ["pr:myon-bioinformatics/Aoi#207"])

    def test_unobserved_metadata_remains_null_not_inferred_from_main_scope(self):
        document = self.example()
        for key in ("event", "workflow_id"):
            self.target(document).pop(key, None)
        claim = self.claim(ot.audit([document]))
        self.assertIsNone(claim["event"])
        self.assertIsNone(claim["workflow_id"])


if __name__ == "__main__":
    unittest.main()
