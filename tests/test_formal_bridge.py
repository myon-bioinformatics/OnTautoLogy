"""Connect the Lean finite truth-table model to the actual public rule checks.

The independent oracle is set algebra over integer-enumerated assignments.
These finite tests do not prove the Python parser or evaluator correct for all
formulas. Run with: python -S -m unittest discover -s tests -p test_formal_bridge.py
"""

import itertools
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ontautology as ot
from tools import tautology


def rows(names):
    """Same feature order, independently generated without itertools.product."""
    return [frozenset(name for i, name in enumerate(names)
                      if mask & (1 << (len(names) - 1 - i)))
            for mask in range(2 ** len(names))]


def support(rule):
    if isinstance(rule, str):
        return {rule}
    return set().union(*(support(child) for child in rule[1:]))


def truth_set(rule, universe):
    """Interpret a rule by intersections, unions and relative complements."""
    if isinstance(rule, str):
        return frozenset(row for row in universe if rule in row)
    operator, *children = rule
    values = [truth_set(child, universe) for child in children]
    if operator == "NOT":
        return universe - values[0]
    if operator in ("AND", "NAND"):
        result = universe.intersection(*values)
    else:
        result = frozenset().union(*values)
    return universe - result if operator in ("NAND", "NOR") else result


def rule_cases():
    seeds = ["p", "q", ["AND"], ["OR"], ["NOT", "p"], ["NOT", "q"]]
    candidates = seeds + [["NAND"], ["NOR"]] + [["NOT", rule] for rule in seeds]
    candidates += [[operator, left, right] for operator in ("AND", "OR", "NAND", "NOR")
                   for left, right in itertools.product(seeds, repeat=2)]
    candidates += [
        ["AND", "p", "q", ["NOT", "p"]],
        ["OR", "p", "q", ["NOT", "p"]],
        ["AND", ["OR", "p", "q"], ["NAND", "p", "q"]],
        ["NOT", ["AND", ["OR", "p", "q"], ["NAND", "p", "q"]]],
        ["OR", ["AND", "p", ["NOT", "q"]], ["AND", "q", ["NOT", "p"]]],
        ["NOT", ["AND", ["NOT", "p"], ["NOT", "q"]]],
        ["NOT", ["OR", ["NOT", "p"], ["NOT", "q"]]],
    ]
    unique = {json.dumps(rule): rule for rule in candidates}
    universe = frozenset(rows(("p", "q")))
    return [(rule, support(rule), truth_set(rule, universe)) for rule in unique.values()]


class TruthTableBridge(unittest.TestCase):
    def test_exhaustive_assignments_include_the_empty_assignment(self):
        for size in range(7):
            names = [f"feature-{i}" for i in range(size)]
            with self.subTest(features=size):
                actual = list(ot._assignments(names, limit=size))
                self.assertEqual(actual, rows(names))
                self.assertEqual(len({frozenset(row) for row in actual}), 2 ** size)

    def test_formula_semantics_classification_and_witnesses(self):
        cases = rule_cases()
        # Include every Boolean function of the two features, while exercising
        # multiple syntactic forms of each function.
        self.assertEqual(len({accepted for _, _, accepted in cases}), 16)
        for rule, names, accepted in cases:
            with self.subTest(rule=rule):
                assignments = rows(sorted(names))
                yes = next((sorted(row) for row in assignments if row in accepted), None)
                no = next((sorted(row) for row in assignments if row not in accepted), None)
                for row in rows(("p", "q")):
                    self.assertEqual(ot.holds(rule, row), row in accepted)
                expected = "tautology" if no is None else "contradiction" if yes is None else "contingent"
                self.assertEqual(ot.classify(rule), {"verdict": expected, "atoms": sorted(names),
                                                   "true_witness": yes, "false_witness": no})

    def test_all_rule_pairs_agree_with_set_equivalence(self):
        cases = rule_cases()
        for left_index, (left, left_names, in_left) in enumerate(cases):
            for right_index, (right, right_names, in_right) in enumerate(cases):
                with self.subTest(left=left_index, right=right_index):
                    names = sorted(left_names | right_names)
                    difference = in_left ^ in_right
                    witness = next((sorted(row) for row in rows(names) if row in difference), None)
                    result = tautology.equivalent(left, right)
                    self.assertEqual(result, {"equivalent": not difference, "counterexample": witness,
                                              "atoms": names, "basis": "hypothesis" if difference else "proof"})
                    if witness is not None:
                        self.assertNotEqual(ot.holds(left, witness), ot.holds(right, witness))

    def test_all_rule_pairs_keep_inconsistency_distinct_from_entailment(self):
        cases = rule_cases()
        for left_index, (premise, premise_names, supported) in enumerate(cases):
            for right_index, (conclusion, conclusion_names, accepted) in enumerate(cases):
                with self.subTest(premise=left_index, conclusion=right_index):
                    names = sorted(premise_names | conclusion_names)
                    refuted = supported - accepted
                    witness = next((sorted(row) for row in rows(names) if row in refuted), None)
                    expected = "counterexample" if refuted else "entailed" if supported else "inconsistent-premises"
                    result = ot.entailment([premise], conclusion)
                    self.assertEqual(result, {"verdict": expected, "atoms": names, "counterexample": witness})
                    if witness is not None:
                        self.assertTrue(ot.holds(premise, witness))
                        self.assertFalse(ot.holds(conclusion, witness))

    def test_compound_premises_are_scoped_to_the_inference(self):
        implication = ["OR", ["NOT", "p"], "q"]
        self.assertEqual(ot.entailment([implication, "p"], "q")["verdict"], "entailed")
        converse = ot.entailment([implication, "q"], "p")
        self.assertEqual(converse["counterexample"], ["q"])
        self.assertEqual(ot.entailment(["p", ["NOT", "p"]], "q")["verdict"],
                         "inconsistent-premises")
        # Agreement on one observed row must not become truth-table equivalence.
        self.assertEqual(ot.holds("p", {"p", "q"}), ot.holds("q", {"p", "q"}))
        self.assertFalse(tautology.equivalent("p", "q")["equivalent"])

    def test_empty_witness_is_not_absence_of_a_counterexample(self):
        self.assertEqual(tautology.equivalent(["AND"], ["OR"])["counterexample"], [])
        self.assertEqual(ot.entailment([], "p")["counterexample"], [])
        self.assertEqual(ot.entailment([], ["AND"])["verdict"], "entailed")
        self.assertEqual(ot.entailment([["OR"]], ["AND"])["verdict"], "inconsistent-premises")

    def test_limits_refuse_incomplete_search_instead_of_reporting_success(self):
        checks = [
            lambda: ot.classify(["OR", "p", "q"], limit=1),
            lambda: tautology.equivalent("p", "q", limit=1),
            lambda: ot.entailment(["p"], "q", limit=1),
        ]
        for check in checks:
            with self.assertRaisesRegex(ValueError, "truth-table limit"):
                check()


if __name__ == "__main__":
    unittest.main()
