"""Generic graph algorithms: behavior, CLI, mutations, and full branch coverage."""
import contextlib
import dis
import functools
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from vendor.cli_args import run_cli  # noqa: E402

_TARGET = str((ROOT / "ontautology_graphs.py").resolve())
_SEEN_LINES = set()
_SEEN_ARCS = set()
_PENDING = {}
_COVER_DIR = Path(tempfile.mkdtemp(prefix="ontautology-graphs-cover-"))
_JUMP_PREFIXES = (
    "POP_JUMP_IF_",
    "POP_JUMP_FORWARD_IF_",
    "POP_JUMP_BACKWARD_IF_",
    "JUMP_IF_",
)
_UNTRACED_OPS = {"CACHE", "END_FOR", "EXTENDED_ARG", "RESUME"}
_PREVIOUS = sys.gettrace()
_realpath = functools.lru_cache(maxsize=None)(os.path.realpath)  # ⚡ one realpath per file, not one per traced call (the hook runs on every call of every test)


def _conditional(opname):
    return opname == "FOR_ITER" or opname.startswith(_JUMP_PREFIXES)


def _qual(code):
    return f"{code.co_firstlineno}:{code.co_qualname}"


def _hook(frame, event, arg):
    if _realpath(frame.f_code.co_filename) != _TARGET:
        if _PREVIOUS is not None:
            return _PREVIOUS(frame, event, arg)
        return None
    frame.f_trace_opcodes = True
    if event == "line":
        _SEEN_LINES.add(frame.f_lineno)
    elif event == "opcode":
        code = frame.f_code
        key = id(frame)
        offset = frame.f_lasti
        pending = _PENDING.get(key)
        if pending is not None:
            _SEEN_ARCS.add((pending[0], pending[1], offset))
            del _PENDING[key]
        real = offset
        name = dis.opname[code.co_code[real]]
        while name == "EXTENDED_ARG":
            real += 2
            name = dis.opname[code.co_code[real]]
        if _conditional(name):
            _PENDING[key] = (_qual(code), real)
    elif event == "return":
        _PENDING.pop(id(frame), None)
    return _hook


sys.settrace(_hook)
import ontautology_graphs as graphs  # noqa: E402


def edge(kind, source, target, **more):
    return {"kind": kind, "source": source, "target": target, **more}


def graph_of(edges, nodes=None):
    body = {"edges": edges}
    if nodes is not None:
        body["nodes"] = nodes
    return body


def invoke(argv, stdin=b""):
    stdout, stderr = io.StringIO(), io.StringIO()
    wrapper = io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        with patch.object(sys, "stdin", wrapper):
            code = graphs.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


def write_json(folder, name, body):
    path = Path(folder) / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def reachable(edges, roots, skip=None):
    outward = {}
    for item in edges:
        outward.setdefault(item["source"], set()).add(item["target"])
    seen, stack = set(), [root for root in roots if root != skip]
    while stack:
        node = stack.pop()
        if node == skip or node in seen:
            continue
        seen.add(node)
        for nxt in outward.get(node, ()):
            if nxt != skip and nxt not in seen:
                stack.append(nxt)
    return seen


def naive_idom(edges, roots):
    base = reachable(edges, roots)
    found = {}
    for node in base:
        strict = [cand for cand in base if cand != node and node not in reachable(edges, roots, skip=cand)]
        immediate = None
        for cand in strict:
            if all(cand not in reachable(edges, roots, skip=other) for other in strict if other != cand):
                immediate = cand
        found[node] = immediate
    return found


def component_count(edges, skip=None):
    adjacent = {}
    for item in edges:
        source, target = item["source"], item["target"]
        adjacent.setdefault(source, set())
        if source == target:
            continue
        adjacent.setdefault(target, set())
        adjacent[source].add(target)
        adjacent[target].add(source)
    seen, count = set(), 0
    for start in adjacent:
        if start == skip or start in seen:
            continue
        count += 1
        stack = [start]
        seen.add(start)
        while stack:
            node = stack.pop()
            for nxt in adjacent[node]:
                if nxt != skip and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
    return count


def naive_articulation(edges):
    nodes = set()
    for item in edges:
        nodes.add(item["source"])
        nodes.add(item["target"])
    base = component_count(edges)
    return sorted(node for node in nodes if component_count(edges, skip=node) > base)


def _cycle_signature(result):
    return (
        result["independent_cycles"],
        result["counts"],
        [(cycle["labels"], [(edge["kind"], edge["source"], edge["target"]) for edge in cycle["edges"]])
         for cycle in result["cycles"]],
    )


def assert_closed_walk(cycle):
    """Each cycle's edges are one undirected closed walk, in order."""
    edges = cycle["edges"]
    first = edges[0]

    def follow(here, edge):
        if edge["source"] == here:
            return edge["target"]
        if edge["target"] == here:
            return edge["source"]
        return None

    closed = False
    for start, nxt in ((first["source"], first["target"]), (first["target"], first["source"])):
        here, ok = nxt, True
        for edge in edges[1:]:
            here = follow(here, edge)
            if here is None:
                ok = False
                break
        if ok and here == start:
            closed = True
            break
    if not closed:
        raise AssertionError(cycle["indices"])


def independent_masks(cycles, width):
    rows = []
    for cycle in cycles:
        mask = 0
        for index in cycle["indices"]:
            mask ^= 1 << index
        rows.append(mask)
    rank = 0
    for column in range(width):
        bit = 1 << column
        pivot = next((index for index in range(rank, len(rows)) if rows[index] & bit), None)
        if pivot is None:
            continue
        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        for index, row in enumerate(rows):
            if index != rank and row & bit:
                rows[index] ^= rows[rank]
        rank += 1
    return rank


_REVISION_EDGES = [
    ["n3", "n0"], ["n2", "n4"], ["n3", "n3"], ["n2", "n3"], ["n2", "n4"], ["n1", "n4"],
    ["n1", "n2"], ["n1", "n0"], ["n4", "n2"], ["n4", "n5"], ["n4", "n1"], ["n2", "n0"],
    ["n5", "n0"], ["n5", "n2"], ["n3", "n4"], ["n0", "n2"], ["n3", "n2"], ["n4", "n5"],
    ["n1", "n4"], ["n3", "n3"], ["n4", "n2"], ["n0", "n4"], ["n0", "n0"], ["n5", "n3"],
    ["n5", "n5"], ["n5", "n0"], ["n4", "n3"], ["n2", "n1"], ["n5", "n2"], ["n5", "n0"],
]


