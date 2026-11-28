"""第一弾 (phase 1) — the GitHub audit dashboard (gh_audit/gh_audit.py): snapshots → graph, plan, diff, Turtle, transfers. Standard library only."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ontautology as ot  # noqa: E402
from gh_audit import gh_audit as ga  # noqa: E402
from test_ontautology import run_cli  # noqa: E402
from vendor.cli_args import run_cli as run_cli_command  # noqa: E402


class AuditTransport(unittest.TestCase):
    script = Path(__file__).resolve().parent.parent / 'gh_audit/gh_audit.py'

    def run_cli(self, *args, **options):
        return run_cli(self.script, *args, **options)

    def test_stdin_audit_matches_file_and_preserves_japanese(self):
        path = self.script.parents[1] / 'examples/audit-20261114.json'
        document = json.loads(path.read_text(encoding='utf-8'))
        document['records'][0]['title'] = '監査の入力を保持'
        p = self.run_cli('audit', '-', data=json.dumps(document, ensure_ascii=False))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), ga.audit([document]))

    def test_stdin_reuse_is_an_input_error(self):
        for args in (('audit','-','-'), ('diff','-','-')):
            p=self.run_cli(*args)
            self.assertEqual(p.returncode,1);self.assertEqual(p.stdout,b'');self.assertIn(b'ontautology:',p.stderr)

    def test_core_commands_read_an_audit_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph = Path(tmp) / 'graph.json'
            self.assertEqual(self.run_cli('audit', str(self.script.parents[1] / 'examples/audit-20261114.json'), '-o', str(graph)).returncode, 0)
            p = self.run_cli('reach', str(graph), 'file:myon-bioinformatics/Aoi:README.md')
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(json.loads(p.stdout)['rows'])
            core = run_cli_command(self.script.parents[1] / 'ontautology.py', 'reach', str(graph), 'x', python_options=('-S',))
            self.assertEqual(core.returncode, 1, 'the core alone does not know audit graphs')



def row(number, **changes):
    return {"repository": "demo", "number": number, "state": "調査中", "head_sha": "a" * 40,
            "base_sha": "b" * 40, "main_sha": "b" * 40, "base": "main", "merged": False,
            "mergeable": None, "contained_in_main": None, "files": [], "dependencies": [], **changes}


def snapshot(*rows, at="2026-11-14T14:00:00Z"):
    return {"schema": "integration-audit/3", "captured_at": at, "records": list(rows)}


class OpenInventoryTests(unittest.TestCase):
    repo = "myon-bioinformatics/Ironmate"
    ident = "pr:" + repo + "#231"

    def doc(self, numbers, *rows, at="2026-11-15T12:00:00Z", complete=True):
        doc = snapshot(*rows, at=at)
        doc["open_pr_inventory"] = [{"repository": self.repo, "checked_at": at,
                                     "complete": complete, "open_pr_numbers": numbers}]
        return doc

    def test_empty_snapshot_then_new_pr_and_back_to_zero_keeps_history(self):
        empty = self.doc([])
        newer = self.doc([231], row(231, repository=self.repo), at="2026-11-15T13:00:00Z")
        graph = ga.audit([empty, newer])
        self.assertEqual(ga.plan(graph)["order"], [self.ident])
        self.assertEqual(len([n for n in graph["nodes"] if n["type"] == "Snapshot"]), 2)
        self.assertIn("ot:Snapshot", ga.turtle(graph))
        final = self.doc([], at="2026-11-15T14:00:00Z")
        graph = ga.audit([empty, newer, final])
        self.assertEqual(ga.plan(graph)["order"], [])
        self.assertTrue(any(n["type"] == "Observation" for n in graph["nodes"]))
        self.assertIs(ga.validate(graph), graph)

    def test_incomplete_latest_suppresses_stale_schedule_and_is_not_zero(self):
        first = self.doc([231], row(231, repository=self.repo))
        partial = self.doc(None, at="2026-11-15T13:00:00Z", complete=False)
        result = ga.plan(ga.audit([first, partial]))
        self.assertEqual(result["order"], [])
        self.assertEqual(result["inventory_uncertainty"][self.repo]["open_pr_numbers"], None)
        self.assertFalse(result["inventory_uncertainty"][self.repo]["complete"])

    def test_membership_requires_row_in_same_snapshot_not_older_evidence(self):
        first = self.doc([231], row(231, repository=self.repo))
        second = self.doc([231, 232], at="2026-11-15T13:00:00Z")
        result = ga.plan(ga.audit([first, second]))
        self.assertEqual(result["order"], [])
        self.assertEqual(result["missing_rows"], [self.ident, self.ident[:-3] + "232"])
        self.assertEqual(result["blocked"], result["missing_rows"])
        # Collection can precede captured_at: digest, not timestamp equality, binds rows.
        second["records"] = [row(231, repository=self.repo)]
        second["captured_at"] = "2026-11-15T14:00:00Z"
        self.assertEqual(ga.plan(ga.audit([second]))["order"], [self.ident])

    def test_inventory_scope_does_not_erase_other_repositories_or_legacy(self):
        legacy = snapshot(row(1))
        result = ga.plan(ga.audit([legacy, self.doc([])]))
        self.assertEqual(result["order"], ["pr:myon-bioinformatics/demo#1"])
        baseline = ga.plan(ga.audit([legacy]))
        self.assertNotIn("missing_rows", baseline)
        doc = snapshot(row(1)); doc["open_pr_inventory"] = []
        result = ga.plan(ga.audit([doc]))
        self.assertEqual(result["order"], baseline["order"])

    def test_absent_dependency_is_not_completion_without_verified_containment(self):
        for contained in (None, True):
            old = self.doc([231], row(231, repository=self.repo, contained_in_main=contained))
            current = self.doc([], row(1, dependencies=[self.repo + "#231"]), at="2026-11-15T13:00:00Z")
            result = ga.plan(ga.audit([old, current]))
            dependent = "pr:myon-bioinformatics/demo#1"
            self.assertEqual(result["order"], [dependent] if contained else [])
            if not contained:
                self.assertEqual(result["missing"][dependent], [self.ident])

    def test_missing_row_blocks_dependents_and_partial_scope_blocks_cross_repo(self):
        for complete, numbers in ((True, [231]), (False, None)):
            doc = self.doc(numbers, row(1, dependencies=[self.repo + "#231"]), complete=complete)
            result = ga.plan(ga.audit([doc]))
            self.assertEqual(result["order"], [])
            self.assertIn("pr:myon-bioinformatics/demo#1", result["blocked"])

    def test_inventory_turtle_is_json_text_literal_and_partial_cli_requires_attention(self):
        doc = self.doc(None, complete=False)
        graph = ga.audit([doc])
        line = next(line for line in ga.turtle(graph).splitlines() if " ot:open_pr_inventory " in line)
        literal = line.split(" ot:open_pr_inventory ", 1)[1].removesuffix(" .")
        self.assertEqual(json.loads(json.loads(literal)), doc["open_pr_inventory"])
        p = run_cli_command(AuditTransport.script, "plan", "-",
                            python_options=("-S",), stdin=json.dumps(graph))
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(json.loads(p.stdout)["inventory_uncertainty"][self.repo]["complete"], False)

    def test_existing_closed_merged_and_snapshot_aliases_are_retained(self):
        for facts in ({"merged": True}, {"github_state": "closed"}):
            doc = self.doc([231], row(231, repository=self.repo, **facts))
            graph = ga.audit([doc])
            self.assertEqual(ga.plan(graph)["order"], [])
            self.assertTrue(any(e["relation"] == "derived_from" for e in graph["edges"]))
        first = self.doc([231], row(231, repository=self.repo))
        second = self.doc([], at="2026-11-15T13:00:00Z")
        second["previous_snapshot"] = {"digest": ga.digest(first), "captured_at": first["captured_at"]}
        forward = ga.audit([first, second])
        self.assertEqual(forward, ga.audit([second, first]))
        self.assertTrue(any(e["relation"] == "supersedes" for e in forward["edges"]))
        self.assertEqual(ga.plan(forward)["order"], [])

    def test_invalid_inventory_rejected_and_graph_validation_checks_it(self):
        for entry in (None, [], "bad", {}, {"repository": self.repo}):
            doc = self.doc([])
            doc["open_pr_inventory"] = [entry]
            with self.assertRaises(ValueError):
                ga.audit([doc])
        for complete, numbers in ((True, None), (True, [True]), (True, [0]), (True, [1,1]), (False, [])):
            with self.assertRaises(ValueError):
                ga.audit([self.doc(numbers, complete=complete)])
        graph = ga.audit([self.doc([])])
        snap = next(n for n in graph["nodes"] if n["type"] == "Snapshot")
        snap["open_pr_inventory"][0]["complete"] = "yes"
        with self.assertRaises(ValueError):
            ga.validate(graph)


class TemporalGraphTests(unittest.TestCase):
    def test_overlap_is_repository_scoped_and_not_a_conflict(self):
        graph = ga.audit([snapshot(row(1, files=["README.md"]), row(2, files=["README.md"]),
                                row(3, repository="other", files=["README.md"]))])
        overlaps = [e for e in graph["edges"] if e["relation"] == "overlapsWith"]
        self.assertEqual(len(overlaps), 1)
        self.assertIn("not a conflict", overlaps[0]["basis"])
        self.assertEqual(overlaps[0]["target"], "pr:myon-bioinformatics/demo#2")

    def test_merge_and_main_containment_are_independent(self):
        graph = ga.audit([snapshot(row(1, merged=True), row(2, contained_in_main=True))])
        self.assertEqual(ga.plan(graph)["order"], [])  # merged is not rescheduled after squash
        obs = [n for n in graph["nodes"] if n["type"] == "Observation"]
        self.assertIsNone(obs[0]["mergeable"])

    def test_missing_dependency_blocks_transitively(self):
        graph = ga.audit([snapshot(row(1, dependencies=["demo#99"]), row(2, dependencies=["demo#1"]), row(3))])
        result = ga.plan(graph)
        self.assertEqual(result["order"], ["pr:myon-bioinformatics/demo#3"])
        self.assertEqual(len(result["blocked"]), 2)
        self.assertEqual(result["missing"]["pr:myon-bioinformatics/demo#1"], ["pr:myon-bioinformatics/demo#99"])

    def test_cycle_does_not_block_independent_component(self):
        graph = ga.audit([snapshot(row(1, dependencies=["demo#2"]), row(2, dependencies=["demo#1"]),
                                row(3, dependencies=["demo#2"]), row(4))])
        result = ga.plan(graph)
        self.assertTrue(result["cycle"])
        self.assertEqual(len(result["blocked"]), 3)
        self.assertEqual(result["order"], ["pr:myon-bioinformatics/demo#4"])

    def test_latest_observation_replaces_dependencies_without_deleting_history(self):
        old = snapshot(row(1, dependencies=["demo#99"]))
        new = snapshot(row(1, dependencies=[], head_sha="c" * 40), at="2026-11-15T00:00:00+09:00")
        graph = ga.audit([old, new])
        self.assertEqual(len([n for n in graph["nodes"] if n["type"] == "Observation"]), 2)
        self.assertFalse(ga.plan(graph)["missing"])
        self.assertTrue(any(e["relation"] == "dependsOn" for e in graph["edges"]))

    def test_equal_timestamp_conflicts_are_reported(self):
        graph = ga.audit([snapshot(row(1)), snapshot(row(1, head_sha="c" * 40))])
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            ga.plan(graph)

    def test_workflow_outcomes_are_scoped_by_sha_attempt_and_observation(self):
        runs = [{"id": 12, "run_attempt": 1, "name": "Minimal stdlib distributions", "head_sha": "a" * 40,
                 "conclusion": "failure", "status": "completed"},
                {"id": 12, "run_attempt": 2, "name": "Minimal stdlib distributions", "head_sha": "a" * 40,
                 "conclusion": "cancelled", "status": "completed"}]
        graph = ga.audit([snapshot(row(1, runs=runs))])
        nodes = [n for n in graph["nodes"] if n["type"] == "ActionsRun"]
        self.assertEqual(len(nodes), 2)
        edges = [e for e in graph["edges"] if e["relation"] == "hasRun"]
        self.assertEqual({e["conclusion"] for e in edges}, {"failure", "cancelled"})
        self.assertTrue(all(e["scope"] == "pr_head" for e in edges))

    def test_history_does_not_assert_timeless_dependency_in_rdf(self):
        graph = ga.audit([snapshot(row(1, dependencies=["demo#2"]), row(2))])
        text = ga.turtle(graph)
        self.assertIn("a rdf:Statement", text)
        self.assertIn("rdf:predicate ot:dependsOn", text)
        self.assertNotIn("> ot:dependsOn <", text)
        self.assertIn("rdfs:domain ot:Observation", text)

    def test_validation_rejects_bad_sha_unknown_classes_and_dangling_edges(self):
        with self.assertRaises(ValueError):
            ga.audit([snapshot(row(1, head_sha="short"))])
        graph = ga.audit([snapshot(row(1))])
        broken = copy.deepcopy(graph)
        broken["nodes"][0]["type"] = "Unknown"
        with self.assertRaises(ValueError):
            ga.validate(broken)
        broken = copy.deepcopy(graph)
        broken["edges"][0]["target"] = "missing"
        with self.assertRaises(ValueError):
            ga.validate(broken)

    def test_observation_requires_timezone_and_boolean_facts(self):
        with self.assertRaises(ValueError):
            ga.audit([snapshot(row(1), at="2026-11-14T14:00:00")])
        with self.assertRaises(ValueError):
            ga.audit([snapshot(row(1, merged="false"))])

    def test_repeated_snapshot_is_idempotent_and_output_deterministic(self):
        doc = snapshot(row(1, files=["b", "a", "a"]))
        self.assertEqual(ga.audit([doc]), ga.audit([doc, doc]))

    def test_unknown_file_list_differs_from_observed_empty_list(self):
        graph = ga.audit([snapshot(row(1, files=None), row(2, files=[]))])
        observations = [n for n in graph["nodes"] if n["type"] == "Observation"]
        self.assertEqual({n["files_observed"] for n in observations}, {False, True})

    def test_cli_works_without_site_packages_and_returns_error_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "audit.json", Path(tmp) / "graph.json"
            source.write_text(json.dumps(snapshot(row(1))))
            script = str(Path(__file__).resolve().parent.parent / "gh_audit/gh_audit.py")
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
        graph = ga.audit([snapshot(row(1, runs=runs))])
        at = {e["source"]: e["target"].rsplit("@", 1)[1] for e in graph["edges"] if e["relation"] == "runsAt"}
        self.assertEqual(sorted(at.values()), ["a" * 40, "d" * 40])
        self.assertEqual(sum(n["type"] == "ActionsRun" for n in graph["nodes"]), 3)
        self.assertFalse(any("unknown" in source for source in at))  # no commit is invented for the third run

    def test_the_site_observation_export_is_unwrapped(self):
        graph = ga.audit([{"aoi_integration": snapshot(row(1))}])
        self.assertEqual(graph, ga.audit([snapshot(row(1))]))

    def test_core_walks_answer_on_an_audit_graph(self):
        graph = ga.audit([snapshot(row(1, files=["tool.py"]), row(2, dependencies=["demo#1"]), row(3, files=["tool.py"]))])
        edges = ga.edges_of(graph)
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
        graph = ga.audit([snapshot(row(1, evidence=[{"kind": "PR metadata", "url": "https://github.com/o/r/pull/1"}]))])
        evidence = next(n for n in graph["nodes"] if n["type"] == "Evidence")
        self.assertEqual(evidence["kind"], "PR metadata")
        self.assertIn("ot:kind", ga.turtle(graph))


    def test_typed_entities_and_job_attempts(self):
        run={'id':7,'run_attempt':2,'name':'CI','jobs':[{'id':8,'name':'unit','conclusion':'cancelled'}]}
        doc=snapshot(row(1,contained_in_main=False,runs=[run],issues=[{'number':10}],
            reviews=[{'id':11,'commit_id':'a'*40,'state':'COMMENTED'}],pins=[{'sha':'c'*40}],
            artifacts=[{'name':'dist.py','source_sha':'d'*40}],evidence=[{'url':'https://github.com/o/r'}],
            gaps=[{'reason':'required checks unknown'}],tasks=[{'id':'verify','phase':'再検証','state':'着手中'}],
            completion_records=[{'title':'merge verified','evidence_url':'https://github.com/o/r','verified_sha':'e'*40}]))
        graph=ga.audit([doc]);types={n['type'] for n in graph['nodes']}
        self.assertTrue({'Issue','Review','Job','FixedSHA','GeneratedArtifact','Evidence','EvidenceGap','MainGap','Task','CompletionRecord'}<=types)
        edge=next(e for e in graph['edges'] if e['relation']=='hasJob')
        self.assertEqual(edge['conclusion'],'cancelled');self.assertIn('attempt:2',edge['target'])
        self.assertFalse(any(e['relation']=='runsAt' for e in graph['edges']))
        self.assertIn('ot:hasJob',ga.turtle(graph))

    def test_main_gap_is_explicit_and_not_sha_inequality(self):
        graph=ga.audit([snapshot(row(1,contained_in_main=None,head_sha='c'*40))])
        self.assertFalse(any(n['type']=='MainGap' for n in graph['nodes']))

    def test_complete_needs_verified_sha_and_evidence(self):
        for changes in ({'tasks':[{'id':'done','state':'完了'}]}, {'completion_records':[{}]}):
            with self.assertRaisesRegex(ValueError,'needs evidence_url'):
                ga.audit([snapshot(row(1,**changes))])

    def test_task_order_is_distinct_from_pr_dependency(self):
        graph=ga.audit([snapshot(row(1,tasks=[{'id':'fix','phase':'修正'}, {'id':'test','after':['fix'],'phase':'再検証'}]))])
        self.assertTrue(any(e['relation']=='precedes' for e in graph['edges']))
        self.assertFalse(any(e['relation']=='dependsOn' for e in graph['edges']))
        with self.assertRaisesRegex(ValueError,'unknown task'):
            ga.audit([snapshot(row(1,tasks=[{'id':'test','after':['missing']}]))])

    def test_diff_ignores_timestamp_but_reports_job_outcome(self):
        values={'runs':[{'id':7,'run_attempt':1,'head_sha':'a'*40,'name':'CI','jobs':[{'id':8,'conclusion':'failure'}]}]}
        old=ga.audit([snapshot(row(1,**values))])
        later=snapshot(row(1,**values),at='2026-11-15T01:00:00Z')
        self.assertFalse(ga.observation_diff(old,ga.audit([later]))['changed'])
        later['records'][0]['runs'][0]['jobs'][0]['conclusion']='success'
        self.assertEqual(len(ga.observation_diff(old,ga.audit([later]))['changed']),1)

    def test_diff_preserves_added_removed(self):
        diff=ga.observation_diff(ga.audit([snapshot(row(1))]),ga.audit([snapshot(row(2))]))
        self.assertEqual(diff['added'],['pr:myon-bioinformatics/demo#2'])
        self.assertEqual(diff['removed'],['pr:myon-bioinformatics/demo#1'])

    def test_history_keeps_review_outcomes_separate(self):
        doc=snapshot(row(1,reviews=[{'id':1,'state':'APPROVED'}]))
        later=snapshot(row(1,reviews=[{'id':1,'state':'DISMISSED'}]),at='2026-11-15T01:00:00Z')
        graph=ga.audit([doc,later]);self.assertEqual(sum(n['type']=='Review' for n in graph['nodes']),2)
        self.assertTrue(all(e.get('observation') for e in graph['edges'] if e['relation']=='hasReview'))

    def test_diff_cli_is_stdlib_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'graph.json';path.write_text(json.dumps(ga.audit([snapshot(row(1))])))
            script=str(Path(__file__).resolve().parent.parent / 'gh_audit/gh_audit.py')
            result=run_cli_command(script,'diff',str(path),str(path),python_options=('-S',))
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
        graph = ga.audit([self.example()])
        claim = self.claim(json.loads(json.dumps(graph)))
        self.assertEqual((claim["event"], claim["workflow_id"], claim["scope"]),
                         ("workflow_run", 401581886, "main"))
        rdf = ga.turtle(graph)
        self.assertIn('ot:event "workflow_run"', rdf)
        self.assertIn('ot:workflow_id 401581886', rdf)

    def test_each_metadata_change_is_a_graph_diff(self):
        before = self.example()
        for field, value in (("event", "push"), ("workflow_id", 99)):
            with self.subTest(field=field):
                after = copy.deepcopy(before)
                self.target(after)[field] = value
                changes = ga.observation_diff(ga.audit([before]), ga.audit([after]))["changed"]
                self.assertEqual([change["pr"] for change in changes],
                                 ["pr:myon-bioinformatics/Aoi#207"])

    def test_unobserved_metadata_remains_null_not_inferred_from_main_scope(self):
        document = self.example()
        for key in ("event", "workflow_id"):
            self.target(document).pop(key, None)
        claim = self.claim(ga.audit([document]))
        self.assertIsNone(claim["event"])
        self.assertIsNone(claim["workflow_id"])


if __name__ == "__main__":
    unittest.main()



class ConvergenceVocabulary(unittest.TestCase):
    def document(self, **changes):
        inventory = {'repo':'other/demo', 'main':'a'*40, 'issues':[],
                     'main_runs':[{'id':7,'run_attempt':None,'name':'CI','conclusion':'failure',
                                   'status':'completed','head_sha':None,'jobs':[]}],
                     'pin_records':[], 'gaps':['artifact payload unverified']}
        inventory.update(changes)
        return {'schema':'integration-audit/3','captured_at':'2026-11-15T01:00:00Z',
                'records':[], 'inventory':[inventory]}

    def test_inventory_survives_zero_prs_and_respects_repository_owner(self):
        graph=ga.audit([self.document()])
        self.assertTrue(any(n['id']=='repo:other/demo' for n in graph['nodes']))
        self.assertFalse(any('myon-bioinformatics/other/' in n['id'] for n in graph['nodes']))
        self.assertEqual(ga.plan(graph)['order'],[])
        self.assertFalse(any(e['relation']=='same_as' for e in graph['edges']))
        self.assertTrue(set('depends_on duplicates updates verified_by derived_from targets blocks integrates_into same_as supersedes has_status'.split())<=set(graph['ontology']['relations']))
        self.assertTrue(set('Repository PullRequest Issue Review ActionsRun Job Commit Branch File FixedSHA GeneratedArtifact Evidence Observation Task Snapshot'.split())<=set(graph['ontology']['classes']))

    def test_unknown_run_sha_and_attempt_are_never_inferred_from_main(self):
        graph=ga.audit([self.document()]);run=next(n for n in graph['nodes'] if n['type']=='ActionsRun')
        self.assertIsNone(run['attempt'])
        self.assertFalse(any(e['source']==run['id'] and e['relation']=='runsAt' for e in graph['edges']))
        self.assertNotIn('conclusion',run)
        self.assertEqual(next(e for e in graph['edges'] if e['relation']=='hasRun')['conclusion'],'failure')

    def test_inventory_history_ignores_only_time_and_reports_run_changes(self):
        import copy
        first=self.document();later=copy.deepcopy(first);later['captured_at']='2026-11-15T02:00:00Z'
        before=ga.audit([first]);self.assertFalse(ga.observation_diff(before,ga.audit([later]))['changed'])
        later['inventory'][0]['main_runs'][0]['conclusion']='success'
        after=ga.audit([later]);diff=ga.observation_diff(before,after)
        self.assertEqual([r['pr'] for r in diff['changed']],['repo:other/demo'])
        history=ga.audit([first,later])
        self.assertEqual({e['conclusion'] for e in history['edges'] if e['relation']=='hasRun'},{'failure','success'})

    def test_inventory_issue_pins_artifacts_and_actual_run_sha(self):
        run={'id':7,'run_attempt':2,'name':'CI','head_sha':'b'*40,'conclusion':'failure',
             'jobs':[{'id':8,'name':'test','conclusion':'failure'}],
             'artifacts':[{'id':9,'name':'report','workflow_run':{'head_sha':'b'*40}}]}
        doc=self.document(issues=[{'url':'https://github.com/other/demo/issues/1','title':'Issue'}],
                          pin_records=[{'repository':'other/source','commit':'c'*40}],main_runs=[run])
        graph=ga.audit([doc]);kinds={n['type'] for n in graph['nodes']}
        self.assertTrue({'Issue','FixedSHA','GeneratedArtifact','Job'}<=kinds)
        byid={n['id']:n for n in graph['nodes']}
        self.assertEqual({byid[e['target']]['sha'] for e in graph['edges'] if e['relation']=='runsAt'},{'b'*40})
        self.assertEqual(ga.audit([doc,doc]),graph)

    def test_closed_unmerged_is_excluded_from_integration_order(self):
        graph=ga.audit([snapshot(row(1,github_state='closed',merged=False,contained_in_main=False))])
        self.assertFalse(ga.plan(graph)['order'])


class TransferLedgerTests(unittest.TestCase):
    def example(self):
        return json.loads((Path(__file__).resolve().parents[1]/'examples/flutter-absorption.json').read_text())

    def completed(self):
        doc=self.example();doc['transfers']=doc['transfers'][:1];row=doc['transfers'][0]
        row['state']='完了';row['target'].update(sha='b'*40,paths=['tools/maps.py'])
        row['verification']={'source_sha':row['source']['sha'],'target_sha':'b'*40,'target_in_main':True,
                             'accepted':[c['id'] for c in row['acceptance']],
                             'evidence_url':'https://github.com/'+row['target']['repository']+'/actions/runs/42'}
        return doc

    def test_partial_inventory_remains_unknown_and_requests_are_separate(self):
        report=ga.transfer_report(self.example())
        self.assertEqual(len(report['records']),14)
        self.assertEqual(len(report['unabsorbed_features']),12)
        self.assertEqual(report['archive_readiness'],'未確定')
        self.assertEqual(report['counts']['完了'],0)

    def test_completion_needs_same_source_target_main_and_all_criteria(self):
        import copy
        good=self.completed();self.assertEqual(ga.transfer_report(good)['pending'],[])
        for change in ({'source_sha':'c'*40},{'target_sha':'c'*40},{'target_in_main':False},
                       {'accepted':[]},{'evidence_url':'https://github.com/other/repo/actions/runs/42'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                bad=copy.deepcopy(good);bad['transfers'][0]['verification'].update(change);ga.transfer_report(bad)

    def test_new_task_graph_preserves_archived_source_file_and_destination(self):
        doc=self.example();doc['transfer_scope']['source_archived_observed']=True
        graph=ga.audit([doc]);self.assertEqual(ga.plan(graph)['order'],[])
        self.assertEqual(sum(n['type']=='Task' for n in graph['nodes']),14)
        self.assertTrue(any(e['relation']=='migration_source' for e in graph['edges']))
        self.assertTrue(any(e['relation']=='migration_target' for e in graph['edges']))
        self.assertFalse(any(e['relation']=='same_as' for e in graph['edges']))
        self.assertEqual(ga.audit([doc,doc]),graph)

    def test_transfer_diff_tracks_target_and_state_but_ignores_capture_time(self):
        import copy
        doc=self.example();later=copy.deepcopy(doc);later['captured_at']='2026-11-16T01:00:00Z'
        before=ga.audit([doc]);self.assertEqual(ga.observation_diff(before,ga.audit([later]))['changed'],[])
        later['transfers'][0]['state']='着手中'
        diff=ga.observation_diff(before,ga.audit([later]))
        self.assertEqual(len(diff['changed']),1)
        self.assertIn('flutter-maps-links',diff['changed'][0]['pr'])

    def test_duplicate_ids_and_unanchored_completion_are_rejected(self):
        doc=self.example();doc['transfers'].append(dict(doc['transfers'][0]))
        with self.assertRaises(ValueError):ga.transfer_report(doc)
        doc=self.completed();doc['transfers'][0]['target']['paths']=[]
        with self.assertRaises(ValueError):ga.transfer_report(doc)

    def test_transfers_cli_works_on_stdin_and_signals_pending(self):
        result=run_cli_command(Path(ga.__file__),'transfers','-',
                              python_options=('-S',),stdin=json.dumps(self.example()))
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertEqual(len(json.loads(result.stdout)['pending']),14)


class InventoryEvidenceTests(unittest.TestCase):
    def test_repository_observation_keeps_corpus_reference_separate_from_evidence_gaps(self):
        doc = snapshot()
        ref = {'run_id': 10, 'kind': 'errorr-corpus-reference', 'scope': 'run-reference-only',
               'evidence_url': 'https://github.com/myon-bioinformatics/demo/actions/runs/10'}
        doc['inventory'] = [{'repo': 'myon-bioinformatics/demo',
                             'main_runs': [dict(id=10, run_attempt=2, conclusion='success')],
                             'evidence': [ref],
                             'gaps': [dict(run_id=10, reason=kind)
                                      for kind in ('unavailable-endpoint', 'unlinked')]}]
        graph = ga.audit([doc])
        evidence, = (n for n in graph['nodes'] if n['type'] == 'Evidence')
        self.assertEqual(json.loads(evidence['detail']), ref)
        self.assertEqual({n['reason'] for n in graph['nodes'] if n['type'] == 'EvidenceGap'},
                         {'unavailable-endpoint', 'unlinked'})
        relation, = (e for e in graph['edges'] if e['target'] == evidence['id'])
        self.assertTrue(relation['source'].startswith('repository-observation:'))
        self.assertEqual(relation['relation'], 'hasEvidence')
        self.assertEqual([e['conclusion'] for e in graph['edges'] if e['relation'] == 'hasRun'], ['success'])
