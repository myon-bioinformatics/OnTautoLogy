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
        self.assertEqual(next(n for n in graph["nodes"] if n["type"] == "WorkflowRun")["observed_head_sha"], None)

    def test_run_sha_and_attempt_are_evidence_not_assumptions(self):
        row = item("a", 1, [])
        row["runs"]["workflow_runs"] = [
            {"id": 7, "run_attempt": 1, "head_sha": "old", "conclusion": "success"},
            {"id": 7, "run_attempt": 2, "head_sha": "abc", "conclusion": "failure"},
            {"id": 8, "conclusion": "success"},
        ]
        runs = [n for n in build_graph({"result": [row]})["nodes"] if n["type"] == "WorkflowRun"]
        self.assertEqual([n["matches_current_head"] for n in runs], [False, True, None])
        self.assertEqual([n["attempt"] for n in runs], [1, 2, None])
        self.assertEqual(len({n["id"] for n in runs}), 3)

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


if __name__ == "__main__":
    unittest.main()