class CollapseTests(unittest.TestCase):
    def test_mutual_pairs_fold_and_directed_pairs_stay(self):
        edges = [
            edge("similarTo", "b", "a", note="rev"),
            edge("similarTo", "a", "b", note="fwd"),
            edge("dependsOn", "a", "b"),
            edge("dependsOn", "b", "a"),
            edge("similarTo", "a", "a"),
            edge("similarTo", "b", "a", note="extra-rev"),
        ]
        found = graphs.collapse_reciprocal(edges, {"similarTo": "mutual", "dependsOn": "forward"})
        self.assertEqual(found["counts"], {"collapsed_edges": 4, "edges": 6})
        kept = found["edges"]
        self.assertEqual([item["kind"] for item in kept], ["dependsOn", "dependsOn", "similarTo", "similarTo"])
        similar = [item for item in kept if item["kind"] == "similarTo"]
        self.assertEqual(similar[0], edge("similarTo", "a", "a"))
        self.assertEqual(similar[1]["note"], "fwd")
        again = graphs.collapse_reciprocal(list(reversed(edges)), {"similarTo": "undirected", "dependsOn": "directed"})
        self.assertEqual(again["edges"], kept)

    def test_a_single_direction_is_kept_whichever_way_it_points(self):
        low = graphs.collapse_reciprocal([edge("similarTo", "a", "b")], {"similarTo": "mutual"})
        high = graphs.collapse_reciprocal([edge("similarTo", "b", "a")], {"similarTo": "undirected"})
        self.assertEqual(low["counts"]["collapsed_edges"], 1)
        self.assertEqual(high["edges"], [edge("similarTo", "b", "a")])
        multi = graphs.collapse_reciprocal(
            [edge("similarTo", "a", "b", note="keep"), edge("similarTo", "b", "a"), edge("similarTo", "b", "a", note="extra")],
            {"similarTo": "mutual"},
        )
        self.assertEqual(multi["counts"], {"collapsed_edges": 1, "edges": 3})
        self.assertEqual(multi["edges"], [edge("similarTo", "a", "b", note="keep")])
        plain = graphs.collapse_reciprocal(
            [edge("dependsOn", "b", "a"), edge("dependsOn", "a", "b")], {},
        )
        self.assertEqual(plain["counts"]["collapsed_edges"], 2)

    def test_bad_directions_and_edges_are_refused(self):
        good = [edge("k", "a", "b")]
        samples = [
            ([good, []], "directions must be an object"),
            (["nope", {}], "edges must be a list"),
            ([good, {"": "mutual"}], "direction keys"),
            ([good, {1: "mutual"}], "direction keys"),
            ([good, {"k": "sideways"}], "unknown direction"),
            ([["k"], {}], "an edge must be an object"),
            ([[{"kind": "k", "source": "a"}], {"k": "mutual"}], "endpoints"),
            ([[{"kind": "k", "source": "", "target": "b"}], {}], "endpoints"),
            ([[{"kind": "k", "source": 1, "target": "b"}], {}], "endpoints"),
            ([[{"kind": "k", "source": "a", "target": ""}], {}], "endpoints"),
            ([[{"kind": "k", "source": "a", "target": 1}], {}], "endpoints"),
            ([[{"source": "a", "target": "b"}], {}], "relation"),
            ([[{"kind": "", "relation": "", "source": "a", "target": "b"}], {}], "relation"),
            ([[{"kind": 1, "source": "a", "target": "b"}], {}], "relation"),
            ([[{"kind": "k", "relation": "other", "source": "a", "target": "b"}], {}], "disagree"),
            ([[{"relation": "uses", "source": "a", "target": "b"}], {}], None),
            ([[{"kind": "uses", "relation": "uses", "source": "a", "target": "b"}], {}], None),
        ]
        for (edges, directions), message in samples:
            with self.subTest(message=message, edges=edges):
                if message is None:
                    found = graphs.collapse_reciprocal(edges, directions)
                    self.assertEqual(found["counts"]["edges"], 1)
                    continue
                with self.assertRaisesRegex(ValueError, message):
                    graphs.collapse_reciprocal(edges, directions)


class CycleTests(unittest.TestCase):
    def test_the_basis_matches_the_cyclomatic_count_and_keeps_labels(self):
        edges = [
            edge("dependsOn", "a", "b"),
            edge("blocks", "b", "c"),
            edge("dependsOn", "c", "a"),
            edge("dependsOn", "a", "a"),
            edge("blocks", "d", "e"),
        ]
        found = graphs.cycle_basis(graph_of(edges, nodes=["a", "lonely"]))
        self.assertEqual(found["counts"], {"components": 2, "edges": 5, "nodes": 5})
        self.assertEqual(found["independent_cycles"], 2)
        self.assertEqual([cycle["indices"] for cycle in found["cycles"]], [[1, 0, 2], [3]])
        self.assertEqual([cycle["labels"] for cycle in found["cycles"]], [["blocks", "dependsOn", "dependsOn"], ["dependsOn"]])
        for cycle in found["cycles"]:
            assert_closed_walk(cycle)
        self.assertEqual(independent_masks(found["cycles"], 5), 2)
        shuffled = graphs.cycle_basis(graph_of(list(reversed(edges)), nodes=["lonely", "a"]))
        self.assertEqual(_cycle_signature(shuffled), _cycle_signature(found))

    def test_reciprocal_pairs_are_a_2_cycle_until_they_are_collapsed(self):
        edges = [edge("similarTo", "a", "b"), edge("similarTo", "b", "a")]
        raw = graphs.cycle_basis(graph_of(edges))
        self.assertEqual(raw["independent_cycles"], 1)
        folded = graphs.collapse_reciprocal(edges, {"similarTo": "mutual"})
        quiet = graphs.cycle_basis(graph_of(folded["edges"]))
        self.assertEqual(quiet["independent_cycles"], 0)
        self.assertEqual(quiet["cycles"], [])
        tree = graphs.cycle_basis(graph_of([edge("k", "a", "b")]))
        self.assertEqual(tree["independent_cycles"], 0)
        empty = graphs.cycle_basis({"edges": []})
        self.assertEqual(empty["counts"], {"components": 0, "edges": 0, "nodes": 0})

    def test_parallel_edges_and_a_disconnected_cycle_are_independent(self):
        edges = [edge("k", "a", "b"), edge("k", "a", "b"), edge("m", "c", "d"), edge("m", "d", "c")]
        found = graphs.cycle_basis(graph_of(edges))
        self.assertEqual(found["independent_cycles"], 2)
        self.assertEqual(found["counts"]["components"], 2)
        self.assertEqual(independent_masks(found["cycles"], 4), 2)
        for cycle in found["cycles"]:
            assert_closed_walk(cycle)

    def test_random_graphs_keep_an_independent_basis(self):
        rng = random.Random(20261121)
        for trial in range(30):
            nodes = [f"n{i}" for i in range(rng.randrange(1, 7))]
            edges = [edge(rng.choice("km"), rng.choice(nodes), rng.choice(nodes)) for _ in range(rng.randrange(0, 10))]
            found = graphs.cycle_basis(graph_of(edges, nodes=nodes))
            adjacent = {}
            for item in edges:
                adjacent.setdefault(item["source"], set()).add(item["target"])
                adjacent.setdefault(item["target"], set()).add(item["source"])
            seen, components = set(), 0
            for start in adjacent:
                if start in seen:
                    continue
                components += 1
                stack = [start]
                seen.add(start)
                while stack:
                    node = stack.pop()
                    for nxt in adjacent[node]:
                        if nxt not in seen:
                            seen.add(nxt)
                            stack.append(nxt)
            formula = len(edges) - len(adjacent) + components
            self.assertEqual(found["independent_cycles"], formula, trial)
            self.assertEqual(len(found["cycles"]), formula, trial)
            for cycle in found["cycles"]:
                assert_closed_walk(cycle)
            if found["cycles"]:
                self.assertEqual(independent_masks(found["cycles"], len(edges)), formula, trial)
        chord = [
            edge("k", "a", "b"), edge("k", "b", "c"), edge("k", "c", "a"),
            edge("k", "a", "d"), edge("k", "d", "c"), edge("k", "b", "d"),
        ]
        chord_basis = _cycle_signature(graphs.cycle_basis(graph_of(chord)))
        for _ in range(8):
            rng.shuffle(chord)
            self.assertEqual(_cycle_signature(graphs.cycle_basis(graph_of(chord))), chord_basis)

    def test_a_graph_without_edges_is_refused(self):
        with self.assertRaisesRegex(ValueError, "edges list"):
            graphs.cycle_basis(["a"])
        with self.assertRaisesRegex(ValueError, "edges list"):
            graphs.cycle_basis({"nodes": []})


