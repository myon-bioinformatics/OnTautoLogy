import unittest
from ontautology import build_graph


def item(repo, number, files=None):
    return {"repo": repo, "n": number, "pr": {"head_sha": "abc"},
            "files": None if files is None else {"filenames": files},
            "runs": {"workflow_runs": [{"id": number, "name": "CI", "conclusion": "failure"}]}}


class GraphTests(unittest.TestCase):
    def test_overlap_is_repo_scoped_and_deduplicated(self):
        graph = build_graph({"result": [item("a", 1, ["x", "x"]), item("a", 2, ["x"]), item("b", 3, ["x"])]})
        overlaps = [e for e in graph["edges"] if e["relation"] == "shares_changed_paths_with"]
        self.assertEqual(len(overlaps), 1)
        self.assertEqual(overlaps[0]["paths"], ["x"])
        self.assertEqual(len([e for e in graph["edges"] if e["relation"] == "changes"]), 3)
        self.assertEqual(next(n for n in graph["nodes"] if n["type"] == "WorkflowRun")["observed_head_sha"], "abc")

    def test_unknown_files_are_not_treated_as_empty(self):
        graph = build_graph({"result": [item("a", 1), item("a", 2, ["x"])]})
        self.assertEqual(graph["coverage"]["file_lists_missing"], ["a#1"])
        self.assertFalse(any(e["relation"] == "shares_changed_paths_with" for e in graph["edges"]))

    def test_dependencies_order_and_cycle(self):
        data = {"result": [item("a", 1, []), item("a", 2, [])], "dependencies": [{"dependent": "a#2", "prerequisite": "a#1", "evidence": "example"}]}
        self.assertEqual(build_graph(data)["integration_batches"], [["a#1"], ["a#2"]])
        data["dependencies"].append({"dependent": "a#1", "prerequisite": "a#2"})
        graph = build_graph(data)
        self.assertTrue(graph["dependency_cycle"])
        self.assertEqual(graph["integration_batches"], [])

    def test_unknown_and_duplicate_prs_rejected(self):
        with self.assertRaises(ValueError):
            build_graph({"result": [item("a", 1, []), item("a", 1, [])]})
        with self.assertRaises(ValueError):
            build_graph({"result": [item("a", 1, [])], "dependencies": [{"dependent": "a#1", "prerequisite": "a#2"}]})


import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ontautology import build, plan, turtle, validate


def row(number, **changes):
    return {"repository": "demo", "number": number, "state": "調査中", "head_sha": "a" * 40,
            "base_sha": "b" * 40, "main_sha": "b" * 40, "base": "main", "merged": False,
            "mergeable": None, "contained_in_main": None, "files": [], "dependencies": [], **changes}


def snapshot(*rows, at="2026-11-14T14:00:00Z"):
    return {"schema": "integration-audit/3", "captured_at": at, "records": list(rows)}


