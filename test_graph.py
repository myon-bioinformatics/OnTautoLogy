"""Tests for the generic graph helpers ported from the parent fleet_records / vendor_fleet_plan."""
import unittest

from graph import relation_cycles, topological_order


class RelationCyclesTests(unittest.TestCase):
    def test_parent_cycle_is_reported_and_an_acyclic_branch_is_omitted(self):
        # Same assertion as fleet_records.ShapesCyclesLimits.test_cycles_are_reported_and_the_rest_is_still_walked
        # (the walk of the remainder stays in the parent as impact/why).
        relations = [{"kind": "derived_from", "source": "a:x", "target": "a:y", "lock": "a:r"},
                     {"kind": "derived_from", "source": "a:y", "target": "a:x", "lock": "a:r"},
                     {"kind": "derived_from", "source": "b:p", "target": "b:q", "lock": "b:r"}]
        self.assertEqual(relation_cycles(relations), [["a:x", "a:y", "a:x"]])

    def test_empty_and_a_chain_have_no_cycle(self):
        self.assertEqual(relation_cycles([]), [])
        chain = [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]
        self.assertEqual(relation_cycles(chain), [])

    def test_self_loop_and_limit(self):
        self.assertEqual(relation_cycles([{"source": "x", "target": "x"}]), [["x", "x"]])
        edges = ([{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]
                 + [{"source": "c", "target": "d"}, {"source": "d", "target": "c"}]
                 + [{"source": "e", "target": "f"}, {"source": "f", "target": "e"}])
        found = relation_cycles(edges, limit=2)
        self.assertEqual(len(found), 2)
        self.assertTrue(all(c[0] == c[-1] for c in found))


class TopologicalOrderTests(unittest.TestCase):
    def test_sources_precede_targets(self):
        edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]
        result = topological_order(edges)
        self.assertIsNone(result["cycle"])
        self.assertEqual(result["order"], ["a", "b", "c"])

    def test_diamond_includes_every_node_once(self):
        edges = [{"source": "a", "target": "b"}, {"source": "a", "target": "c"},
                 {"source": "b", "target": "d"}, {"source": "c", "target": "d"}]
        result = topological_order(edges)
        self.assertIsNone(result["cycle"])
        order = result["order"]
        self.assertEqual(sorted(order), ["a", "b", "c", "d"])
        self.assertLess(order.index("a"), order.index("b"))
        self.assertLess(order.index("a"), order.index("c"))
        self.assertLess(order.index("b"), order.index("d"))
        self.assertLess(order.index("c"), order.index("d"))

    def test_cycle_clears_the_order(self):
        edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]
        result = topological_order(edges)
        self.assertEqual(result["order"], [])
        self.assertTrue(result["cycle"])
        self.assertEqual(result["cycle"][0], result["cycle"][-1])


if __name__ == "__main__":
    unittest.main()