class FailureTests(unittest.TestCase):
    def assert_matches_removal(self, edges, roots, nodes=None):
        found = graphs.single_points_of_failure(graph_of(edges, nodes), roots)
        self.assertEqual({row["node"]: row["idom"] for row in found["dominators"]}, naive_idom(edges, roots))
        self.assertEqual(found["articulation_points"], naive_articulation(edges))
        base = reachable(edges, roots)
        for row in found["ranked"]:
            self.assertEqual(row["lost"], sorted(base - reachable(edges, roots, skip=row["node"])))
            self.assertEqual(row["unreachable"], len(row["lost"]))
        return found

    def test_dominators_articulation_and_rank_follow_removal(self):
        chain = self.assert_matches_removal(
            [edge("k", "a", "b"), edge("k", "b", "c")], ["a"], nodes=["a", "alone"],
        )
        self.assertEqual(chain["dominators"], [
            {"idom": None, "node": "a"}, {"idom": "a", "node": "b"}, {"idom": "b", "node": "c"},
        ])
        self.assertEqual(chain["articulation_points"], ["b"])
        self.assertEqual([row["node"] for row in chain["ranked"] if row["node"] != "alone"], ["a", "b", "c"])
        forward = [edge("k", "a", "b"), edge("k", "b", "c")]
        backward = [edge("k", "b", "c"), edge("k", "a", "b")]
        self.assertEqual(
            graphs.single_points_of_failure(graph_of(forward), ["a"])["ranked"],
            graphs.single_points_of_failure(graph_of(backward), ["a"])["ranked"],
        )
        self.assertEqual([row for row in chain["ranked"] if row["node"] == "alone"][0]["unreachable"], 0)
        diamond = self.assert_matches_removal(
            [edge("k", "a", "b"), edge("k", "a", "c"), edge("k", "b", "d"), edge("k", "c", "d")], ["a"],
        )
        self.assertEqual({row["node"]: row["idom"] for row in diamond["dominators"]}["d"], "a")
        self.assertEqual(diamond["articulation_points"], [])
        star = self.assert_matches_removal([edge("k", "a", "b"), edge("k", "a", "c")], ["a"])
        self.assertEqual(star["articulation_points"], ["a"])
        two = self.assert_matches_removal([edge("k", "a", "c"), edge("k", "b", "c")], ("b", "a", "a"))
        self.assertEqual(two["roots"], ["a", "b"])
        self.assertIsNone(next(row["idom"] for row in two["dominators"] if row["node"] == "c"))
        loop = self.assert_matches_removal([edge("k", "a", "a")], ["a"])
        self.assertEqual(loop["articulation_points"], [])
        self.assertEqual(loop["ranked"][0]["unreachable"], 1)
        self.assert_matches_removal(
            [edge("k", "a", "b"), edge("k", "b", "c"), edge("k", "c", "d"), edge("k", "a", "d")], ["a"],
        )
        idom = {"a": "a", "b": "a", "c": "b", "d": "c"}
        index = {"a": 0, "b": 1, "c": 2, "d": 3}
        self.assertEqual(graphs._intersect("a", "a", idom, index), "a")
        self.assertEqual(graphs._intersect("a", "d", idom, index), "a")
        self.assertEqual(graphs._intersect("d", "a", idom, index), "a")

    def test_a_revision_and_random_graphs_agree_with_removal(self):
        revision = [edge("k", source, target) for source, target in _REVISION_EDGES]
        self.assert_matches_removal(revision, ["n0"])
        rng = random.Random(20261121)
        for trial in range(25):
            nodes = [f"n{i}" for i in range(rng.randrange(1, 7))]
            edges = [edge(rng.choice("km"), rng.choice(nodes), rng.choice(nodes)) for _ in range(rng.randrange(0, 9))]
            roots = [nodes[0]]
            if rng.random() < 0.5 and len(nodes) > 1:
                roots.append(rng.choice(nodes))
            with self.subTest(trial=trial):
                self.assert_matches_removal(edges, roots, nodes=nodes)

    def test_roots_and_nodes_are_validated(self):
        good = graph_of([edge("k", "a", "b")])
        for roots, message in (
            ("a", "roots must be a list"),
            ({"a": 1}, "roots must be a list"),
            ([], "at least one root"),
            ([""], "non-empty"),
            ([1], "non-empty"),
        ):
            with self.subTest(roots=roots):
                with self.assertRaisesRegex(ValueError, message):
                    graphs.single_points_of_failure(good, roots)
        with self.assertRaisesRegex(ValueError, "nodes must be a list"):
            graphs.single_points_of_failure({"edges": [], "nodes": "a"}, ["a"])
        for node in ({"name": "a"}, {"id": ""}, {"id": 1}, "", 1, None):
            with self.subTest(node=node):
                with self.assertRaisesRegex(ValueError, "node"):
                    graphs.single_points_of_failure({"edges": [], "nodes": [node]}, ["a"])
        found = graphs.single_points_of_failure(
            {"edges": [edge("k", "a", "b")], "nodes": ["a", {"id": "b"}, "a"]}, ["a"],
        )
        self.assertIn("b", {row["node"] for row in found["ranked"]})


class CoverTests(unittest.TestCase):
    def test_exact_cover_breaks_ties_lexicographically_and_lists_unique_elements(self):
        found = graphs.set_cover_min(
            ["b", "a", "c", "a"],
            {"m": ["a", "b", "z"], "z": ["a", "b"], "tail": ["c"], "empty": []},
        )
        self.assertEqual(found["method"], "exact")
        self.assertEqual(found["cover"], ["m", "tail"])
        self.assertTrue(found["complete"])
        self.assertEqual(found["uncovered"], [])
        self.assertEqual(found["unique"]["tail"], ["c"])
        self.assertEqual(found["unique"]["empty"], [])
        self.assertEqual(found["unique"]["z"], [])
        tied = graphs.set_cover_min(["a"], {"m": ["a"], "z": ["a"]})
        self.assertEqual(tied["cover"], ["m"])
        first = graphs.set_cover_min(["b", "a"], {"s": ["b", "a"]})
        second = graphs.set_cover_min(["a", "b"], {"s": ["a", "b"]})
        self.assertEqual(first["unique"], second["unique"])
        self.assertEqual(first["unique"]["s"], ["a", "b"])
        same = graphs.set_cover_min(["a"], {"m": ["a"], "z": ["a"]}, limit=None)
        self.assertEqual(same, tied)

    def test_an_incomplete_universe_is_reported_and_a_large_instance_is_greedy(self):
        partial = graphs.set_cover_min(["a", "missing"], {"only": ["a"]})
        self.assertEqual(partial["cover"], ["only"])
        self.assertEqual(partial["uncovered"], ["missing"])
        self.assertFalse(partial["complete"])
        universe = ["1", "2", "3", "4", "5", "6"]
        sets = {"A": ["1", "2", "3"], "B": ["4", "5", "6"], "C": ["2", "3", "4", "5"]}
        exact = graphs.set_cover_min(universe, sets, limit=3)
        greedy = graphs.set_cover_min(universe, sets, limit=2)
        self.assertEqual(exact["method"], "exact")
        self.assertEqual(exact["cover"], ["A", "B"])
        self.assertEqual(greedy["method"], "greedy")
        self.assertEqual(greedy["cover"], ["A", "B", "C"])
        self.assertGreater(greedy["size"], exact["size"])
        forced = graphs.set_cover_min(["a"], {"only": ["a"]}, limit=0)
        self.assertEqual(forced["method"], "greedy")
        self.assertEqual(forced["cover"], ["only"])
        idle = graphs.set_cover_min([], {"s": []}, limit=0)
        self.assertEqual(idle["cover"], [])
        skipped = graphs.set_cover_min(["a"], {"empty": [], "full": ["a"]}, limit=0)
        self.assertEqual(skipped["cover"], ["full"])
        stuck = graphs.set_cover_min(["a"], {"empty": []}, limit=0)
        self.assertEqual(stuck["uncovered"], ["a"])
        nothing = graphs.set_cover_min([], {})
        self.assertEqual(nothing, {
            "complete": True, "cover": [], "method": "exact", "size": 0, "uncovered": [], "unique": {},
        })
        universe = ["1", "2", "3", "4", "5", "6"]
        padded = {"A": ["1", "2", "3"], "B": ["4", "5", "6"], "C": ["2", "3", "4", "5"]}
        for index in range(15):
            padded[f"e{index:02d}"] = []
        self.assertEqual(len(padded), 18)
        at_limit = graphs.set_cover_min(universe, padded)
        self.assertEqual((at_limit["method"], at_limit["cover"]), ("exact", ["A", "B"]))
        padded["e15"] = []
        self.assertEqual(len(padded), 19)
        past_limit = graphs.set_cover_min(universe, padded)
        self.assertEqual((past_limit["method"], past_limit["cover"]), ("greedy", ["A", "B", "C"]))

    def test_bad_cover_inputs_are_refused(self):
        samples = [
            (("ab", {}), "universe must be a list"),
            ((["a"], []), "candidate_sets"),
            (([1], {}), "universe elements"),
            ((["a"], {"": ["a"]}), "set names"),
            ((["a"], {1: ["a"]}), "set names"),
            ((["a"], {"s": "a"}), "must list"),
            ((["a"], {"s": {"a": 1}}), "must list"),
            ((["a"], {"s": [1]}), "elements must be strings"),
            ((["a"], {"s": ["a"]}, True), "limit"),
            ((["a"], {"s": ["a"]}, False), "limit"),
            ((["a"], {"s": ["a"]}, -1), "limit"),
            ((["a"], {"s": ["a"]}, "2"), "limit"),
            ((None, {}), "universe must be a list"),
        ]
        for args, message in samples:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    graphs.set_cover_min(*args[:2], limit=args[2] if len(args) > 2 else None)


