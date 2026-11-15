"""OnTautoLogy: the repository-independent logic of a small knowledge graph (Python 3.11+, standard library).

The name: take an ontology up to the level of a tautology. A statement starts as a guess, becomes something
seen, and only at the top is true whatever the data — a proof. This module keeps those levels apart and
answers the questions any such graph is asked. It reads plain dicts and lists (JSON), fetches nothing and
knows no repository; who produced the edges, and from which records, is the caller's business.

An edge is a dict: {"kind", "source", "target"} plus what the caller has —
  basis   hypothesis | derived | observed | proof   (absent means observed)
            hypothesis  a candidate nobody checked
            derived     a fixed rule over records (a name match, a hash found in a directory)
            observed    read from a record or seen on the given rows; says nothing about rows not seen
            proof       holds for every case, seen or not — the tautology level
  lock    the record that asserts it;  observed_at  the record's own time;  anything else is carried along.
Direction: source is what is depended on, target is what must be looked at again when the source changes.
So reach() walks forward (what does a change touch) and why() walks back (what does a judgement rest on).

Every function is callable by name from Python, and from Node through a Python launcher:
  check  reach  why  cycles  order  ladder  key_report
"""
from __future__ import annotations

import argparse
import json
import sys
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

BASIS = ("hypothesis", "derived", "observed", "proof")
__all__ = ["BASIS", "check", "reach", "why", "cycles", "order", "ladder", "key_report", "main"]


def _basis(edge):
    return edge.get("basis", "observed")


def check(edges, nodes=None):
    """Findings that make a graph unsafe to walk: bad shape, unknown basis, one statement with two contents,
    and — when the known node ids are given — references to nodes that do not exist. Nothing is repaired."""
    findings, seen = [], {}
    known = None if nodes is None else set(nodes)
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict) or not all(isinstance(edge.get(k), str) and edge.get(k) for k in ("kind", "source", "target")):
            findings.append({"kind": "shape", "edge": index, "detail": "an edge needs kind, source and target as non-empty strings"})
            continue
        if _basis(edge) not in BASIS:
            findings.append({"kind": "basis", "edge": index, "detail": f"unknown basis {edge['basis']!r}"})
        if known is not None:
            for end in ("source", "target"):
                if edge[end] not in known:
                    findings.append({"kind": "missing-reference", "edge": index, "detail": f"{end} {edge[end]} is not a known node"})
        # The same statement from the same record at the same time must say the same thing; another time or
        # another record is another observation and is kept beside it.
        key = (edge["kind"], edge["source"], edge["target"], edge.get("lock"), edge.get("observed_at"))
        text = json.dumps(edge, sort_keys=True, ensure_ascii=False)
        if seen.setdefault(key, text) != text:
            findings.append({"kind": "duplicate-id", "edge": index,
                             "detail": f"{edge['kind']} {edge['source']} → {edge['target']} is stated twice with different content"})
    return findings


def reach(edges, start, *, limit=1000):
    """What a change of the start nodes touches: breadth-first forward, no DAG assumed.

    Each row has the node, its depth, the chain that reaches it and the edge it came by. A hypothesis is
    listed under ``candidates`` and never walked through: a guess decides nothing downstream.
    """
    forward = {}
    for edge in edges:
        forward.setdefault(edge["source"], []).append(edge)
    start = list(dict.fromkeys(start))
    rows, candidates, queue = {}, {}, [(node, 0, [node]) for node in start]
    while queue and len(rows) < limit:
        node, depth, chain = queue.pop(0)
        for edge in sorted(forward.get(node, ()), key=lambda e: (e["kind"], e["target"])):
            target = edge["target"]
            if target in start or target in rows:
                continue
            if _basis(edge) == "hypothesis":
                candidates.setdefault(target, {"node": target, "from": node, "edge": edge})
                continue
            rows[target] = {"node": target, "depth": depth + 1, "via": chain + [target], "edge": edge}
            queue.append((target, depth + 1, chain + [target]))
    known = set(forward) | {edge["target"] for edge in edges}
    return {"start": start, "rows": sorted(rows.values(), key=lambda r: (r["depth"], r["node"])),
            "candidates": [candidates[k] for k in sorted(candidates) if k not in rows],
            "unknown": [node for node in start if node not in known], "truncated": bool(queue)}


def why(edges, node, *, depth=3, limit=200):
    """What a node rests on: inbound edges, breadth-first up to depth. ``weakest`` is the lowest basis on the
    way, so a chain with one guess in it is not read as proven; ``cut`` says the depth limit left edges unread."""
    inbound = {}
    for edge in edges:
        inbound.setdefault(edge["target"], []).append(edge)
    rows, seen, queue, cut = [], {node}, [(node, 0, "proof")], False
    while queue and len(rows) < limit:
        current, level, floor = queue.pop(0)
        if level >= depth:
            cut = cut or bool(inbound.get(current))
            continue
        for edge in sorted(inbound.get(current, ()), key=lambda e: (e["kind"], e["source"])):
            weakest = min(floor, _basis(edge), key=BASIS.index)
            rows.append({"depth": level + 1, "weakest": weakest, "edge": edge})
            if edge["source"] not in seen:
                seen.add(edge["source"])
                queue.append((edge["source"], level + 1, weakest))
    return {"node": node, "rows": rows, "cut": cut, "truncated": bool(queue) and len(rows) >= limit}