class TemporalGraphTests(unittest.TestCase):
    def test_overlap_is_repository_scoped_and_not_a_conflict(self):
        graph = build([snapshot(row(1, files=["README.md"]), row(2, files=["README.md"]),
                                row(3, repository="other", files=["README.md"]))])
        overlaps = [e for e in graph["edges"] if e["relation"] == "overlapsWith"]
        self.assertEqual(len(overlaps), 1)
        self.assertIn("not a conflict", overlaps[0]["basis"])
        self.assertEqual(overlaps[0]["target"], "pr:myon-bioinformatics/demo#2")

    def test_merge_and_main_containment_are_independent(self):
        graph = build([snapshot(row(1, merged=True), row(2, contained_in_main=True))])
        self.assertEqual(plan(graph)["order"], ["pr:myon-bioinformatics/demo#1"])
        obs = [n for n in graph["nodes"] if n["type"] == "Observation"]
        self.assertIsNone(obs[0]["mergeable"])

    def test_missing_dependency_blocks_transitively(self):
        graph = build([snapshot(row(1, dependencies=["demo#99"]), row(2, dependencies=["demo#1"]), row(3))])
        result = plan(graph)
        self.assertEqual(result["order"], ["pr:myon-bioinformatics/demo#3"])
        self.assertEqual(len(result["blocked"]), 2)
        self.assertEqual(result["missing"]["pr:myon-bioinformatics/demo#1"], ["pr:myon-bioinformatics/demo#99"])

    def test_cycle_does_not_block_independent_component(self):
        graph = build([snapshot(row(1, dependencies=["demo#2"]), row(2, dependencies=["demo#1"]),
                                row(3, dependencies=["demo#2"]), row(4))])
        result = plan(graph)
        self.assertTrue(result["cycle"])
        self.assertEqual(len(result["blocked"]), 3)
        self.assertEqual(result["order"], ["pr:myon-bioinformatics/demo#4"])

    def test_latest_observation_replaces_dependencies_without_deleting_history(self):
        old = snapshot(row(1, dependencies=["demo#99"]))
        new = snapshot(row(1, dependencies=[], head_sha="c" * 40), at="2026-11-15T00:00:00+09:00")
        graph = build([old, new])
        self.assertEqual(len([n for n in graph["nodes"] if n["type"] == "Observation"]), 2)
        self.assertFalse(plan(graph)["missing"])
        self.assertTrue(any(e["relation"] == "dependsOn" for e in graph["edges"]))

    def test_equal_timestamp_conflicts_are_reported(self):
        graph = build([snapshot(row(1)), snapshot(row(1, head_sha="c" * 40))])
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            plan(graph)

    def test_workflow_outcomes_are_scoped_by_sha_attempt_and_observation(self):
        runs = [{"id": 12, "run_attempt": 1, "name": "Minimal stdlib distributions", "head_sha": "a" * 40,
                 "conclusion": "failure", "status": "completed"},
                {"id": 12, "run_attempt": 2, "name": "Minimal stdlib distributions", "head_sha": "a" * 40,
                 "conclusion": "cancelled", "status": "completed"}]
        graph = build([snapshot(row(1, runs=runs))])
        nodes = [n for n in graph["nodes"] if n["type"] == "WorkflowRun"]
        self.assertEqual(len(nodes), 2)
        edges = [e for e in graph["edges"] if e["relation"] == "hasRun"]
        self.assertEqual({e["conclusion"] for e in edges}, {"failure", "cancelled"})
        self.assertTrue(all(e["scope"] == "pr_head" for e in edges))

    def test_history_does_not_assert_timeless_dependency_in_rdf(self):
        graph = build([snapshot(row(1, dependencies=["demo#2"]), row(2))])
        text = turtle(graph)
        self.assertIn("a rdf:Statement", text)
        self.assertIn("rdf:predicate ot:dependsOn", text)
        self.assertNotIn("> ot:dependsOn <", text)
        self.assertIn("rdfs:domain ot:Observation", text)

    def test_validation_rejects_bad_sha_unknown_classes_and_dangling_edges(self):
        with self.assertRaises(ValueError):
            build([snapshot(row(1, head_sha="short"))])
        graph = build([snapshot(row(1))])
        broken = copy.deepcopy(graph)
        broken["nodes"][0]["type"] = "Unknown"
        with self.assertRaises(ValueError):
            validate(broken)
        broken = copy.deepcopy(graph)
        broken["edges"][0]["target"] = "missing"
        with self.assertRaises(ValueError):
            validate(broken)

    def test_observation_requires_timezone_and_boolean_facts(self):
        with self.assertRaises(ValueError):
            build([snapshot(row(1), at="2026-11-14T14:00:00")])
        with self.assertRaises(ValueError):
            build([snapshot(row(1, merged="false"))])

    def test_repeated_snapshot_is_idempotent_and_output_deterministic(self):
        doc = snapshot(row(1, files=["b", "a", "a"]))
        self.assertEqual(build([doc]), build([doc, doc]))

    def test_unknown_file_list_differs_from_observed_empty_list(self):
        graph = build([snapshot(row(1, files=None), row(2, files=[]))])
        observations = [n for n in graph["nodes"] if n["type"] == "Observation"]
        self.assertEqual({n["files_observed"] for n in observations}, {False, True})

    def test_cli_works_without_site_packages_and_returns_error_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "audit.json", Path(tmp) / "graph.json"
            source.write_text(json.dumps(snapshot(row(1))))
            script = str(Path(__file__).with_name("ontautology.py"))
            result = subprocess.run([sys.executable, "-S", script, "build", str(source), "-o", str(output)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text())["schema"], "ontautology/1")
            source.write_text("{}")
            result = subprocess.run([sys.executable, "-S", script, "build", str(source)], capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn(b"Traceback", result.stderr)

    def test_original_cli_still_uses_original_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "snapshot.json"
            source.write_text(json.dumps({"result": [item("demo", 1, [])]}))
            script = str(Path(__file__).with_name("ontautology.py"))
            result = subprocess.run([sys.executable, "-S", script, str(source)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["schema"], "ontautology/pr-audit-graph/1")




class ExtendedAuditTests(unittest.TestCase):
    def test_typed_entities_and_job_attempts(self):
        run={'id':7,'run_attempt':2,'name':'CI','jobs':[{'id':8,'name':'unit','conclusion':'cancelled'}]}
        doc=snapshot(row(1,contained_in_main=False,runs=[run],issues=[{'number':10}],
            reviews=[{'id':11,'commit_id':'a'*40,'state':'COMMENTED'}],pins=[{'sha':'c'*40}],
            artifacts=[{'name':'dist.py','source_sha':'d'*40}],evidence=[{'url':'https://github.com/o/r'}],
            gaps=[{'reason':'required checks unknown'}],tasks=[{'id':'verify','phase':'再検証','state':'着手中'}],
            completion_records=[{'title':'merge verified','evidence_url':'https://github.com/o/r','verified_sha':'e'*40}]))
        graph=build([doc]);types={n['type'] for n in graph['nodes']}
        self.assertTrue({'Issue','Review','Job','FixedSHA','Artifact','Evidence','EvidenceGap','MainGap','Task','CompletionRecord'}<=types)
        edge=next(e for e in graph['edges'] if e['relation']=='hasJob')
        self.assertEqual(edge['conclusion'],'cancelled');self.assertIn('attempt:2',edge['target'])
        self.assertFalse(any(e['relation']=='runsAt' for e in graph['edges']))
        self.assertIn('ot:hasJob',turtle(graph))

    def test_main_gap_is_explicit_and_not_sha_inequality(self):
        graph=build([snapshot(row(1,contained_in_main=None,head_sha='c'*40))])
        self.assertFalse(any(n['type']=='MainGap' for n in graph['nodes']))

    def test_complete_needs_verified_sha_and_evidence(self):
        for changes in ({'tasks':[{'id':'done','state':'完了'}]}, {'completion_records':[{}]}):
            with self.assertRaisesRegex(ValueError,'needs evidence_url'):
                build([snapshot(row(1,**changes))])

    def test_task_order_is_distinct_from_pr_dependency(self):
        graph=build([snapshot(row(1,tasks=[{'id':'fix','phase':'修正'}, {'id':'test','after':['fix'],'phase':'再検証'}]))])
        self.assertTrue(any(e['relation']=='precedes' for e in graph['edges']))
        self.assertFalse(any(e['relation']=='dependsOn' for e in graph['edges']))
        with self.assertRaisesRegex(ValueError,'unknown task'):
            build([snapshot(row(1,tasks=[{'id':'test','after':['missing']}]))])

    def test_diff_ignores_timestamp_but_reports_job_outcome(self):
        from ontautology import observation_diff
        values={'runs':[{'id':7,'run_attempt':1,'head_sha':'a'*40,'name':'CI','jobs':[{'id':8,'conclusion':'failure'}]}]}
        old=build([snapshot(row(1,**values))])
        later=snapshot(row(1,**values),at='2026-11-15T01:00:00Z')
        self.assertFalse(observation_diff(old,build([later]))['changed'])
        later['records'][0]['runs'][0]['jobs'][0]['conclusion']='success'
        self.assertEqual(len(observation_diff(old,build([later]))['changed']),1)

    def test_diff_preserves_added_removed(self):
        from ontautology import observation_diff
        diff=observation_diff(build([snapshot(row(1))]),build([snapshot(row(2))]))
        self.assertEqual(diff['added'],['pr:myon-bioinformatics/demo#2'])
        self.assertEqual(diff['removed'],['pr:myon-bioinformatics/demo#1'])

    def test_history_keeps_review_outcomes_separate(self):
        doc=snapshot(row(1,reviews=[{'id':1,'state':'APPROVED'}]))
        later=snapshot(row(1,reviews=[{'id':1,'state':'DISMISSED'}]),at='2026-11-15T01:00:00Z')
        graph=build([doc,later]);self.assertEqual(sum(n['type']=='Review' for n in graph['nodes']),2)
        self.assertTrue(all(e.get('observation') for e in graph['edges'] if e['relation']=='hasReview'))

    def test_diff_cli_is_stdlib_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'graph.json';path.write_text(json.dumps(build([snapshot(row(1))])))
            script=str(Path(__file__).with_name('ontautology.py'))
            result=subprocess.run([sys.executable,'-S',script,'diff',str(path),str(path)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['changed'],[])


if __name__ == "__main__":
    unittest.main()
