import hashlib
import json
import unittest
from copy import deepcopy

from examples.kg_poc import FIXTURE, baseline, evaluate


class KgPocTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_bytes())

    def run_case(self, query, **overrides):
        case = next(c for c in self.fixture["cases"] if c["id"] == query)
        return baseline(self.fixture["nodes"], self.fixture["relationships"],
                        query, case["input"] | overrides)

    def test_original_contract(self):
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                         "d8e13b6618c9fccf1f028c1791ba32d111a8646abf0e2e6af2cf47482b92a021")
        before = deepcopy(self.fixture)
        rows = evaluate(self.fixture)
        self.assertEqual([r["id"] for r in rows], [f"Q{i:02d}" for i in range(1, 7)])
        for row in rows:
            with self.subTest(query=row["id"]):
                self.assertEqual(row["actual"], row["expected"])
        self.assertEqual(self.fixture, before)

    def test_unknown_and_leaf(self):
        self.assertEqual(self.run_case("Q01", caseId="missing")["decision"], "unknown")
        self.assertEqual(self.run_case("Q02", conceptId="missing")["decision"], "unknown")
        self.assertEqual(self.run_case("Q02", conceptId="C"), {"ancestors": []})

    def test_cycle(self):
        edge = {"id": "back", "type": "IS_A", "from": "C", "to": "A1"}
        self.assertEqual(self.run_case("Q02", addRelationships=[edge])["cycles"],
                         [["A1", "B", "C", "A1"]])

    def test_same_conclusion_and_unrelated_case(self):
        args = self.fixture["cases"][3]["input"]
        args["addNodes"][0]["label"] = "対象"
        self.assertEqual(self.run_case("Q04")["conflictingJudgments"], [])
        args["addNodes"][0]["label"] = "対象外"
        args["addNodes"].append({"id": "C2", "type": "Case"})
        args["addRelationships"][0]["from"] = "C2"
        self.assertEqual(self.run_case("Q04")["conflictingJudgments"], [])

    def test_zero_confidence_and_withdrawal(self):
        patch = [{"id": "J1", "confidence": 0}, {"id": "E1", "status": "withdrawn"}]
        result = self.run_case("Q05", patchNodes=patch, removeProperties=[])
        self.assertEqual(result["issues"], [{"id": "J1", "code": "no_active_evidence"}])
        self.assertEqual(result["historicalEvidence"], ["E1"])
        self.assertEqual(self.run_case("Q06", patchNodes=patch)["citationIds"], [])

    def test_citation_requires_path_and_allowlist(self):
        before = deepcopy(self.fixture)
        self.assertEqual(self.run_case("Q06", knownEvidenceIds=["absent"])["citationIds"], [])
        self.assertEqual(self.fixture, before)
        self.fixture["relationships"].pop()
        self.assertEqual(self.run_case("Q06")["citationIds"], [])