def cycles(edges, *, limit=5):
    """Representative cycles, reported and never fatal: a graph with guesses and refutations need not be a DAG."""
    out = {}
    for edge in edges:
        out.setdefault(edge["source"], []).append(edge["target"])
    colour, found = {}, []
    for start in sorted(out):
        if colour.get(start):
            continue
        stack, path = [(start, iter(sorted(out[start])))], [start]
        colour[start] = 1
        while stack and len(found) < limit:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                colour[node] = 2
                stack.pop()
                path.pop()
            elif colour.get(child) == 1:
                found.append(path[path.index(child):] + [child])
            elif not colour.get(child):
                colour[child] = 1
                path.append(child)
                stack.append((child, iter(sorted(out.get(child, ())))))
    return found


def order(edges, *, nodes=()):
    """Batches in which the targets can be handled, sources first (graphlib); only where an order is needed.

    Pass just the edges that mean "must come before". A cycle gives no batches and is returned, so the
    caller can still handle everything the cycle does not touch.
    """
    waits = {node: set() for node in nodes}
    for edge in edges:
        waits.setdefault(edge["target"], set()).add(edge["source"])
        waits.setdefault(edge["source"], set())
    sorter = TopologicalSorter(waits)
    try:
        sorter.prepare()
    except CycleError as error:
        return {"batches": [], "cycle": list(error.args[1])}
    batches = []
    while sorter.is_active():
        ready = sorted(sorter.get_ready())
        batches.append(ready)
        sorter.done(*ready)
    return {"batches": batches, "cycle": None}


def ladder(edges):
    """How far up the graph has come: edges per basis, and per kind how many are at the proof level."""
    counts = {basis: 0 for basis in BASIS}
    kinds = {}
    for edge in edges:
        basis = _basis(edge)
        counts[basis] = counts.get(basis, 0) + 1
        entry = kinds.setdefault(edge["kind"], {"edges": 0, "proof": 0})
        entry["edges"] += 1
        entry["proof"] += basis == "proof"
    return {"edges": len(edges), "basis": counts, "kinds": dict(sorted(kinds.items()))}


def key_report(items, candidates):
    """Can an attribute set be the key of these entries? Identity is settled last: a handle first, a key only
    when the observations support it, and a key that collides is reported, not overwritten.

    key        complete and unique — may be promoted from handle to identity
    repeat     unique except for entries equal in every field (the same entry listed twice)
    collides   one value names entries that differ — not an identity
    incomplete some entry lacks a field, so nothing is claimed
    The verdict is about these entries only; one more entry can turn ``key`` into ``collides``.
    """
    report = {}
    for fields in candidates:
        groups, missing = {}, 0
        for item in items:
            if any(item.get(field) in (None, "") for field in fields):
                missing += 1
                continue
            groups.setdefault(tuple(str(item[field]) for field in fields), []).append(json.dumps(item, sort_keys=True, ensure_ascii=False))
        repeats = sorted(key for key, texts in groups.items() if len(texts) > 1 and len(set(texts)) == 1)
        conflicts = sorted(key for key, texts in groups.items() if len(set(texts)) > 1)
        verdict = "incomplete" if missing else "collides" if conflicts else "repeat" if repeats else "key"
        report["+".join(fields)] = {"verdict": verdict, "distinct": len(groups), "repeats": len(repeats), "collisions": len(conflicts),
                                    "missing": missing, "examples": ["+".join(key) for key in (conflicts or repeats)[:5]]}
    return report


def main(argv=None):
    """0 = answered, 1 = input error, 2 = answered and something needs a look (findings, a cycle, an unknown node)."""
    parser = argparse.ArgumentParser(description="Ask a small knowledge graph: 🧪 check, 💥 reach, 🔎 why, 🔁 cycles, 🪜 order / ladder, 🔑 keys.")
    parser.add_argument("graph", type=Path, help='JSON: {"edges": [...]} with optional "nodes" (ids) and "items" (entries for keys)')
    parser.add_argument("ask", choices=("check", "reach", "why", "cycles", "order", "ladder", "keys"))
    parser.add_argument("terms", nargs="*", help="node ids (reach, why) · edge kinds that mean 'before' (order) · field sets like id+run (keys)")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.graph.read_text(encoding="utf-8"))
        edges = data["edges"]
        bad = check(edges, data.get("nodes"))
        if args.ask != "check" and any(f["kind"] == "shape" for f in bad):
            raise ValueError("the graph has malformed edges; run check")
        if args.ask in ("reach", "why") and not args.terms:
            raise ValueError(f"{args.ask} needs a node id")
        if args.ask == "check":
            answer, look = bad, bool(bad)
        elif args.ask == "reach":
            answer = reach(edges, args.terms)
            look = bool(answer["unknown"])
        elif args.ask == "why":
            answer = [why(edges, node) for node in args.terms]
            look = any(not found["rows"] for found in answer)
        elif args.ask == "cycles":
            answer = cycles(edges)
            look = bool(answer)
        elif args.ask == "order":
            answer = order([e for e in edges if not args.terms or e["kind"] in args.terms], nodes=data.get("nodes") or ())
            look = answer["cycle"] is not None
        elif args.ask == "ladder":
            answer, look = ladder(edges), False
        else:
            answer = key_report(data.get("items") or [], [tuple(term.split("+")) for term in args.terms])
            look = any(v["verdict"] != "key" for v in answer.values())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ontautology: {error}", file=sys.stderr)
        return 1
    json.dump(answer, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 2 if look else 0


if __name__ == "__main__":
    raise SystemExit(main())
