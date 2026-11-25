import unittest

from ontautology_shared.predicate_logic import (
    FiniteModel, const, free_variables, func, pred, substitute,
    universal_closure, var,
)


class TestPredicateLogic(unittest.TestCase):
    def setUp(self):
        self.model = FiniteModel((0, 1), constants={"zero": 0},
                                 functions={"flip": lambda x: 1 - x},
                                 predicates={"P": lambda x: x == 1})

    def test_free_variables(self):
        self.assertEqual(free_variables(("forall", "x", pred("R", var("x"), var("y")))), {"y"})

    def test_capture(self):
        original = ("forall", "y", pred("R", var("x"), var("y")))
        result = substitute(original, "x", var("y"))
        self.assertEqual(result, ("forall", "y_0", pred("R", var("y"), var("y_0"))))
        self.assertEqual(free_variables(result), {"y"})

    def test_shadowing(self):
        formula = ("forall", "x", pred("P", var("x")))
        self.assertEqual(substitute(formula, "x", const("zero")), formula)

    def test_fresh_name_collision(self):
        formula = ("forall", "y", ("exists", "y_0", pred("R", var("x"), var("y"))))
        self.assertEqual(substitute(formula, "x", var("y"))[1], "y_1")

    def test_nested_shadowing(self):
        formula = ("forall", "y", ("and", pred("R", var("x"), var("y")),
                                    ("exists", "y", pred("P", var("y")))))
        result = substitute(formula, "x", var("y"))
        self.assertEqual(result[2][2], formula[2][2])
        self.assertEqual(free_variables(result), {"y"})

    def test_closure(self):
        self.assertEqual(free_variables(universal_closure(pred("R", var("a"), var("b")))), set())

    def test_quantifiers(self):
        self.assertFalse(self.model.evaluate(("forall", "x", pred("P", var("x")))))
        self.assertTrue(self.model.evaluate(("exists", "x", pred("P", var("x")))))

    def test_functions(self):
        self.assertTrue(self.model.evaluate(pred("P", func("flip", const("zero")))))

    def test_equality_and_connectives(self):
        t = ("eq", const("zero"), const("zero"))
        f = ("not", t)
        for op, expected in (("and", False), ("or", True), ("implies", False), ("iff", False)):
            self.assertEqual(self.model.evaluate((op, t, f)), expected)

    def test_counterexample(self):
        self.assertEqual(self.model.counterexample(pred("P", var("x"))), {"x": 0})
        self.assertIsNone(self.model.counterexample(("true",)))
        self.assertEqual(self.model.counterexample(("false",)), {})

    def test_missing_symbol(self):
        with self.assertRaises(KeyError):
            self.model.evaluate(("or", ("true",), pred("missing")))

    def test_missing_assignment(self):
        with self.assertRaises(KeyError):
            self.model.evaluate(pred("P", var("x")))

    def test_empty_domain(self):
        with self.assertRaises(ValueError):
            FiniteModel(())

    def test_outside_domain(self):
        with self.assertRaises(ValueError):
            self.model.evaluate(pred("P", var("x")), {"x": 2})
        with self.assertRaises(ValueError):
            FiniteModel((0,), constants={"bad": 1})

    def test_invalid_formula(self):
        with self.assertRaises(ValueError):
            self.model.evaluate(("not",))
        with self.assertRaises(ValueError):
            self.model.evaluate(("and", ("true",), var("x")))

    def test_substitution_semantics(self):
        formula = ("exists", "y", ("eq", var("x"), var("y")))
        replacement = func("flip", var("y"))
        for y in self.model.domain:
            self.assertEqual(self.model.evaluate(substitute(formula, "x", replacement), {"y": y}),
                             self.model.evaluate(formula, {"x": 1-y}))


if __name__ == "__main__":
    unittest.main()