class NearTests(unittest.TestCase):
    def test_each_normalization_is_named_and_nothing_is_merged(self):
        nodes = ["dependsOn", "depends_on", "Repo.git", "repo", "Café", "Cafe\u0301", "/Path/", "path", "HTTPServer", "http_server"]
        relations = ["A", "a/", "keeps-hyphen", "keeps_hyphen"]
        original = (list(nodes), list(relations))
        found = graphs.near_duplicates(nodes, relations)
        self.assertEqual((nodes, relations), original)
        self.assertFalse(found["folded"])
        by_key = {tuple(group["ids"]): group["normalizations"] for group in found["nodes"]}
        self.assertEqual(by_key[("dependsOn", "depends_on")], ["camel_snake", "casefold"])
        self.assertEqual(by_key[("Repo.git", "repo")], ["git", "casefold"])
        self.assertEqual(by_key[("Cafe\u0301", "Café")], ["nfc", "casefold"])
        self.assertEqual(by_key[("HTTPServer", "http_server")], ["camel_snake", "casefold"])
        self.assertEqual(by_key[("/Path/", "path")], ["slash", "casefold"])
        relation_groups = {tuple(group["ids"]): group["normalizations"] for group in found["relations"]}
        self.assertEqual(relation_groups[("A", "a/")], ["slash", "casefold"])
        self.assertNotIn(("keeps-hyphen", "keeps_hyphen"), relation_groups)
        self.assertTrue(all(group["folded"] is False for group in found["nodes"] + found["relations"]))

    def test_shapes_that_are_not_duplicates_still_exercise_each_rule(self):
        names = ["HTTP", "a2B", "a-B", "_x", "depends_On", "Foo.GIT", "foo", "plain"]
        found = graphs.near_duplicates(names, ["dependsOn"])
        grouped = {tuple(group["ids"]) for group in found["nodes"]}
        self.assertIn(("Foo.GIT", "foo"), grouped)
        self.assertTrue(all("depends_On" not in group["ids"] or "plain" not in group["ids"] for group in found["nodes"]))
        self.assertEqual(found["relations"], [])
        separated = graphs.near_duplicates(["Case"], ["Case", "case"])
        self.assertEqual(separated["nodes"], [])
        self.assertEqual(separated["relations"][0]["ids"], ["Case", "case"])
        self.assertEqual(separated["relations"][0]["normalizations"], ["casefold"])

    def test_graph_names_keep_endpoints_and_relation_fields(self):
        nodes, relations = graphs.names_from_graph({
            "nodes": ["a", {"id": "b"}],
            "edges": [{"relation": "dependsOn", "source": "a", "target": "c"}],
        })
        self.assertEqual(nodes, ["a", "b", "c"])
        self.assertEqual(relations, ["dependsOn"])
        found = graphs.near_duplicates(nodes, relations)
        self.assertEqual(found["nodes"], [])

    def test_names_must_be_a_list_of_strings(self):
        with self.assertRaisesRegex(ValueError, "names must be a list"):
            graphs.near_duplicates("ab", [])
        with self.assertRaisesRegex(ValueError, "names must be a list"):
            graphs.near_duplicates(None, [])
        with self.assertRaisesRegex(ValueError, "non-empty"):
            graphs.near_duplicates([""], [])
        with self.assertRaisesRegex(ValueError, "non-empty"):
            graphs.near_duplicates([1], [])


class LagTests(unittest.TestCase):
    def test_commits_and_merges_after_the_pin_are_counted(self):
        pin = "a" * 40
        mid = "b" * 40
        merge = "c" * 40
        tip = "d" * 40
        chain = [
            {"sha": tip, "parents": [merge]},
            {"sha": merge, "parents": [mid, pin]},
            {"sha": mid, "parents": [pin]},
            {"sha": pin, "parents": []},
        ]
        self.assertEqual(graphs.first_parent_lag(chain, pin), {
            "commits": 3, "merges": 1, "pinned": pin, "tip": tip,
        })
        self.assertEqual(graphs.first_parent_lag(chain, tip)["commits"], 0)
        self.assertEqual(graphs.first_parent_lag(chain, tip)["merges"], 0)
        side = "e" * 40
        with self.assertRaisesRegex(ValueError, "not on the first-parent chain"):
            graphs.first_parent_lag(chain, side)
        with self.assertRaisesRegex(ValueError, "40 lowercase"):
            graphs.first_parent_lag(chain, None)

    def test_a_malformed_chain_is_refused(self):
        good = {"sha": "a" * 40, "parents": []}
        samples = [
            ("nope", "a" * 40, "empty"),
            ([], "a" * 40, "empty"),
            ([good], "aa", "40 lowercase"),
            ([good], "g" * 40, "40 lowercase"),
            ([good], "A" * 40, "40 lowercase"),
            ([1], "a" * 40, "object"),
            ([{"sha": "a" * 40, "parents": []}, good], "a" * 40, "duplicate"),
            ([{"sha": "b" * 40, "parents": "a"}], "b" * 40, "parents"),
            ([{"sha": "b" * 40, "parents": [1]}], "b" * 40, "parents"),
            ([{"sha": "b" * 40, "parents": [""]}], "b" * 40, "parents"),
        ]
        for chain, pinned, message in samples:
            with self.subTest(message=message, chain=chain):
                with self.assertRaisesRegex(ValueError, message):
                    graphs.first_parent_lag(chain, pinned)

    def history(self):
        folder = tempfile.TemporaryDirectory()
        repo = Path(folder.name)
        env = os.environ.copy()

        def git(*args):
            done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
            if done.returncode:
                raise AssertionError(done.stdout + done.stderr)
            return done.stdout.strip()

        git("init", "-b", "main")

        def commit(name, body):
            (repo / name).write_text(body, encoding="utf-8")
            git("add", name)
            git("-c", "user.name=Tester", "-c", "user.email=tester@example.com", "commit", "-m", name)
            return git("rev-parse", "HEAD")

        shas = {"a": commit("a.txt", "a\n"), "b": commit("b.txt", "b\n")}
        git("branch", "side")
        shas["c"] = commit("c.txt", "c\n")
        git("checkout", "side")
        shas["d"] = commit("d.txt", "d\n")
        git("checkout", "main")
        git("-c", "user.name=Tester", "-c", "user.email=tester@example.com", "merge", "--no-ff", "-m", "M", "side")
        shas["m"] = git("rev-parse", "HEAD")
        shas["e"] = commit("e.txt", "e\n")
        self.addCleanup(folder.cleanup)
        return repo, shas

    def test_local_first_parent_history_rejects_a_side_commit(self):
        repo, shas = self.history()
        after_c, digest = graphs.load_first_parent(str(repo), "main", shas["c"])
        self.assertEqual(after_c["commits"], 2)
        self.assertEqual(after_c["merges"], 1)
        self.assertEqual(after_c["pinned"], shas["c"])
        self.assertEqual(after_c["tip"], shas["e"])
        self.assertEqual(len(digest), 64)
        at_tip, _digest = graphs.load_first_parent(str(repo), "main", shas["e"])
        self.assertEqual((at_tip["commits"], at_tip["merges"]), (0, 0))
        short = graphs.load_first_parent(str(repo), "refs/heads/main", shas["a"][:12])
        self.assertEqual(short[0]["pinned"], shas["a"])
        self.assertGreater(short[0]["commits"], 0)
        with self.assertRaisesRegex(ValueError, "not on the first-parent chain"):
            graphs.load_first_parent(str(repo), "main", shas["d"])
        with self.assertRaisesRegex(ValueError, "not a git repository"):
            graphs.load_first_parent(str(repo / "a.txt"), "main", shas["e"])
        for value, message in (("", "repository path"), (1, "repository path")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, message):
                    graphs.load_first_parent(value, "main", shas["e"])
        with self.assertRaisesRegex(ValueError, "branch ref"):
            graphs.load_first_parent(str(repo), "", shas["e"])
        with self.assertRaisesRegex(ValueError, "branch ref"):
            graphs.load_first_parent(str(repo), None, shas["e"])
        with self.assertRaisesRegex(ValueError, "pinned sha"):
            graphs.load_first_parent(str(repo), "main", "")
        with self.assertRaisesRegex(ValueError, "pinned sha"):
            graphs.load_first_parent(str(repo), "main", None)
        with self.assertRaisesRegex(ValueError, "git exited 7"):
            with patch.object(graphs.subprocess, "run", return_value=subprocess.CompletedProcess([], 7, "", "")):
                graphs._git(repo, "rev-parse", "HEAD")
        with self.assertRaisesRegex(ValueError, "fatal|not a git"):
            graphs._git(Path(tempfile.gettempdir()), "rev-parse", "--verify", "definitely-missing")


