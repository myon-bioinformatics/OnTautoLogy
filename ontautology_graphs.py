"""Generic graph algorithms for OnTautoLogy (Python 3.11+, standard library only).

Callers such as a topology summary or a relation table keep their own aggregation.
This file only folds edges, lists a cycle basis, reports one directed cycle and
one missing transitive chord, finds single points of failure, solves a small set
cover, reports near-duplicate names, and counts first-parent git lag. It fetches
nothing and does not merge the names it reports.

An edge is ``{"source", "target"}`` plus ``kind`` or ``relation``. Endpoints and
relation names are non-empty strings. CLI results carry the tool version and the
sha256 of every input path. ``--json`` is shorthand for ``--format json``.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import subprocess
import sys
import unicodedata
from pathlib import Path

import onto_path

__version__ = "0.1.0"
TOOL_NAME = "ontautology-graphs"
EXACT_COVER_LIMIT = 18
_COLLAPSE = frozenset({"mutual", "undirected"})
_DIRECTED = frozenset({"forward", "directed"})
_NORMALIZERS = ("nfc", "slash", "git", "camel_snake", "casefold")
_SUPER = object()
__all__ = [
    "collapse_reciprocal", "cycle_basis", "directed_cycle_witness", "transitivity_witness",
    "single_points_of_failure", "set_cover_min", "near_duplicates", "names_from_graph",
    "first_parent_lag", "load_first_parent", "main",
]


def _relation(edge):
    kind = edge.get("kind")
    relation = edge.get("relation")
    if isinstance(kind, str) and kind:
        if relation not in (None, kind):
            raise ValueError("edge kind and relation disagree")
        return kind
    if isinstance(relation, str) and relation:
        return relation
    raise ValueError("edge needs a non-empty relation")


def _endpoints(edge):
    source = edge.get("source")
    target = edge.get("target")
    if not isinstance(source, str) or not source or not isinstance(target, str) or not target:
        raise ValueError("edge needs non-empty string endpoints")
    return source, target


def _copy_edge(edge):
    if not isinstance(edge, dict):
        raise ValueError("an edge must be an object")
    _endpoints(edge)
    _relation(edge)
    return dict(edge)


def _edge_key(edge):
    return (_relation(edge), edge["source"], edge["target"], json.dumps(edge, ensure_ascii=False, sort_keys=True))


def _graph_edges(graph):
    if not isinstance(graph, dict) or not isinstance(graph.get("edges"), list):
        raise ValueError("graph needs an edges list")
    return [_copy_edge(edge) for edge in graph["edges"]]


# ---------------------------------------------------------------- reciprocal pairs


def collapse_reciprocal(edges, directions):
    """Fold mutual or undirected ``a→b`` plus ``b→a`` into the ``a≤b`` edges.

    When both directions are present, every edge from the higher endpoint to the
    lower one is dropped, including extras. ``a→b`` once and ``b→a`` twice
    therefore leave the single ``a→b``. Edges that already run lower to higher
    are all kept, so that direction's multi-edges do not collapse into one.
    Directed relations are left alone, so a real length-2 cycle stays visible.
    A self-loop is not a pair. ``counts.edges`` is the input length and
    ``counts.collapsed_edges`` is the length after folding.
    """
    if not isinstance(edges, list):
        raise ValueError("edges must be a list")
    if not isinstance(directions, dict):
        raise ValueError("directions must be an object")
    for name, direction in directions.items():
        if not isinstance(name, str) or not name:
            raise ValueError("direction keys must be non-empty strings")
        if direction not in _COLLAPSE and direction not in _DIRECTED:
            raise ValueError(f"unknown direction {direction!r}")
    buckets = {}
    kept = []
    for edge in (_copy_edge(item) for item in edges):
        relation = _relation(edge)
        source, target = edge["source"], edge["target"]
        direction = directions.get(relation, "directed")
        if direction not in _COLLAPSE or source == target:
            kept.append(edge)
            continue
        if source <= target:
            low, high, side = source, target, "low"
        else:
            low, high, side = target, source, "high"
        buckets.setdefault((relation, low, high), {"low": [], "high": []})[side].append(edge)
    for key in sorted(buckets):
        bucket = buckets[key]
        if bucket["low"] and bucket["high"]:
            kept.extend(bucket["low"])
        else:
            kept.extend(bucket["low"])
            kept.extend(bucket["high"])
    kept.sort(key=_edge_key)
    return {"counts": {"collapsed_edges": len(kept), "edges": len(edges)}, "edges": kept}


# ---------------------------------------------------------------- fundamental cycles


def _cycle_key(indices, edges):
    return [_edge_key(edges[index]) for index in indices]


def _canonical_cycle(indices, edges):
    sequences = (list(indices), list(reversed(indices)))
    candidates = []
    for sequence in sequences:
        for offset in range(len(sequence)):
            candidates.append(sequence[offset:] + sequence[:offset])
    return min(candidates, key=lambda sequence: _cycle_key(sequence, edges))


def cycle_basis(graph):
    """A fundamental cycle basis of the undirected multigraph.

    Each directed edge is one undirected edge, so a reciprocal pair is a
    length-2 cycle until ``collapse_reciprocal`` folds it. Isolated node records
    are not vertices. The basis has ``E - V + C`` cycles; each cycle lists the
    original edges and their relation labels in walk order.
    """
    edges = _graph_edges(graph)
    adjacent = {}
    for index, edge in enumerate(edges):
        source, target = edge["source"], edge["target"]
        adjacent.setdefault(source, []).append((target, index))
        if source != target:
            adjacent.setdefault(target, []).append((source, index))
    for node in adjacent:
        adjacent[node].sort(key=lambda item: (item[0], _edge_key(edges[item[1]]), item[1]))
    used, visited, parent, parent_edge = set(), set(), {}, {}
    found = []

    def absorb(start):
        stack = [start]
        while True:
            if not stack:
                break
            node = stack[-1]
            stepped = False
            for neighbor, index in adjacent[node]:
                if index in used:
                    continue
                used.add(index)
                if neighbor not in visited:
                    visited.add(neighbor)
                    parent[neighbor] = node
                    parent_edge[neighbor] = index
                    stack.append(neighbor)
                    stepped = True
                    break
                cycle = []
                if neighbor != node:
                    current = node
                    while True:
                        cycle.append(parent_edge[current])
                        current = parent[current]
                        if current == neighbor:
                            break
                cycle.append(index)
                found.append(_canonical_cycle(cycle, edges))
                stepped = True
                break
            if not stepped:
                stack.pop()

    components = 0
    for start in sorted(adjacent):
        if start in visited:
            continue
        components += 1
        visited.add(start)
        parent[start] = None
        absorb(start)
    edge_count = len(edges)
    node_count = len(adjacent)
    independent = edge_count - node_count + components
    found.sort(key=lambda cycle: _cycle_key(cycle, edges))
    cycles = []
    for cycle in found:
        cycles.append({
            "edges": [dict(edges[index]) for index in cycle],
            "indices": list(cycle),
            "labels": [_relation(edges[index]) for index in cycle],
        })
    return {
        "counts": {"components": components, "edges": edge_count, "nodes": node_count},
        "cycles": cycles,
        "independent_cycles": independent,
    }


def _adjacency_by_source(edges):
    adjacent = {}
    for index, edge in enumerate(edges):
        adjacent.setdefault(edge["source"], []).append(index)
    return adjacent


def _incoming_by_target(edges):
    incoming = {}
    for index, edge in enumerate(edges):
        incoming.setdefault(edge["target"], []).append(index)
    return incoming


def _shortest_directed_length(edges, adjacent):
    """Fewest edges in a simple directed cycle, counting a self-loop as one."""
    best = None
    for start in sorted(adjacent):
        dist = {start: 0}
        queue = [start]
        head = 0
        while True:
            if head >= len(queue):
                break
            node = queue[head]
            head += 1
            for index in adjacent.get(node, ()):
                nxt = edges[index]["target"]
                step = dist[node] + 1
                if nxt == start:
                    if best is None or step < best:
                        best = step
                    continue
                if nxt not in dist:
                    dist[nxt] = step
                    queue.append(nxt)
    return best


def _distance_toward(edges, incoming, goal):
    """Shortest-path distance to ``goal``, by breadth-first search on reversed edges."""
    dist = {goal: 0}
    queue = [goal]
    head = 0
    while True:
        if head >= len(queue):
            break
        node = queue[head]
        head += 1
        for index in incoming.get(node, ()):
            prev = edges[index]["source"]
            if prev not in dist:
                dist[prev] = dist[node] + 1
                queue.append(prev)
    return dist


def _distances_toward_all(edges, incoming):
    nodes = []
    seen = set()
    for edge in edges:
        for node in (edge["source"], edge["target"]):
            if node not in seen:
                seen.add(node)
                nodes.append(node)
    toward = {}
    for node in nodes:
        toward[node] = _distance_toward(edges, incoming, node)
    return toward


def _girth_edge(edges, toward, length):
    """Minimum edge that lies on some simple cycle of ``length`` edges."""
    chosen = None
    best_rank = None
    need = length - 1
    for index, edge in enumerate(edges):
        back = toward[edge["source"]].get(edge["target"])
        if back is None or back != need:
            continue
        rank = (_edge_key(edges[index]), index)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            chosen = index
    return chosen


def _shortest_return(edges, adjacent, toward, origin, length):
    """Lexicographically smallest shortest path from the far end back to the start."""
    goal = edges[origin]["source"]
    node = edges[origin]["target"]
    indices = [origin]
    left = length - 1
    while True:
        if left == 0:
            break
        here = toward[goal][node]
        picked = None
        picked_rank = None
        for index in adjacent.get(node, ()):
            nxt = edges[index]["target"]
            dist_nxt = toward[goal].get(nxt)
            if dist_nxt is None or dist_nxt != here - 1:
                continue
            rank = (_edge_key(edges[index]), index)
            if picked_rank is None or rank < picked_rank:
                picked_rank = rank
                picked = index
        indices.append(picked)
        node = edges[picked]["target"]
        left -= 1
    return indices


def _directed_search(edges, adjacent, length):
    incoming = _incoming_by_target(edges)
    toward = _distances_toward_all(edges, incoming)
    origin = _girth_edge(edges, toward, length)
    return _shortest_return(edges, adjacent, toward, origin, length)


def directed_cycle_witness(graph):
    """One simple directed cycle, the one with the fewest edges, or None.

    A self-loop is a cycle of one edge and beats every longer cycle. Parallel
    edges in the same direction are not a cycle. A reciprocal pair is a cycle of
    two edges, the same pair ``cycle_basis`` keeps until ``collapse_reciprocal``
    folds it. The walk stays directed: it may be rotated, not reversed. Among
    shortest cycles the smallest rotation of ``(edge key, index)`` wins, with the
    same edge key as ``cycle_basis``. ``nodes`` is that closed walk, repeating
    the first node at the end. ``indices`` are positions in ``graph["edges"]``.
    The witness is that rotation of one shortest cycle: the minimum edge on any
    shortest cycle, then the lexicographically smallest shortest path back.
    Edges that do not step one closer to the start are ignored, so the search
    does not list the other shortest cycles.

    ``A→C``, ``B→C``, ``B→A``, ``C→A`` yields ``A→C→A``. The undirected basis
    also contains the triangle, and that triangle is not a directed cycle.
    """
    edges = _graph_edges(graph)
    adjacent = _adjacency_by_source(edges)
    length = _shortest_directed_length(edges, adjacent)
    if length is None:
        return None
    indices = _directed_search(edges, adjacent, length)
    nodes = [edges[indices[0]]["source"]]
    labels = []
    copied = []
    for index in indices:
        copied.append(dict(edges[index]))
        labels.append(_relation(edges[index]))
        nodes.append(edges[index]["target"])
    return {"edges": copied, "indices": indices, "labels": labels, "nodes": nodes}


def transitivity_witness(edges):
    """One path ``a→b→c`` whose chord ``a→c`` is absent, or None.

    ``a==c`` is a directed cycle, not a missing chord, so a reciprocal pair
    without a self-loop is not a witness. Self-loops are not required. A
    self-loop cannot be the missing chord either: if either step is a self-loop,
    the chord is the other step, which is present. Any one edge ``a→c`` in this
    list, including a parallel edge, supplies the chord. Indices are positions
    in ``edges``. Among witnesses, the smallest ``(edge key, index)`` of the
    first step, then of the second step, wins. Relation names are not filtered;
    pass the edge set of the relation under test.
    """
    if not isinstance(edges, list):
        raise ValueError("edges must be a list")
    copied = []
    for edge in edges:
        copied.append(_copy_edge(edge))
    present = set()
    by_source = {}
    for index, edge in enumerate(copied):
        present.add((edge["source"], edge["target"]))
        by_source.setdefault(edge["source"], []).append(index)
    winner = None
    for index, edge in enumerate(copied):
        follows = by_source.get(edge["target"])
        if follows is None:
            continue
        for follow in follows:
            nxt = copied[follow]["target"]
            source = edge["source"]
            if source == nxt:
                continue
            if (source, nxt) in present:
                continue
            key = (_edge_key(edge), index, _edge_key(copied[follow]), follow)
            if winner is None or key < winner[0]:
                winner = (key, index, follow)
    if winner is None:
        return None
    _key, index, follow = winner
    first, second = copied[index], copied[follow]
    return {
        "edges": [dict(first), dict(second)],
        "indices": [index, follow],
        "missing": {"source": first["source"], "target": second["target"]},
        "nodes": [first["source"], first["target"], second["target"]],
    }


# ---------------------------------------------------------------- points of failure


def _adjacency(edges):
    outward, inward = {}, {}
    for edge in edges:
        outward.setdefault(edge["source"], set()).add(edge["target"])
        inward.setdefault(edge["target"], set()).add(edge["source"])
    return (
        {node: sorted(values) for node, values in outward.items()},
        {node: sorted(values) for node, values in inward.items()},
    )


def _reverse_postorder(start, outward):
    seen = {start}
    frames = {start: iter(outward.get(start, ()))}
    active = [start]
    post = []
    while True:
        if not active:
            break
        node = active[-1]
        advanced = False
        for child in frames[node]:
            if child in seen:
                continue
            seen.add(child)
            frames[child] = iter(outward.get(child, ()))
            active.append(child)
            advanced = True
            break
        if not advanced:
            post.append(active.pop())
    post.reverse()
    return post


def _intersect(left, right, idom, index):
    while left != right:
        while index[left] > index[right]:
            left = idom[left]
        while index[right] > index[left]:
            right = idom[right]
    return left


def _immediate_dominators(roots, edges):
    """Iterative Cooper–Harvey–Kennedy immediate dominators, rooted at a virtual entry."""
    outward, inward = _adjacency(edges)
    outward[_SUPER] = list(roots)
    for root in roots:
        inward[root] = [_SUPER, *inward.get(root, ())]
    order = _reverse_postorder(_SUPER, outward)
    index = {node: position for position, node in enumerate(order)}
    idom = {_SUPER: _SUPER}
    changed = True
    while True:
        if not changed:
            break
        changed = False
        for node in order:
            if node is _SUPER:
                continue
            ready = [item for item in inward.get(node, ()) if item in idom]
            new_idom = ready[0]
            for other in ready[1:]:
                new_idom = _intersect(other, new_idom, idom, index)
            if node not in idom or idom[node] != new_idom:
                idom[node] = new_idom
                changed = True
    return {node: None if idom[node] is _SUPER else idom[node] for node in order if node is not _SUPER}


def _undirected(edges):
    adjacent = {}
    for edge in edges:
        source, target = edge["source"], edge["target"]
        adjacent.setdefault(source, set())
        if source == target:
            continue
        adjacent.setdefault(target, set())
        adjacent[source].add(target)
        adjacent[target].add(source)
    return {node: sorted(values) for node, values in adjacent.items()}


def _articulation_points(edges):
    adjacent = _undirected(edges)
    depth, low, parent = {}, {}, {}
    points = set()
    clock = 0

    def walk(node):
        nonlocal clock
        depth[node] = low[node] = clock
        clock += 1
        children = 0
        for nxt in adjacent[node]:
            if nxt not in depth:
                parent[nxt] = node
                children += 1
                walk(nxt)
                low[node] = min(low[node], low[nxt])
                if parent[node] is None and children > 1:
                    points.add(node)
                if parent[node] is not None and low[nxt] >= depth[node]:
                    points.add(node)
            elif nxt != parent[node]:
                low[node] = min(low[node], depth[nxt])

    for start in sorted(adjacent):
        if start in depth:
            continue
        parent[start] = None
        walk(start)
    return sorted(points)


def _node_id(node):
    if isinstance(node, str):
        ident = node
    elif isinstance(node, dict) and isinstance(node.get("id"), str):
        ident = node["id"]
    else:
        raise ValueError("a node is a string id or an object with a string id")
    if not ident:
        raise ValueError("node ids must be non-empty strings")
    return ident


def _listed_nodes(graph, edges, roots):
    raw = graph.get("nodes", [])
    if not isinstance(raw, list):
        raise ValueError("nodes must be a list")
    found, seen = [], set()

    def add(ident):
        if ident not in seen:
            seen.add(ident)
            found.append(ident)

    for node in raw:
        add(_node_id(node))
    for edge in edges:
        add(edge["source"])
        add(edge["target"])
    for root in roots:
        add(root)
    return found


def _dominated(idom):
    children = {node: [] for node in idom}
    for node, immediate in idom.items():
        if immediate is not None:
            children[immediate].append(node)

    def collect(node):
        group = [node]
        for child in children[node]:
            group.extend(collect(child))
        return group

    return {node: sorted(collect(node)) for node in idom}


def _clean_roots(roots):
    if isinstance(roots, str) or not isinstance(roots, (list, tuple)):
        raise ValueError("roots must be a list")
    cleaned, seen = [], set()
    for root in roots:
        if not isinstance(root, str) or not root:
            raise ValueError("roots must be non-empty strings")
        if root not in seen:
            seen.add(root)
            cleaned.append(root)
    if not cleaned:
        raise ValueError("at least one root is required")
    cleaned.sort()
    return cleaned


def single_points_of_failure(graph, roots):
    """Immediate dominators from ``roots``, undirected articulation points, and failure rank.

    Rank is how many nodes that are reachable from the roots, including the node
    itself, lose every path from the roots when the node is removed. A node that
    was already unreachable ranks 0. Dominators are the Cooper–Harvey–Kennedy tree.
    """
    cleaned = _clean_roots(roots)
    edges = _graph_edges(graph)
    idom = _immediate_dominators(cleaned, edges)
    lost = _dominated(idom)
    ranked = []
    for node in _listed_nodes(graph, edges, cleaned):
        group = lost.get(node, [])
        ranked.append({"lost": group, "node": node, "unreachable": len(group)})
    ranked.sort(key=lambda row: (-row["unreachable"], row["node"]))
    return {
        "articulation_points": _articulation_points(edges),
        "dominators": [{"idom": idom[node], "node": node} for node in sorted(idom)],
        "ranked": ranked,
        "roots": cleaned,
    }


# ---------------------------------------------------------------- set cover


def _as_sets(universe, candidate_sets):
    if isinstance(universe, str) or not isinstance(universe, (list, tuple)):
        raise ValueError("universe must be a list")
    if not isinstance(candidate_sets, dict):
        raise ValueError("candidate_sets must be an object")
    seen, elements = set(), []
    for element in universe:
        if not isinstance(element, str):
            raise ValueError("universe elements must be strings")
        if element not in seen:
            seen.add(element)
            elements.append(element)
    sets = {}
    for name, members in candidate_sets.items():
        if not isinstance(name, str) or not name:
            raise ValueError("set names must be non-empty strings")
        if isinstance(members, str) or not isinstance(members, (list, tuple)):
            raise ValueError(f"{name} must list its elements")
        cleaned = []
        for member in members:
            if not isinstance(member, str):
                raise ValueError(f"{name} elements must be strings")
            cleaned.append(member)
        sets[name] = set(cleaned)
    return elements, sets


def _exact_cover(names, sets, target):
    best, best_hit = [], -1
    for size in range(len(names) + 1):
        for combo in itertools.combinations(names, size):
            covered = set()
            for name in combo:
                covered |= sets[name]
            hit = len(covered & target)
            if hit == len(target):
                return list(combo)
            if hit > best_hit:
                best, best_hit = list(combo), hit
    return best


def _greedy_cover(names, sets, target):
    remaining = set(target)
    chosen = []
    while remaining:
        ranked = []
        for name in names:
            if name in chosen:
                continue
            gain = len(sets[name] & remaining)
            if gain:
                ranked.append((-gain, name))
        if not ranked:
            break
        ranked.sort()
        best = ranked[0][1]
        chosen.append(best)
        remaining -= sets[best]
    return chosen


def set_cover_min(universe, candidate_sets, *, limit=None):
    """Minimum set cover for a small instance, otherwise greedy.

    Names are sorted, then ``itertools.combinations`` walks them. A combination
    that covers the whole universe stops the search, so a full cover is a
    minimum-size set and ties take the first combination. When nothing covers
    the universe, the chosen set is the one that covers the most elements; an
    equal count keeps the earlier combination. The returned ``cover`` list is
    that choice, sorted. ``limit`` is the largest number of candidate sets
    solved exactly (default ``EXACT_COVER_LIMIT``). Each candidate also lists
    the universe elements that no other candidate contains.
    """
    if limit is None:
        limit = EXACT_COVER_LIMIT
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a non-negative integer")
    elements, sets = _as_sets(universe, candidate_sets)
    names = sorted(sets)
    target = set(elements)
    if len(names) > limit:
        chosen = _greedy_cover(names, sets, target)
        method = "greedy"
    else:
        chosen = _exact_cover(names, sets, target)
        method = "exact"
    covered = set()
    for name in chosen:
        covered |= sets[name] & target
    owners = {element: [] for element in elements}
    for name in names:
        for element in sets[name]:
            if element in owners:
                owners[element].append(name)
    unique = {name: [] for name in names}
    for element in elements:
        found = owners[element]
        if len(found) == 1:
            unique[found[0]].append(element)
    for name in unique:
        unique[name].sort()
    return {
        "complete": target <= covered,
        "cover": sorted(chosen),
        "method": method,
        "size": len(chosen),
        "uncovered": sorted(target - covered),
        "unique": unique,
    }


# ---------------------------------------------------------------- near-duplicate names


def _camel_to_snake(text):
    chars = []
    for index, char in enumerate(text):
        if char == "_":
            chars.append("_")
            continue
        if char.isupper() and chars and chars[-1] != "_":
            previous = text[index - 1]
            nxt = text[index + 1] if index + 1 < len(text) else ""
            if previous.islower() or previous.isdigit() or (previous.isupper() and nxt.islower()):
                chars.append("_")
        chars.append(char)
    return "".join(chars)


def _apply_normalizers(text, enabled):
    if "nfc" in enabled:
        text = unicodedata.normalize("NFC", text)
    if "slash" in enabled:
        text = text.strip("/")
    if "git" in enabled:
        if text.casefold().endswith(".git"):
            text = text[:-4]
    if "camel_snake" in enabled:
        text = _camel_to_snake(text)
    if "casefold" in enabled:
        text = text.casefold()
    return text


def _canonical(text):
    return _apply_normalizers(text, set(_NORMALIZERS))


def _minimal_normalizations(names):
    wanted = _canonical(names[0])
    found = []
    width = len(_NORMALIZERS)
    for mask in range(1 << width):
        enabled = {name for bit, name in enumerate(_NORMALIZERS) if mask & (1 << bit)}
        matched = True
        for value in names:
            if _apply_normalizers(value, enabled) != wanted:
                matched = False
                break
        if matched:
            found.append([name for name in _NORMALIZERS if name in enabled])
    best = min(found, key=lambda item: (len(item), item))
    return list(best)


def _group_names(names):
    if isinstance(names, str) or not isinstance(names, (list, tuple)):
        raise ValueError("names must be a list")
    buckets = {}
    for name in names:
        if not isinstance(name, str) or not name:
            raise ValueError("names must be non-empty strings")
        buckets.setdefault(_canonical(name), []).append(name)
    groups = []
    for key in sorted(buckets):
        distinct = sorted(set(buckets[key]))
        if len(distinct) < 2:
            continue
        groups.append({
            "folded": False,
            "ids": distinct,
            "key": key,
            "normalizations": _minimal_normalizations(distinct),
        })
    return groups


def near_duplicates(node_ids, relation_names):
    """Group ids that differ only by case, NFC, a trailing ``.git``, slashes, or camel/snake.

    The result names the normalizations that were required. ``folded`` is always
    false: this reports candidates and does not choose a survivor.
    """
    return {
        "folded": False,
        "nodes": _group_names(node_ids),
        "relations": _group_names(relation_names),
    }


def names_from_graph(graph):
    """Node ids and relation names appearing in a graph, in first-seen order."""
    edges = _graph_edges(graph)
    return _listed_nodes(graph, edges, []), [_relation(edge) for edge in edges]


# ---------------------------------------------------------------- first-parent lag


def _commit_sha(value):
    if not isinstance(value, str) or len(value) != 40:
        raise ValueError("commit sha must be 40 lowercase hex characters")
    for char in value:
        if char not in "0123456789abcdef":
            raise ValueError("commit sha must be 40 lowercase hex characters")
    return value


def first_parent_lag(chain, pinned):
    """Count first-parent commits and merges strictly after ``pinned``.

    ``chain`` runs from the branch tip back to the root. Each commit is
    ``{"sha", "parents"}``. A merge has two or more parents. The pinned sha must
    itself lie on this chain; a squashed-away commit or a side commit does not.
    """
    if not isinstance(chain, list) or not chain:
        raise ValueError("the first-parent chain is empty")
    pinned = _commit_sha(pinned)
    seen, normalized = set(), []
    for commit in chain:
        if not isinstance(commit, dict):
            raise ValueError("a commit must be an object")
        sha = _commit_sha(commit.get("sha"))
        if sha in seen:
            raise ValueError(f"duplicate commit {sha}")
        seen.add(sha)
        parents = commit.get("parents")
        if not isinstance(parents, list):
            raise ValueError("commit parents must be a list of shas")
        for parent in parents:
            if not isinstance(parent, str) or not parent:
                raise ValueError("commit parents must be a list of shas")
        normalized.append({"parents": list(parents), "sha": sha})
    if pinned not in seen:
        raise ValueError(f"{pinned} is not on the first-parent chain")
    index = 0
    while normalized[index]["sha"] != pinned:
        index += 1
    after = normalized[:index]
    merges = 0
    for commit in after:
        if len(commit["parents"]) > 1:
            merges += 1
    return {"commits": len(after), "merges": merges, "pinned": pinned, "tip": normalized[0]["sha"]}


def _git(repo, *args):
    command = [
        "git", "--no-pager", "--no-optional-locks", "-c", "safe.directory=*",
        "-C", str(repo), *args,
    ]
    env = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", ""),
    }
    done = subprocess.run(command, capture_output=True, env=env, text=True, encoding="utf-8")
    if done.returncode != 0:
        detail = (done.stderr or "").strip() or f"git exited {done.returncode}"
        raise ValueError(detail)
    return done.stdout


def load_first_parent(repo, ref, pinned):
    """Read-only ``git rev-list --first-parent`` for a local repository. No network."""
    if not isinstance(repo, str) or not repo:
        raise ValueError("git repository path is required")
    if not isinstance(ref, str) or not ref:
        raise ValueError("branch ref is required")
    if not isinstance(pinned, str) or not pinned:
        raise ValueError("pinned sha is required")
    path = Path(repo)
    if not path.is_dir():
        raise ValueError(f"not a git repository directory: {repo}")
    listing = _git(path, "rev-list", "--first-parent", "--parents", "--end-of-options", ref)
    resolved = _git(path, "rev-parse", "--verify", "--end-of-options", pinned + "^{commit}").strip()
    chain = []
    for line in listing.splitlines():
        parts = line.split()
        chain.append({"parents": parts[1:], "sha": parts[0]})
    result = first_parent_lag(chain, resolved)
    digest = hashlib.sha256(listing.encode("utf-8")).hexdigest()
    return result, digest


# ---------------------------------------------------------------- command line


def _one_stdin(paths):
    if sum(str(path) == "-" for path in paths) > 1:
        raise ValueError("stdin '-' may be used only once per command")


def _read_input(path, role):
    if str(path) == "-":
        data = sys.stdin.buffer.read()
        shown = "-"
    else:
        data = Path(path).read_bytes()
        shown = Path(path).as_posix()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{role} is not utf-8") from error
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"{role} is not json") from error
    return parsed, {"path": shown, "role": role, "sha256": hashlib.sha256(data).hexdigest()}


def _document(command, result, inputs, parameters=None):
    provenance = {"inputs": inputs}
    if parameters:
        provenance["parameters"] = parameters
    return {
        "command": command,
        "provenance": provenance,
        "result": result,
        "tool": {"name": TOOL_NAME, "version": __version__},
    }


def _selected_format(args):
    if args.json and args.format not in (None, "json"):
        raise ValueError("--json cannot be combined with a different --format")
    if args.json or args.format == "json":
        return "json"
    return "text"


def _dump(document):
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _header(document):
    lines = [
        f"tool: {document['tool']['name']} {document['tool']['version']}",
        f"command: {document['command']}",
    ]
    for item in document["provenance"]["inputs"]:
        lines.append(f"input: {item['role']} {item['path']} sha256:{item['sha256']}")
    parameters = document["provenance"].get("parameters") or {}
    for key in sorted(parameters):
        lines.append(f"parameter: {key} {parameters[key]}")
    return lines


def _render_collapse(result):
    counts = result["counts"]
    lines = [f"edges: {counts['edges']}", f"collapsed_edges: {counts['collapsed_edges']}"]
    for edge in result["edges"]:
        lines.append(f"edge: {_relation(edge)} {edge['source']} {edge['target']}")
    return lines


def _render_cycle(result):
    if result is None:
        return ["cycle: none"]
    lines = ["cycle: " + " ".join(result["nodes"])]
    position = 0
    while True:
        if position >= len(result["indices"]):
            break
        index = result["indices"][position]
        edge = result["edges"][position]
        lines.append(f"edge: {index} {_relation(edge)} {edge['source']} {edge['target']}")
        position += 1
    return lines


def _render_transitive(result):
    if result is None:
        return ["witness: none"]
    missing = result["missing"]
    lines = [
        "witness: " + " ".join(result["nodes"]),
        f"missing: {missing['source']} {missing['target']}",
    ]
    position = 0
    while True:
        if position >= len(result["indices"]):
            break
        index = result["indices"][position]
        edge = result["edges"][position]
        lines.append(f"edge: {index} {_relation(edge)} {edge['source']} {edge['target']}")
        position += 1
    return lines


def _render_basis(result):
    counts = result["counts"]
    lines = [
        f"independent_cycles: {result['independent_cycles']}",
        f"edges: {counts['edges']}",
        f"nodes: {counts['nodes']}",
        f"components: {counts['components']}",
    ]
    for number, cycle in enumerate(result["cycles"], start=1):
        joined = " ".join(cycle["labels"])
        lines.append(f"cycle: {number} {joined}")
    return lines


def _render_spof(result):
    lines = [f"roots: {' '.join(result['roots'])}"]
    for row in result["dominators"]:
        immediate = row["idom"] if row["idom"] is not None else "-"
        lines.append(f"dominator: {row['node']} {immediate}")
    lines.append("articulation: " + " ".join(result["articulation_points"]))
    for row in result["ranked"]:
        lines.append(f"rank: {row['node']} {row['unreachable']}")
    return lines


def _render_cover(result):
    lines = [
        f"method: {result['method']}",
        f"complete: {'yes' if result['complete'] else 'no'}",
        f"size: {result['size']}",
        "cover: " + " ".join(result["cover"]),
        "uncovered: " + " ".join(result["uncovered"]),
    ]
    for name in sorted(result["unique"]):
        lines.append(f"unique: {name} {' '.join(result['unique'][name])}")
    return lines


def _render_near(result):
    lines = ["folded: no"]
    for kind in ("nodes", "relations"):
        for group in result[kind]:
            rules = ",".join(group["normalizations"])
            lines.append(f"{kind}: {rules} {' '.join(group['ids'])}")
    return lines


def _render_lag(result):
    return [
        f"commits: {result['commits']}",
        f"merges: {result['merges']}",
        f"tip: {result['tip']}",
        f"pinned: {result['pinned']}",
    ]


_RENDER = {
    "basis": _render_basis,
    "collapse": _render_collapse,
    "cover": _render_cover,
    "cycle": _render_cycle,
    "lag": _render_lag,
    "near": _render_near,
    "spof": _render_spof,
    "transitive": _render_transitive,
}


def _render(document):
    return "\n".join(_header(document) + _RENDER[document["command"]](document["result"])) + "\n"


def _cmd_collapse(args):
    _one_stdin((args.graph, args.directions))
    graph, graph_record = _read_input(args.graph, "graph")
    directions, direction_record = _read_input(args.directions, "directions")
    result = collapse_reciprocal(_graph_edges(graph), directions)
    return _document("collapse", result, [graph_record, direction_record])


def _cmd_basis(args):
    graph, record = _read_input(args.graph, "graph")
    return _document("basis", cycle_basis(graph), [record])


def _cmd_cycle(args):
    graph, record = _read_input(args.graph, "graph")
    return _document("cycle", directed_cycle_witness(graph), [record])


def _cmd_transitive(args):
    graph, record = _read_input(args.graph, "graph")
    return _document("transitive", transitivity_witness(_graph_edges(graph)), [record])


def _roots_from(args):
    roots = [item for item in args.roots if item]
    if not roots:
        roots = [item for item in os.environ.get(onto_path.OTL_ROOTS_ENV, "").split(",") if item]
    if not roots:
        raise ValueError(f"roots are required (arguments or {onto_path.OTL_ROOTS_ENV})")
    return roots


def _cmd_spof(args):
    roots = _roots_from(args)
    graph, record = _read_input(args.graph, "graph")
    result = single_points_of_failure(graph, roots)
    return _document("spof", result, [record], {"roots": " ".join(result["roots"])})


def _cmd_cover(args):
    payload, record = _read_input(args.cover, "cover")
    if not isinstance(payload, dict) or "universe" not in payload or "sets" not in payload:
        raise ValueError("cover input needs universe and sets")
    result = set_cover_min(payload["universe"], payload["sets"], limit=args.limit)
    return _document("cover", result, [record], {"limit": str(args.limit)})


def _cmd_near(args):
    graph, record = _read_input(args.graph, "graph")
    nodes, relations = names_from_graph(graph)
    return _document("near", near_duplicates(nodes, relations), [record])


def _from_env(value, env_name):
    if value:
        return value
    found = os.environ.get(env_name, "")
    if found:
        return found
    raise ValueError(f"required input is missing ({env_name})")


def _cmd_lag(args):
    repo = _from_env(args.repo, onto_path.OTL_GIT_REPO_ENV)
    ref = _from_env(args.ref, onto_path.OTL_GIT_REF_ENV)
    pinned = _from_env(args.sha, onto_path.OTL_GIT_SHA_ENV)
    result, digest = load_first_parent(repo, ref, pinned)
    record = {"path": repo, "role": "git", "sha256": digest}
    return _document("lag", result, [record], {"pinned": result["pinned"], "ref": ref})


_COMMANDS = {
    "basis": _cmd_basis,
    "collapse": _cmd_collapse,
    "cover": _cmd_cover,
    "cycle": _cmd_cycle,
    "lag": _cmd_lag,
    "near": _cmd_near,
    "spof": _cmd_spof,
    "transitive": _cmd_transitive,
}


def _add_format(parser):
    parser.add_argument("--format", choices=("text", "json"))
    parser.add_argument("--json", action="store_true", help="shorthand for --format json")
    parser.add_argument("-o", "--output", type=Path)


def main(argv=None):
    """0 = answered, 1 = the input cannot be read or does not satisfy the command."""
    parser = argparse.ArgumentParser(
        prog="ontautology-graphs",
        description="collapse · basis · cycle · transitive · spof · cover · near · lag",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    collapse = commands.add_parser("collapse", help="fold mutual or undirected reciprocal edges")
    collapse.add_argument("graph", type=Path)
    collapse.add_argument("directions", type=Path)
    _add_format(collapse)
    basis = commands.add_parser("basis", help="fundamental cycle basis of the undirected view")
    basis.add_argument("graph", type=Path)
    _add_format(basis)
    cycle = commands.add_parser("cycle", help="shortest simple directed cycle")
    cycle.add_argument("graph", type=Path)
    _add_format(cycle)
    transitive = commands.add_parser("transitive", help="one missing transitive chord")
    transitive.add_argument("graph", type=Path)
    _add_format(transitive)
    spof = commands.add_parser("spof", help="dominators, articulation points, and failure rank")
    spof.add_argument("graph", type=Path)
    spof.add_argument("roots", nargs="*")
    _add_format(spof)
    cover = commands.add_parser("cover", help="minimum set cover, greedy when the instance is large")
    cover.add_argument("cover", type=Path)
    cover.add_argument("--limit", type=int, default=EXACT_COVER_LIMIT)
    _add_format(cover)
    near = commands.add_parser("near", help="report near-duplicate ids without merging them")
    near.add_argument("graph", type=Path)
    _add_format(near)
    lag = commands.add_parser("lag", help="first-parent commits after a pinned sha")
    lag.add_argument("--repo", default="")
    lag.add_argument("--ref", default="")
    lag.add_argument("--sha", default="")
    _add_format(lag)
    try:
        args = parser.parse_args(argv)
        document = _COMMANDS[args.command](args)
        text = _render(document) if _selected_format(args) == "text" else _dump(document)
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    except (OSError, ValueError, TypeError) as error:
        print(f"ontautology-graphs: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