class CliTests(unittest.TestCase):
    def sample(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        graph = write_json(folder.name, "graph.json", graph_of(
            [edge("similarTo", "b", "a"), edge("similarTo", "a", "b"), edge("dependsOn", "a", "c"),
             edge("dependsOn", "DependsOn", "c")],
            nodes=["/Repo.git/", "repo"],
        ))
        directions = write_json(folder.name, "directions.json", {"similarTo": "mutual", "dependsOn": "forward"})
        cover = write_json(folder.name, "cover.json", {"universe": ["a", "b"], "sets": {"s": ["a"], "t": ["b"]}})
        return Path(folder.name), graph, directions, cover

    def test_each_command_prints_provenance_in_text_and_json(self):
        folder, graph, directions, cover = self.sample()
        cases = [
            (["collapse", str(graph), str(directions)], "collapse", "collapsed_edges: 3"),
            (["basis", str(graph)], "basis", "cycle: 1"),
            (["cycle", str(graph)], "cycle", "cycle: a b a"),
            (["transitive", str(graph)], "transitive", "witness: b a c"),
            (["spof", str(graph), "a"], "spof", "dominator: a -"),
            (["cover", str(cover)], "cover", "complete: yes"),
            (["near", str(graph)], "near", "folded: no"),
        ]
        for argv, command, snippet in cases:
            with self.subTest(command=command):
                code, out, err = invoke(argv)
                self.assertEqual(code, 0, err)
                self.assertIn(f"tool: ontautology-graphs {graphs.__version__}", out)
                self.assertIn("sha256:", out)
                self.assertIn(snippet, out)
                code, raw, err = invoke([*argv, "--json"])
                self.assertEqual(code, 0, err)
                body = json.loads(raw)
                self.assertEqual(body["tool"], {"name": "ontautology-graphs", "version": graphs.__version__})
                self.assertEqual(body["command"], command)
                self.assertEqual(len(body["provenance"]["inputs"][0]["sha256"]), 64)
                self.assertEqual(raw, json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
                if command in ("collapse", "basis", "cycle", "near", "transitive"):
                    self.assertNotIn("parameters", body["provenance"])
                    self.assertNotIn("parameter:", out)
        code, collapse_text, err = invoke(["collapse", str(graph), str(directions)])
        self.assertEqual(code, 0, err)
        self.assertIn("edge: similarTo a b", collapse_text)
        self.assertIn("edge: dependsOn a c", collapse_text)
        code, spof_text, err = invoke(["spof", str(graph), "a"])
        self.assertEqual(code, 0, err)
        self.assertIn("parameter: roots a", spof_text)
        self.assertIn("articulation:", spof_text)
        self.assertIn("rank: a ", spof_text)
        code, cover_text, err = invoke(["cover", str(cover)])
        self.assertEqual(code, 0, err)
        self.assertIn("parameter: limit 18", cover_text)
        self.assertIn("unique: s a", cover_text)
        self.assertIn("unique: t b", cover_text)
        code, spof_raw, err = invoke(["spof", str(graph), "a", "--json"])
        self.assertEqual(json.loads(spof_raw)["provenance"]["parameters"], {"roots": "a"}, err)
        code, cover_raw, err = invoke(["cover", str(cover), "--json"])
        self.assertEqual(json.loads(cover_raw)["provenance"]["parameters"], {"limit": "18"}, err)
        partial = write_json(folder, "partial.json", {"universe": ["a", "b"], "sets": {"only": ["a"]}})
        code, out, err = invoke(["cover", str(partial)])
        self.assertEqual(code, 0, err)
        self.assertIn("complete: no", out)
        self.assertIn("uncovered: b", out)
        missing_sets = write_json(folder, "half.json", {"universe": ["a"]})
        code, out, err = invoke(["cover", str(missing_sets)])
        self.assertEqual(code, 1)
        self.assertIn("universe and sets", err)

    def test_json_sugar_output_files_and_input_errors(self):
        folder, graph, directions, cover = self.sample()
        code, out, err = invoke(["collapse", str(graph), str(directions), "--json", "--format", "json"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["result"]["counts"]["edges"], 4)
        code, out, err = invoke(["basis", str(graph), "--json", "--format", "text"])
        self.assertEqual(code, 1)
        self.assertIn("cannot be combined", err)
        target = folder / "out.txt"
        code, out, err = invoke(["near", str(graph), "-o", str(target)])
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "")
        self.assertIn("Repo.git", target.read_text(encoding="utf-8"))
        code, out, err = invoke(["collapse", "-", "-"])
        self.assertEqual(code, 1)
        self.assertIn("only once", err)
        code, out, err = invoke(["basis", "-"], b"\xff")
        self.assertEqual(code, 1)
        self.assertIn("not utf-8", err)
        code, out, err = invoke(["basis", "-"], b"{")
        self.assertEqual(code, 1)
        self.assertIn("not json", err)
        missing = folder / "missing.json"
        code, out, err = invoke(["basis", str(missing)])
        self.assertEqual(code, 1)
        self.assertIn("ontautology-graphs:", err)
        code, out, err = invoke(["cover", str(graph)])
        self.assertEqual(code, 1)
        self.assertIn("universe and sets", err)
        code, out, err = invoke(["cover", "-"], b"[1]")
        self.assertEqual(code, 1)
        self.assertIn("universe and sets", err)
        code, out, err = invoke(["spof", str(graph)])
        self.assertEqual(code, 1)
        self.assertIn("OTL_ROOTS", err)
        with patch.dict(os.environ, {"OTL_ROOTS": ",a,b,"}, clear=False):
            code, out, err = invoke(["spof", str(graph)])
        self.assertEqual(code, 0, err)
        self.assertIn("roots: a b", out)
        with patch.dict(os.environ, {"OTL_ROOTS": "z"}, clear=False):
            code, out, err = invoke(["spof", str(graph), "a", ""])
        self.assertEqual(code, 0, err)
        self.assertIn("dominator: a -", out)
        self.assertNotIn("dominator: z", out)
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                graphs.main(["basis"])
        with patch.object(Path, "read_bytes", return_value=None):
            with self.assertRaises(AttributeError):
                graphs._read_input(graph, "graph")
        with patch.object(graphs.json, "loads", side_effect=TypeError("boom")):
            with self.assertRaises(TypeError):
                graphs._read_input(graph, "graph")

    def test_lag_reads_args_or_environment_and_the_script_entrypoint(self):
        repo, shas = LagTests.history(self)
        code, out, err = invoke(["lag", "--repo", str(repo), "--ref", "main", "--sha", shas["c"], "--format", "text"])
        self.assertEqual(code, 0, err)
        self.assertIn("commits: 2", out)
        self.assertIn("merges: 1", out)
        self.assertIn(f"input: git {repo}", out)
        env = {
            "OTL_GIT_REPO": str(repo),
            "OTL_GIT_REF": "main",
            "OTL_GIT_SHA": shas["d"],
            "PATH": os.environ.get("PATH", ""),
        }
        with patch.dict(os.environ, env, clear=False):
            code, out, err = invoke(["lag", "--repo", "", "--sha", ""])
        self.assertEqual(code, 1)
        self.assertIn("not on the first-parent chain", err)
        with patch.dict(os.environ, {"OTL_GIT_REPO": str(repo), "OTL_GIT_SHA": shas["e"], "PATH": os.environ["PATH"]}, clear=False):
            code, out, err = invoke(["lag", "--ref", "main"])
        self.assertEqual(code, 0, err)
        self.assertIn("commits: 0", out)
        with patch.dict(os.environ, {}, clear=True):
            code, out, err = invoke(["lag"])
        self.assertEqual(code, 1)
        self.assertIn("OTL_GIT_REPO", err)
        script = str(ROOT / "ontautology_graphs.py")
        done = run_cli(
            script, "basis", str(repo / "a.txt"),
            python_options=("-S",),
        )
        self.assertEqual(done.returncode, 1)
        self.assertIn("ontautology-graphs:", done.stderr)
        payload = graph_of([edge("k", "a", "b")])
        shown = run_cli(
            script, "basis", "-", "--json",
            python_options=("-S",), stdin=json.dumps(payload),
        )
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(json.loads(shown.stdout)["result"]["independent_cycles"], 0)

    def test_the_module_stays_generic(self):
        source = (ROOT / "ontautology_graphs.py").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for banned in ("urllib", "socket", "requests", "gh_audit", "workflow_dispatch", "fetch("):
            self.assertNotIn(banned, source)
        self.assertIn("ontautology_graphs.py", readme)
        for command in ("collapse", "basis", "cycle", "transitive", "spof", "cover", "near", "lag"):
            self.assertIn(command, readme)


def diamond_chain(depth, b_before_a=False):
    edges = []
    for i in range(depth):
        left, right, nxt = f"n{i}", f"a{i}", f"n{i + 1}"
        other = f"b{i}"
        pair = [(left, other), (left, right)] if b_before_a else [(left, right), (left, other)]
        for source, target in pair:
            edges.append(edge("r", source, target))
        edges.append(edge("r", right, nxt))
        edges.append(edge("r", other, nxt))
    edges.append(edge("r", f"n{depth}", "n0"))
    return edges


def diamond_nodes(depth):
    nodes = ["a0"]
    for i in range(1, depth):
        nodes.append(f"n{i}")
        nodes.append(f"a{i}")
    nodes.append(f"n{depth}")
    nodes.append("n0")
    nodes.append("a0")
    return nodes


class WitnessTests(unittest.TestCase):
    def test_the_directed_witness_is_the_2_cycle_not_the_undirected_triangle(self):
        edges = [
            edge("k", "A", "C"),
            edge("k", "B", "C"),
            edge("k", "B", "A"),
            edge("k", "C", "A"),
        ]
        found = graphs.directed_cycle_witness(graph_of(edges))
        self.assertEqual(found["nodes"], ["A", "C", "A"])
        self.assertEqual(found["indices"], [0, 3])
        self.assertEqual(found["labels"], ["k", "k"])
        self.assertEqual([(item["source"], item["target"]) for item in found["edges"]], [("A", "C"), ("C", "A")])
        basis = graphs.cycle_basis(graph_of(edges))
        self.assertGreater(basis["independent_cycles"], 1)
        self.assertNotIn([0, 3], [cycle["indices"] for cycle in basis["cycles"] if len(cycle["indices"]) == 3])

    def test_shortest_cycle_beats_a_longer_one_and_parallel_edges_stay_directed(self):
        loop = edge("k", "a", "a")
        edges = [
            edge("k", "a", "b"), edge("k", "b", "c"), edge("k", "c", "a"), loop,
        ]
        found = graphs.directed_cycle_witness(graph_of(edges))
        self.assertEqual(found["nodes"], ["a", "a"])
        self.assertEqual(found["indices"], [3])
        later = [
            edge("k", "a", "b"), edge("k", "b", "a"), edge("k", "z", "z"),
        ]
        shortened = graphs.directed_cycle_witness(graph_of(later))
        self.assertEqual(shortened["nodes"], ["z", "z"])
        self.assertEqual(shortened["indices"], [2])
        same_way = [edge("k", "a", "b"), edge("k", "a", "b")]
        self.assertIsNone(graphs.directed_cycle_witness(graph_of(same_way)))
        paired = same_way + [edge("k", "b", "a")]
        closed = graphs.directed_cycle_witness(graph_of(paired))
        self.assertEqual(closed["indices"], [0, 2])
        self.assertEqual(closed["nodes"], ["a", "b", "a"])
        marked = [edge("k", "a", "b"), edge("m", "a", "b"), edge("k", "b", "a")]
        preferred = graphs.directed_cycle_witness(graph_of(marked))
        self.assertEqual(preferred["indices"], [0, 2])
        self.assertEqual(preferred["labels"], ["k", "k"])

    def test_equal_cycles_break_ties_by_the_rotated_edge_key(self):
        edges = [
            edge("k", "c", "d"), edge("k", "d", "c"),
            edge("k", "a", "b"), edge("k", "b", "a"),
        ]
        found = graphs.directed_cycle_witness(graph_of(edges))
        self.assertEqual(found["nodes"], ["a", "b", "a"])
        self.assertEqual(found["indices"], [2, 3])
        shuffled = list(edges)
        random.Random(4).shuffle(shuffled)
        again = graphs.directed_cycle_witness(graph_of(shuffled))
        self.assertEqual(again["nodes"], ["a", "b", "a"])
        self.assertEqual(
            [(item["source"], item["target"]) for item in again["edges"]],
            [("a", "b"), ("b", "a")],
        )
        self.assertIsNone(graphs.directed_cycle_witness({"edges": []}))
        tree = graphs.directed_cycle_witness(graph_of([edge("k", "a", "b"), edge("k", "b", "c")]))
        self.assertIsNone(tree)
        with self.assertRaisesRegex(ValueError, "edges list"):
            graphs.directed_cycle_witness([])

    def test_a_missing_chord_is_reported_and_a_return_is_not(self):
        edges = [edge("k", "a", "b"), edge("k", "b", "a")]
        self.assertIsNone(graphs.transitivity_witness(edges))
        self.assertIsNone(graphs.transitivity_witness([edge("k", "a", "a"), edge("k", "a", "b")]))
        missing = [edge("k", "a", "b"), edge("k", "b", "c")]
        found = graphs.transitivity_witness(missing)
        self.assertEqual(found["nodes"], ["a", "b", "c"])
        self.assertEqual(found["indices"], [0, 1])
        self.assertEqual(found["missing"], {"source": "a", "target": "c"})
        closed = graphs.transitivity_witness(missing + [edge("k", "a", "c")])
        self.assertIsNone(closed)
        parallel = graphs.transitivity_witness(missing + [edge("k", "a", "c"), edge("m", "a", "c")])
        self.assertIsNone(parallel)
        self.assertIsNone(graphs.transitivity_witness([]))
        with self.assertRaisesRegex(ValueError, "edges must be a list"):
            graphs.transitivity_witness({"edges": []})
        with self.assertRaisesRegex(ValueError, "relation"):
            graphs.transitivity_witness([{"source": "a", "target": "b"}])

    def test_transitivity_ties_prefer_the_smaller_edge_key(self):
        edges = [
            edge("z", "a", "m"), edge("k", "m", "c"),
            edge("a", "a", "b"), edge("k", "b", "c"),
        ]
        found = graphs.transitivity_witness(edges)
        self.assertEqual(found["nodes"], ["a", "b", "c"])
        self.assertEqual(found["indices"], [2, 3])
        self.assertEqual(found["missing"], {"source": "a", "target": "c"})
        reverse = [
            edge("a", "a", "b"), edge("k", "b", "c"),
            edge("z", "a", "m"), edge("k", "m", "c"),
        ]
        kept = graphs.transitivity_witness(reverse)
        self.assertEqual(kept["indices"], [0, 1])
        self.assertEqual(kept["nodes"], ["a", "b", "c"])
        lone = [edge("k", "a", "b")]
        self.assertIsNone(graphs.transitivity_witness(lone))

    def test_a_dead_end_does_not_steal_the_cycle(self):
        found = graphs.directed_cycle_witness(graph_of([
            edge("a", "n", "z"),
            edge("r", "p", "q"),
            edge("a", "q", "x"),
            edge("r", "q", "p"),
        ]))
        self.assertEqual(found["nodes"], ["p", "q", "p"])
        self.assertEqual(found["indices"], [1, 3])

    def test_a_reachable_detour_does_not_replace_the_step_closer(self):
        # T→Y is reachable and has the smaller relation, but it does not step
        # one closer to S. The shortest cycle stays S→T→X→S.
        found = graphs.directed_cycle_witness(graph_of([
            edge("r", "S", "T"),
            edge("z", "T", "X"),
            edge("a", "T", "Y"),
            edge("r", "X", "S"),
            edge("r", "Y", "Z"),
            edge("r", "Z", "S"),
        ]))
        self.assertEqual(found["nodes"], ["S", "T", "X", "S"])
        self.assertEqual(found["indices"], [0, 1, 3])

    def test_diamond_chain_stays_fast_and_picks_the_smaller_side(self):
        found = graphs.directed_cycle_witness(graph_of(diamond_chain(2)))
        self.assertEqual(found["nodes"], diamond_nodes(2))
        self.assertEqual(len(found["indices"]), 5)
        swapped = graphs.directed_cycle_witness(graph_of(diamond_chain(2, b_before_a=True)))
        self.assertEqual(swapped["nodes"], diamond_nodes(2))
        probe = r"""
import time, sys
sys.path.insert(0, sys.argv[1])
import ontautology_graphs as graphs

def chain(depth):
    edges = []
    for i in range(depth):
        left, right, nxt, other = f"n{i}", f"a{i}", f"n{i + 1}", f"b{i}"
        edges.append({"kind": "r", "source": left, "target": right})
        edges.append({"kind": "r", "source": left, "target": other})
        edges.append({"kind": "r", "source": right, "target": nxt})
        edges.append({"kind": "r", "source": other, "target": nxt})
    edges.append({"kind": "r", "source": f"n{depth}", "target": "n0"})
    return edges

def nodes(depth):
    found = ["a0"]
    for i in range(1, depth):
        found.append(f"n{i}")
        found.append(f"a{i}")
    found.extend([f"n{depth}", "n0", "a0"])
    return found

lines = []
for depth in (8, 12, 30):
    started = time.perf_counter()
    witness = graphs.directed_cycle_witness({"edges": chain(depth)})
    elapsed = time.perf_counter() - started
    if witness["nodes"] != nodes(depth) or elapsed >= 1.0:
        raise SystemExit(f"d={depth} {elapsed:.4f}s {witness['nodes'][:8]}")
    lines.append(f"d={depth} {elapsed:.4f}s")
print(" ".join(lines))
"""
        done = subprocess.run(
            [sys.executable, "-S", "-c", probe, str(ROOT)],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        sys.stderr.write(done.stdout)

    def test_cli_prints_the_witness_or_none(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        cycle = write_json(folder.name, "cycle.json", graph_of([
            edge("k", "A", "C"), edge("k", "B", "C"), edge("k", "B", "A"), edge("k", "C", "A"),
        ]))
        code, out, err = invoke(["cycle", str(cycle)])
        self.assertEqual(code, 0, err)
        self.assertIn("cycle: A C A", out)
        self.assertIn("edge: 0 k A C", out)
        self.assertIn("edge: 3 k C A", out)
        code, raw, err = invoke(["cycle", str(cycle), "--json"])
        self.assertEqual(json.loads(raw)["result"]["indices"], [0, 3], err)
        acyclic = write_json(folder.name, "tree.json", graph_of([edge("k", "a", "b")]))
        code, out, err = invoke(["cycle", str(acyclic), "--format", "text"])
        self.assertEqual(code, 0, err)
        self.assertIn("cycle: none", out)
        chord = write_json(folder.name, "chord.json", graph_of([
            edge("k", "a", "b"), edge("k", "b", "c"),
        ]))
        code, out, err = invoke(["transitive", str(chord)])
        self.assertEqual(code, 0, err)
        self.assertIn("witness: a b c", out)
        self.assertIn("missing: a c", out)
        self.assertIn("edge: 0 k a b", out)
        self.assertIn("edge: 1 k b c", out)
        code, raw, err = invoke(["transitive", str(chord), "--json"])
        body = json.loads(raw)
        self.assertEqual(body["result"]["missing"], {"source": "a", "target": "c"}, err)
        self.assertNotIn("parameters", body["provenance"])
        done = write_json(folder.name, "done.json", graph_of([
            edge("k", "a", "b"), edge("k", "b", "c"), edge("k", "a", "c"),
        ]))
        code, out, err = invoke(["transitive", str(done)])
        self.assertEqual(code, 0, err)
        self.assertIn("witness: none", out)


class MutationTests(unittest.TestCase):
    def test_handwritten_mutations_are_killed_by_the_functional_checks(self):
        source = (ROOT / "ontautology_graphs.py").read_text(encoding="utf-8")

        def load(text):
            namespace = {"__name__": "ontautology_graphs_mutant"}
            exec(compile(text, "<ontautology-graphs-mutant>", "exec"), namespace)  # noqa: S102
            return namespace

        def killed(text, check):
            try:
                check(load(text))
            except Exception:
                return True
            return False

        def check_collapse(module):
            found = module["collapse_reciprocal"](
                [edge("similarTo", "a", "b"), edge("similarTo", "b", "a")],
                {"similarTo": "mutual"},
            )
            if found["counts"]["collapsed_edges"] != 1:
                raise AssertionError(found)

        def check_basis(module):
            found = module["cycle_basis"](graph_of([
                edge("k", "a", "b"), edge("k", "b", "c"), edge("k", "c", "a"),
            ]))
            if found["independent_cycles"] != 1:
                raise AssertionError(found)

        def check_dominators(module):
            found = module["single_points_of_failure"](graph_of([
                edge("k", "a", "b"), edge("k", "a", "c"), edge("k", "b", "d"), edge("k", "c", "d"),
            ]), ["a"])
            idom = {row["node"]: row["idom"] for row in found["dominators"]}
            if idom["d"] != "a":
                raise AssertionError(idom)

        def check_cover(module):
            found = module["set_cover_min"](["a"], {"m": ["a"], "z": ["a"]})
            if found["cover"] != ["m"]:
                raise AssertionError(found)

        def check_near(module):
            found = module["near_duplicates"](["dependsOn", "depends_on"], [])
            if not found["nodes"] or found["nodes"][0]["normalizations"] != ["camel_snake", "casefold"]:
                raise AssertionError(found)

        def check_cycle(module):
            found = module["directed_cycle_witness"](graph_of([
                edge("k", "a", "b"), edge("k", "b", "c"), edge("k", "c", "a"), edge("k", "a", "a"),
            ]))
            if found["indices"] != [3]:
                raise AssertionError(found)

        def check_side(module):
            found = module["directed_cycle_witness"](graph_of(diamond_chain(2)))
            if found is None or found["nodes"] != diamond_nodes(2):
                raise AssertionError(found)

        def check_closer(module):
            found = module["directed_cycle_witness"](graph_of([
                edge("r", "S", "T"),
                edge("z", "T", "X"),
                edge("a", "T", "Y"),
                edge("r", "X", "S"),
                edge("r", "Y", "Z"),
                edge("r", "Z", "S"),
            ]))
            if found is None or found["nodes"] != ["S", "T", "X", "S"]:
                raise AssertionError(found)

        def check_prune(module):
            found = module["directed_cycle_witness"](graph_of([
                edge("a", "n", "z"),
                edge("r", "p", "q"),
                edge("a", "q", "x"),
                edge("r", "q", "p"),
            ]))
            if found is None or found["nodes"] != ["p", "q", "p"]:
                raise AssertionError(found)

        def check_cycle_tie(module):
            found = module["directed_cycle_witness"](graph_of([
                edge("k", "c", "d"), edge("k", "d", "c"),
                edge("k", "a", "b"), edge("k", "b", "a"),
            ]))
            if found["nodes"] != ["a", "b", "a"]:
                raise AssertionError(found)

        def check_transitive(module):
            pair = module["transitivity_witness"]([edge("k", "a", "b"), edge("k", "b", "a")])
            if pair is not None:
                raise AssertionError(pair)
            found = module["transitivity_witness"]([
                edge("z", "a", "m"), edge("k", "m", "c"),
                edge("a", "a", "b"), edge("k", "b", "c"),
            ])
            if found["indices"] != [2, 3]:
                raise AssertionError(found)

        def check_lag(module):
            pin, mid, tip = "a" * 40, "b" * 40, "c" * 40
            found = module["first_parent_lag"]([
                {"sha": tip, "parents": [mid, pin]},
                {"sha": mid, "parents": [pin]},
                {"sha": pin, "parents": []},
            ], pin)
            if (found["commits"], found["merges"]) != (2, 1):
                raise AssertionError(found)

        mutations = [
            ("if bucket[\"low\"] and bucket[\"high\"]:", "if False:", check_collapse),
            (
                "independent = edge_count - node_count + components",
                "independent = edge_count - node_count + components + 1",
                check_basis,
            ),
            ("def _intersect(left, right, idom, index):\n    while left != right:",
             "def _intersect(left, right, idom, index):\n    return left\n    while left != right:",
             check_dominators),
            ("names = sorted(sets)", "names = list(reversed(sorted(sets)))", check_cover),
            (
                '_NORMALIZERS = ("nfc", "slash", "git", "camel_snake", "casefold")',
                '_NORMALIZERS = ("nfc", "slash", "git", "casefold")',
                check_near,
            ),
            ('if len(commit["parents"]) > 1:', 'if len(commit["parents"]) >= 1:', check_lag),
            ("if best is None or step < best:", "if best is None or step > best:", check_cycle),
            (
                "if best_rank is None or rank < best_rank:",
                "if best_rank is None or rank > best_rank:",
                check_cycle_tie,
            ),
            (
                "if picked_rank is None or rank < picked_rank:",
                "if picked_rank is None or rank > picked_rank:",
                check_side,
            ),
            (
                "if back is None or back != need:",
                "if False and (back is None or back != need):",
                check_prune,
            ),
            (
                "if dist_nxt is None or dist_nxt != here - 1:",
                "if False and (dist_nxt is None or dist_nxt != here - 1):",
                check_prune,
            ),
            (
                "if dist_nxt is None or dist_nxt != here - 1:",
                "if dist_nxt is None and dist_nxt != here - 1:",
                check_closer,
            ),
            ("if source == nxt:\n                continue", "if False and source == nxt:\n                continue", check_transitive),
            ("if winner is None or key < winner[0]:", "if winner is None or key > winner[0]:", check_transitive),
        ]
        for old, new, check in mutations:
            with self.subTest(old=old):
                self.assertEqual(source.count(old), 1)
                self.assertTrue(killed(source.replace(old, new, 1), check))
                check({"collapse_reciprocal": graphs.collapse_reciprocal, "cycle_basis": graphs.cycle_basis,
                       "single_points_of_failure": graphs.single_points_of_failure,
                       "set_cover_min": graphs.set_cover_min, "near_duplicates": graphs.near_duplicates,
                       "first_parent_lag": graphs.first_parent_lag,
                       "directed_cycle_witness": graphs.directed_cycle_witness,
                       "transitivity_witness": graphs.transitivity_witness})


_WRAPPER = r"""
import dis, functools, os, runpy, sys
from pathlib import Path
realpath = functools.lru_cache(maxsize=None)(os.path.realpath)  # ⚡ one realpath per file, not one per traced call (the hook runs on every call of every test)
script, dest = sys.argv[1], sys.argv[2]
sys.argv = [script, *sys.argv[3:]]
target = os.path.realpath(script)
lines, arcs, pending = set(), set(), {}
prefixes = ("POP_JUMP_IF_", "POP_JUMP_FORWARD_IF_", "POP_JUMP_BACKWARD_IF_", "JUMP_IF_")

def conditional(opname):
    return opname == "FOR_ITER" or opname.startswith(prefixes)

def qual(code):
    return f"{code.co_firstlineno}:{code.co_qualname}"

def hook(frame, event, arg):
    if realpath(frame.f_code.co_filename) != target:
        return None
    frame.f_trace_opcodes = True
    if event == "line":
        lines.add(frame.f_lineno)
    elif event == "opcode":
        code = frame.f_code
        key = id(frame)
        offset = frame.f_lasti
        prev = pending.get(key)
        if prev is not None:
            arcs.add((prev[0], prev[1], offset))
            del pending[key]
        real = offset
        name = dis.opname[code.co_code[real]]
        while name == "EXTENDED_ARG":
            real += 2
            name = dis.opname[code.co_code[real]]
        if conditional(name):
            pending[key] = (qual(code), real)
    elif event == "return":
        pending.pop(id(frame), None)
    return hook

sys.settrace(hook)
status = 0
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as exc:
    status = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
finally:
    sys.settrace(None)
    body = ["LINES", *(str(number) for number in sorted(lines)), "ARCS"]
    body.extend(f"{ident}\t{src}\t{dst}" for ident, src, dst in sorted(arcs))
    Path(dest).write_text("\n".join(body) + "\n", encoding="utf-8")
raise SystemExit(status)
"""


def _static_arcs(code):
    arcs = set()
    blocks = []

    def walk(block):
        blocks.append(block)
        for const in block.co_consts:
            if hasattr(const, "co_code"):
                walk(const)

    walk(code)
    for block in blocks:
        insns = [ins for ins in dis.get_instructions(block) if ins.opname not in {"CACHE", "EXTENDED_ARG"}]
        ident = _qual(block)
        for index, ins in enumerate(insns):
            if not _conditional(ins.opname):
                continue
            fall = next(item.offset for item in insns[index + 1:] if item.opname not in _UNTRACED_OPS)
            target = next(item.offset for item in insns if item.offset >= ins.argval and item.opname not in _UNTRACED_OPS)
            arcs.add((ident, ins.offset, fall))
            arcs.add((ident, ins.offset, target))
    return arcs


class ZCoverageTests(unittest.TestCase):
    def test_statements_and_branches_are_fully_executed(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        graph = write_json(folder.name, "graph.json", graph_of([edge("k", "a", "b"), edge("k", "b", "a")]))
        directions = write_json(folder.name, "directions.json", {"k": "mutual"})
        cover = write_json(folder.name, "cover.json", {"universe": ["a"], "sets": {"s": ["a"]}})
        repo = Path(folder.name) / "repo"
        repo.mkdir()
        env = os.environ.copy()
        subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True, text=True)
        (repo / "f").write_text("f\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "f"], check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=Tester", "-c", "user.email=tester@example.com", "commit", "-m", "f"],
            check=True, capture_output=True, text=True,
        )
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        commands = [
            ["collapse", str(graph), str(directions)],
            ["basis", str(graph), "--json"],
            ["cycle", str(graph), "--format", "text"],
            ["transitive", str(graph), "--json"],
            ["spof", str(graph), "a"],
            ["cover", str(cover), "--format", "text"],
            ["near", str(graph), "--json"],
            ["lag", "--repo", str(repo), "--ref", "main", "--sha", sha, "--format", "json"],
        ]
        child_lines, child_arcs = set(), set()
        for index, argv in enumerate(commands):
            dest = _COVER_DIR / f"cli-{index}.txt"
            done = subprocess.run(
                [sys.executable, "-S", "-c", _WRAPPER, _TARGET, str(dest), *argv],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            section = None
            for line in dest.read_text(encoding="utf-8").splitlines():
                if line in {"LINES", "ARCS"}:
                    section = line
                    continue
                if section == "LINES":
                    child_lines.add(int(line))
                elif section == "ARCS":
                    ident, src, dst = line.split("\t")
                    child_arcs.add((ident, int(src), int(dst)))
        self.assertTrue(child_lines)
        source = Path(_TARGET).read_text(encoding="utf-8")
        total = len(source.splitlines())
        compiled = compile(source, _TARGET, "exec")
        executable = set()

        def walk(block):
            for _start, _end, lineno in block.co_lines():
                if lineno:
                    executable.add(lineno)
            for const in block.co_consts:
                if hasattr(const, "co_lines"):
                    walk(const)

        walk(compiled)
        seen_lines = set(_SEEN_LINES) | child_lines
        executed = executable & seen_lines
        excluded = set(range(1, total + 1)) - executable
        unexecuted = executable - seen_lines
        self.assertEqual(len(executed) + len(excluded) + len(unexecuted), total)
        arcs = _static_arcs(compiled)
        seen_arcs = set(_SEEN_ARCS) | child_arcs
        executed_arcs = arcs & seen_arcs
        excluded_arcs = set()
        unexecuted_arcs = arcs - seen_arcs
        self.assertEqual(len(executed_arcs) + len(excluded_arcs) + len(unexecuted_arcs), len(arcs))
        guard = next(number for number, line in enumerate(source.splitlines(), start=1) if line.startswith("if __name__"))
        self.assertIn(guard, child_lines)
        sys.stderr.write(
            f"statements executed={len(executed)} excluded={len(excluded)} "
            f"unexecuted={len(unexecuted)} total={total}\n"
            f"branches executed={len(executed_arcs)} excluded={len(excluded_arcs)} "
            f"unexecuted={len(unexecuted_arcs)} total={len(arcs)}\n"
        )
        if unexecuted or unexecuted_arcs:
            lines = source.splitlines()
            preview = "\n".join(f"{number}: {lines[number - 1]}" for number in sorted(unexecuted))
            arc_preview = "\n".join(repr(item) for item in sorted(unexecuted_arcs)[:50])
            self.fail(
                f"unexecuted lines {len(unexecuted)}\n{preview}\n"
                f"unexecuted branches {len(unexecuted_arcs)}\n{arc_preview}"
            )


if __name__ == "__main__":
    unittest.main()
