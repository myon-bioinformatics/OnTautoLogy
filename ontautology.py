"""OnTautoLogy: look across repositories as one small knowledge graph (Python 3.11+, standard library).

The name: take an ontology up to the level of a tautology. A statement starts as a guess, becomes something
seen, and only at the top is true whatever the data — a proof. One file, generic only — it knows no repository,
fetches nothing and is all a vendoring repository needs:

1. Core — logic any such graph needs, on plain dicts and lists.
     check  reach  why  cycles  order  ladder  key_report
2. Concepts — from similar pairs (guitar ↔ bass) to the common part and what tells them apart.
     define_concepts  roundtrip_elements  concept_edges
The GitHub audit dashboard (PR audit snapshots, plan, diff, Turtle, transfers) is a use of this file and lives in
gh_audit/gh_audit.py; it adds its commands to main() through ``commands`` and ``load``.

A core edge is a dict {"kind", "source", "target"} plus what the caller has:
  basis   hypothesis | derived | observed | proof   (absent means observed)
            hypothesis  a candidate nobody checked
            derived     a fixed rule over records (a name match, the same changed path)
            observed    read from a record; says nothing about what was not seen
            proof       holds for every case, seen or not — the tautology level
  lock    the record that asserts it;  observed_at  the record's own time;  anything else is carried along.
Direction: source is what is depended on, target is what must be looked at again when the source changes.
reach() walks forward (what does a change touch), why() walks back (what does a judgement rest on).

Every function is callable by name from Python, and from Node through the Python launcher (py_launch.cjs).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

# ---------------------------------------------------------------- 1. core

BASIS = ("hypothesis", "derived", "observed", "proof")
__all__ = ["BASIS", "LABEL_KINDS", "check", "reach", "why", "cycles", "order", "ladder", "key_report",
           "digest", "timestamp", "define_concepts", "roundtrip_elements", "concept_edges", "concept_lexicon", "main"]


def digest(value):
    """👀 Watch layer, shared by every use: the identity of a record (a snapshot, an observed value) — SHA-256 of its JSON."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def timestamp(value):
    """👀 Watch layer: an observation time is an ISO timestamp with a timezone; anything else is refused."""
    if not isinstance(value, str):
        raise ValueError("observed_at must be an ISO timestamp with timezone")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("observed_at must include a timezone")
    return result


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
        # another record is another observation and is kept beside it. Without a record there is nothing to compare.
        key = (edge["kind"], edge["source"], edge["target"], edge.get("lock"), edge.get("observed_at"))
        text = json.dumps(edge, sort_keys=True, ensure_ascii=False)
        if edge.get("lock") and seen.setdefault(key, text) != text:
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
    return {"node": node, "rows": rows[:limit], "cut": cut, "truncated": len(rows) > limit or (bool(queue) and len(rows) >= limit)}


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

    Pass just the edges that mean "must come before". Whatever sits on a cycle, or behind one, is ``blocked``
    and left out; everything else is still ordered, so one cycle does not stop unrelated work.
    """
    waits = {node: set() for node in nodes}
    for edge in edges:
        waits.setdefault(edge["target"], set()).add(edge["source"])
        waits.setdefault(edge["source"], set())
    cycle, blocked = None, set()
    while True:
        open_waits = {node: sorted(waits[node] - blocked) for node in sorted(waits) if node not in blocked}
        sorter = TopologicalSorter(open_waits)
        try:
            sorter.prepare()
            break
        except CycleError as error:
            cycle = cycle or list(error.args[1])
            stuck = set(error.args[1])
            blocked |= stuck | {row["node"] for row in reach([e for e in edges if e["source"] not in blocked], sorted(stuck), limit=len(waits) + 1)["rows"]}
    batches = []
    while sorter.is_active():
        ready = sorted(sorter.get_ready())
        batches.append(ready)
        sorter.done(*ready)
    return {"batches": batches, "cycle": cycle, "blocked": sorted(blocked)}


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


# ---------------------------------------------------------------- 3. concept similarity & definition

CONCEPT_SCHEMA = "ontautology-concepts/1"
# 第三弾の試作。種別は SKOS の prefLabel / altLabel に相当する呼び名で、語彙そのものは導入しない。
LABEL_KINDS = ("pref", "alt", "abbr", "variant", "translation")
_PHASE3_LISTS = ("observations", "judgments", "candidates")


def _nonempty_str(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _normalize_corpus(corpus):
    """Validate and normalize a concept-similarity corpus into sorted dicts.

    Accepts {"concepts": ..., "similar": [...]} (concepts as dict or list of objects;
    similar entries as [left, right] or {"left"/"source", "right"/"target", ...}).
    Missing concepts mentioned in ``similar`` are kept with elements=None (unobserved).
    """
    if not isinstance(corpus, dict):
        raise ValueError("concept corpus must be a JSON object")
    schema = corpus.get("schema")
    if schema is not None and schema != CONCEPT_SCHEMA:
        raise ValueError(f"unsupported concept schema: {schema!r}")
    raw_concepts = corpus.get("concepts", {})
    concepts, concept_meta = {}, {}
    if isinstance(raw_concepts, dict):
        # 辞書のキーが概念の名前。中の id は言語に依存しない安定 ID（例: C006-salmon）。無いときは名前のまま。
        items = []
        for raw_name, raw_spec in raw_concepts.items():
            if isinstance(raw_spec, dict) and "id" in raw_spec:
                raw_spec = dict(raw_spec)
                raw_spec["concept_id"] = raw_spec.pop("id")
            items.append((raw_name, raw_spec))
    elif isinstance(raw_concepts, list):
        items = []
        for entry in raw_concepts:
            if not isinstance(entry, dict) or "id" not in entry:
                raise ValueError("concept list entries must be objects with 'id'")
            items.append((entry["id"], entry))
    else:
        raise ValueError("concepts must be an object or a list of objects")
    for raw_name, raw_spec in items:
        name = _nonempty_str(raw_name, "concept id")
        if name in concepts:
            raise ValueError(f"duplicate concept id: {name!r}")
        if raw_spec is None:
            concepts[name] = None
            concept_meta[name] = {"basis": "hypothesis"}
        elif isinstance(raw_spec, list):
            concepts[name] = sorted({_nonempty_str(el, f"{name} element") for el in raw_spec})
            concept_meta[name] = {"basis": "observed"}
        elif isinstance(raw_spec, dict):
            basis = raw_spec.get("basis", "observed")
            if basis not in BASIS:
                raise ValueError(f"unknown basis {basis!r} for concept {name!r}")
            elems = raw_spec.get("elements")
            if elems is None:
                concepts[name] = None
            elif isinstance(elems, list):
                concepts[name] = sorted({_nonempty_str(el, f"{name} element") for el in elems})
            else:
                raise ValueError(f"elements for {name!r} must be a list or null")
            if "concept_id" in raw_spec:
                _nonempty_str(raw_spec["concept_id"], f"{name} id")
            if "notation" in raw_spec and raw_spec["notation"] is not None:
                _nonempty_str(raw_spec["notation"], f"{name} notation")
            concept_meta[name] = {**{k: v for k, v in raw_spec.items() if k not in ("id", "elements")}, "basis": basis}
        else:
            raise ValueError(f"concept spec for {name!r} must be a list, object, or null")
    raw_similar = corpus.get("similar", [])
    if not isinstance(raw_similar, list):
        raise ValueError("similar must be a list")
    pairs, neighbors = [], {name: {} for name in concepts}
    for entry in raw_similar:
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            left, right, meta = entry[0], entry[1], {"basis": "observed"}
        elif isinstance(entry, dict):
            left = entry.get("left", entry.get("source"))
            right = entry.get("right", entry.get("target"))
            basis = entry.get("basis", "observed")
            if basis not in BASIS:
                raise ValueError(f"unknown basis {basis!r} in similar pair")
            meta = {**{k: v for k, v in entry.items() if k not in ("left", "right", "source", "target")}, "basis": basis}
        else:
            raise ValueError("similar entries must be [left, right] or objects with left/right or source/target")
        left = _nonempty_str(left, "similar left")
        right = _nonempty_str(right, "similar right")
        if left == right:
            raise ValueError(f"self-similarity is invalid: {left!r}")
        for end in (left, right):
            if end not in concepts:
                concepts[end] = None
                concept_meta[end] = {"basis": "hypothesis"}
                neighbors[end] = {}
        a, b = sorted((left, right))
        pairs.append({"left": a, "right": b, **meta})
        # Keep the strongest basis if the same pair is cited multiple times.
        for x, y in ((a, b), (b, a)):
            prev = neighbors[x].get(y)
            if prev is None or BASIS.index(meta["basis"]) > BASIS.index(prev):
                neighbors[x][y] = meta["basis"]
    # 安定 ID と、ID を書かなかった概念の名前が、グラフ上で重ならないこと。
    seen_tokens = {}
    for uname, meta in concept_meta.items():
        token = meta.get("concept_id") or uname
        if token in seen_tokens:
            raise ValueError(f"概念の ID が重なっています: {token!r}（{seen_tokens[token]!r} と {uname!r}）")
        seen_tokens[token] = uname
    return concepts, concept_meta, pairs, neighbors


def _beside(corpus, concepts, key):
    """A {concept: [element, ...]} list kept beside the observed elements, for known concepts; definitions never
    rest on it.

    maybe  elements a concept might have — links allowed to be wrong (hypotheses)
    names  the name side: how it is read, written, translated or called (読み・英名・学名・別名・同音語 …).
           Asking for a name is calling the answer, so the thing side alone defines and is asked about.
    """
    raw = corpus.get(key, {})
    if not isinstance(raw, dict):
        raise ValueError(f"{key} must be an object of concept → elements")
    found = {}
    for name, elements in raw.items():
        if name not in concepts:
            raise ValueError(f"{key} names an unknown concept: {name!r}")
        if not isinstance(elements, list):
            raise ValueError(f"{key} for {name!r} must be a list")
        found[name] = sorted({_nonempty_str(el, f"{name} {key} element") for el in elements} - set(concepts[name] or ()))
    return found


def _minimal_hitting_sets(requirements, *, max_keys=5, max_key_size=5):
    """Minimal subsets of elements that intersect every non-empty difference set."""
    if not requirements:
        return [[]]
    reduced = []
    for req in sorted({frozenset(r) for r in requirements}, key=lambda r: (len(r), sorted(r))):
        if not any(kept <= req for kept in reduced):
            reduced.append(req)
    max_size = min(max_key_size, len({el for req in reduced for el in req}))
    found = []
    for target_size in range(1, max_size + 1):
        seen_states = set()

        def search(chosen, uncovered):
            if len(found) >= max_keys:
                return
            state = frozenset(chosen)
            if state in seen_states:
                return
            seen_states.add(state)
            if not uncovered:
                found.append(sorted(chosen))
                return
            if len(chosen) >= target_size:
                return
            pivot = min(uncovered, key=lambda r: (len(r), sorted(r)))
            for el in sorted(pivot):
                nxt = chosen | {el}
                if any(frozenset(prev) <= nxt for prev in found):
                    continue
                search(nxt, [r for r in uncovered if el not in r])
                if len(found) >= max_keys:
                    return

        search(set(), reduced)
        if len(found) >= max_keys:
            break
    return found


def roundtrip_elements(corpus, elements):
    """Reverse lookup (TalkCompress-style roundtrip): which observed concepts contain all ``elements``?"""
    concepts, _, _, _ = _normalize_corpus(corpus)
    if not isinstance(elements, (list, tuple, set)):
        raise ValueError("elements must be a list")
    query = sorted({_nonempty_str(el, "element") for el in elements})
    qset = set(query)
    matched = [name for name in sorted(concepts) if concepts[name] is not None and qset <= set(concepts[name])]
    unobserved = [name for name in sorted(concepts) if concepts[name] is None]
    verdict = "unique" if len(matched) == 1 else "collides" if len(matched) > 1 else "empty"
    return {"schema": "ontautology-roundtrip/1", "query": query, "verdict": verdict,
            "matched": matched, "unobserved": unobserved}


def define_concepts(corpus, targets=None, *, max_keys=5, max_key_size=5):
    """Derive genus (common elements across similar pairs) and differentia (minimal distinguishing keys)."""
    concepts, _, pairs, neighbors = _normalize_corpus(corpus)
    all_names = sorted(concepts)
    if targets:
        requested = list(dict.fromkeys(_nonempty_str(t, "target concept") for t in targets))
        unknown = [t for t in requested if t not in concepts]
        selected = [t for t in requested if t in concepts]
    else:
        unknown = []
        selected = all_names
    observed_names = [name for name in all_names if concepts[name] is not None]
    results = {}
    for name in selected:
        elems = concepts[name]
        sim_map = neighbors[name]
        sim_names = sorted(sim_map)
        if elems is None:
            results[name] = {
                "elements_observed": False,
                "elements": None,
                "similar": sim_names,
                "status": "incomplete",
                "basis": "hypothesis",
                "genus": {"all_common": [], "by_similar": {}, "support": []},
                "differentia": {"vs_similar": {}, "minimal_keys": [], "unavoidable_collisions": []},
                "definition": {"genus": [], "differentia": [], "elements": [],
                               "roundtrip": {"verdict": "incomplete", "matched": []}},
            }
            continue
        elem_set = set(elems)
        obs_sim = [s for s in sim_names if concepts[s] is not None]
        unobs_sim = [s for s in sim_names if concepts[s] is None]
        by_similar, vs_similar = {}, {}
        for s in obs_sim:
            s_set = set(concepts[s])
            common = sorted(elem_set & s_set)
            only_target = sorted(elem_set - s_set)
            only_similar = sorted(s_set - elem_set)
            by_similar[s] = {"common": common, "basis": sim_map[s]}
            vs_similar[s] = {"only_target": only_target, "only_similar": only_similar}
        if obs_sim:
            common_sets = [elem_set] + [set(concepts[s]) for s in obs_sim]
            all_common = sorted(set.intersection(*common_sets))
        else:
            all_common = []
        cluster = [name] + obs_sim
        support = [{"element": el, "count": sum(el in concepts[c] for c in cluster), "of": len(cluster)}
                   for el in elems]
        support.sort(key=lambda row: (-row["count"], row["element"]))
        reqs, collisions = [], []
        for other in observed_names:
            if other == name:
                continue
            diff = elem_set - set(concepts[other])
            if not diff:
                collisions.append(other)
            else:
                reqs.append(diff)
        minimal_keys = [] if collisions else _minimal_hitting_sets(reqs, max_keys=max_keys, max_key_size=max_key_size)
        primary_diff = minimal_keys[0] if minimal_keys else []
        def_elements = sorted(set(all_common) | set(primary_diff)) if primary_diff else elems
        rt = roundtrip_elements(corpus, def_elements)
        if collisions:
            status, basis = "collides", "hypothesis"
        elif unobs_sim:
            status, basis = "incomplete", "hypothesis"
        elif not obs_sim:
            status, basis = ("unique_uncontrasted" if rt["verdict"] == "unique" else "incomplete"), "hypothesis"
        elif not minimal_keys:
            status, basis = "incomplete", "hypothesis"
        else:
            sim_bases = {sim_map[s] for s in obs_sim}
            status = "unique"
            basis = "hypothesis" if sim_bases == {"hypothesis"} else "derived"
        results[name] = {
            "elements_observed": True,
            "elements": elems,
            "similar": sim_names,
            "unobserved_similar": unobs_sim,
            "status": status,
            "basis": basis,
            "genus": {"all_common": all_common, "by_similar": by_similar, "support": support},
            "differentia": {"vs_similar": vs_similar, "minimal_keys": minimal_keys, "unavoidable_collisions": collisions},
            "definition": {"genus": all_common, "differentia": primary_diff, "elements": def_elements,
                           "roundtrip": {"verdict": rt["verdict"], "matched": rt["matched"]}},
        }
    return {"schema": CONCEPT_SCHEMA, "similar_pairs": len(pairs),
            "concepts": results, "unknown": unknown}


def _bcp47(value, label):
    """言語タグ。ja / en / ko のような BCP 47。空や空白、日本語の文字そのものは受けない。"""
    parts = value.split("-") if isinstance(value, str) else []
    head, rest = (parts[0], parts[1:]) if parts else ("", [])

    def _ascii(text, lo, hi, digits):
        if not lo <= len(text) <= hi:
            return False
        for ch in text:
            letter = ("A" <= ch <= "Z") or ("a" <= ch <= "z")
            number = digits and ("0" <= ch <= "9")
            if not (letter or number):
                return False
        return True

    if not (_ascii(head, 2, 3, False) and all(_ascii(part, 2, 8, True) for part in rest)):
        raise ValueError(f"{label} は BCP 47 の言語タグ（ja, en など）でなければなりません: {value!r}")
    return value


def _phase3_records(corpus, concepts):
    """観測・判断・外部候補。人が確定するまで判断は hypothesis。外部候補は書かれた basis を上げない。

    人の名前はノードにしない。actor と role は記録の別フィールドとして返す。
    """
    found = {key: [] for key in _PHASE3_LISTS}
    if not any(key in corpus for key in ("labels", *_PHASE3_LISTS)):
        labels = []
    else:
        labels = _structured_labels(corpus, concepts)
    for key in _PHASE3_LISTS:
        if key not in corpus:
            continue
        raw = corpus[key]
        if not isinstance(raw, list):
            raise ValueError(f"{key} はオブジェクトの配列です")
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError(f"{key} の要素はオブジェクトです")
            concept = _nonempty_str(item.get("concept"), f"{key} concept")
            if concept not in concepts:
                raise ValueError(f"{key} に未知の概念があります: {concept!r}")
            row = {"concept": concept}
            for field in ("actor", "role", "evidence", "context", "statement", "note", "generator", "model"):
                if field in item and item[field] is not None:
                    row[field] = _nonempty_str(item[field], f"{key} {field}")
            if "slots" in item and item["slots"] is not None:
                slots = item["slots"]
                if not isinstance(slots, dict) or not slots:
                    raise ValueError(f"{key} の slots は空でないオブジェクトです")
                row["slots"] = { _nonempty_str(k, "slot"): _nonempty_str(v, "slot") for k, v in slots.items()}
            if key == "judgments":
                basis = item.get("basis", "hypothesis")
                if basis not in BASIS:
                    raise ValueError(f"判断の basis が不明です: {basis!r}")
                row["basis"] = basis
                rests = item.get("rests_on", [concept])
                if not isinstance(rests, list) or not rests:
                    raise ValueError("判断の rests_on は概念名の配列です")
                row["rests_on"] = [_nonempty_str(name, "rests_on") for name in rests]
                unknown = [name for name in row["rests_on"] if name not in concepts]
                if unknown:
                    raise ValueError(f"判断が未知の概念に拠っています: {unknown!r}")
            if key == "candidates":
                # 外部モデルの出力。observed や proof と書いてあっても hypothesis のまま置く。
                claimed = item.get("basis", "hypothesis")
                if claimed not in BASIS:
                    raise ValueError(f"候補の basis が不明です: {claimed!r}")
                row["basis"] = "hypothesis"
                if claimed != "hypothesis":
                    row["claimed_basis"] = claimed
                row["text"] = _nonempty_str(item.get("text"), "candidate text")
                row["lang"] = _bcp47(item.get("lang"), "candidate lang")
                if item.get("kind") not in LABEL_KINDS:
                    raise ValueError(f"候補の kind は {LABEL_KINDS} のいずれかです: {item.get('kind')!r}")
                row["kind"] = item["kind"]
                if "confidence" in item and item["confidence"] is not None:
                    score = item["confidence"]
                    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
                        raise ValueError(f"候補の confidence は 0 以上 1 以下の数です: {score!r}")
                    row["confidence"] = score
            found[key].append(row)
    return labels, found


def _structured_labels(corpus, concepts):
    """属性名では書ききれない表記（文脈つきなど）。無いコーパスでは空で、名前側の文字列は触らない。"""
    raw = corpus.get("labels", {})
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise ValueError("labels は概念からラベル配列へのオブジェクトです")
    rows, seen_pref = [], set()
    for name, items in raw.items():
        if name not in concepts:
            raise ValueError(f"labels に未知の概念があります: {name!r}")
        if not isinstance(items, list):
            raise ValueError(f"labels[{name!r}] はオブジェクトの配列です")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("labels の要素は text, lang, kind を持つオブジェクトです（文字列は names に書いてください）")
            unknown = set(item) - {"text", "lang", "kind", "context"}
            if unknown:
                raise ValueError(f"labels に未知のフィールドがあります: {sorted(unknown)}")
            text = _nonempty_str(item.get("text"), "label text")
            lang = _bcp47(item.get("lang"), "label lang")
            kind = item.get("kind")
            if kind not in LABEL_KINDS:
                raise ValueError(f"label kind は {LABEL_KINDS} のいずれかです: {kind!r}")
            context = item.get("context")
            if context is not None:
                context = _nonempty_str(context, "label context")
            pref_key = (name, lang.lower(), context)
            if kind == "pref" and pref_key in seen_pref:
                raise ValueError(f"pref ラベルが同じ概念・言語・文脈で重複しています: {name!r} {lang} {context!r}")
            if kind == "pref":
                seen_pref.add(pref_key)
            row = {"concept": name, "text": text, "lang": lang, "kind": kind}
            if context:
                row["context"] = context
            rows.append(row)
    rows.sort(key=lambda row: (row["concept"], row["lang"].lower(), row["kind"], row["text"], row.get("context") or ""))
    return rows


def concept_lexicon(corpus):
    """入力。安定 ID・任意の構造化ラベル・観測・判断・外部候補を正規化する。定義と当てっこはこれを見ない。

    names の「英名:Guitar」形式はここでは解釈しない（表記の言語と種別は tools 側が属性名から読む）。
    """
    concepts, concept_meta, _, _ = _normalize_corpus(corpus)
    labels, records = _phase3_records(corpus, concepts)
    return {"concepts": concepts, "meta": concept_meta, "labels": labels, **records}


def concept_edges(corpus):
    """Project a concept-similarity corpus onto core edges for check / reach / why / cycles / ladder.

    The watch layer is the one phase 1 uses: the corpus is one Snapshot (the digest of its normalized content, so
    the order of the input does not change it) and every concept whose elements were seen gets one Observation
    (``observes`` the concept, ``derived_from`` the snapshot). Each element edge names that observation as its
    ``lock``. An unobserved concept (elements null) has no observation. ``captured_at``, when given, is the time.
    ``maybe`` elements (links allowed to be wrong) become hasElement edges at the hypothesis level; nothing
    observed them, so their ``lock`` is the snapshot that wrote them down. ``names`` become Name nodes with an
    observed hasName edge (the name side: read, written, translated, called), locked like the elements.

    安定 ID（concept_id）が無い概念のノードは、これまでどおり ``concept:名前`` です。ID があるときだけ
    ``concept:そのID`` になり、名前はノードの name に残します。人の名前はノードにしません。
    """
    concepts, concept_meta, pairs, _ = _normalize_corpus(corpus)
    maybe, called = _beside(corpus, concepts, "maybe"), _beside(corpus, concepts, "names")
    labels, records = _phase3_records(corpus, concepts)
    defined = define_concepts(corpus)
    seen_at = corpus.get("captured_at")
    if seen_at is not None:
        timestamp(seen_at)
    when = {"observed_at": seen_at} if seen_at else {}
    payload = {"concepts": concepts, "similar": sorted(pairs, key=digest)}
    if called:
        payload["names"] = called
    idents = {name: meta["concept_id"] for name, meta in concept_meta.items() if meta.get("concept_id")}
    notations = {name: meta["notation"] for name, meta in concept_meta.items() if meta.get("notation")}
    # 第二弾のコーパスにはこれらのキーを足さない。digest が変わるとスナップショットが別物になる。
    if idents:
        payload["concept_ids"] = idents
    if notations:
        payload["notation"] = notations
    if labels:
        payload["labels"] = labels
    for key, rows in records.items():
        if rows:
            payload[key] = rows
    snapshot = digest(payload)
    sid = "snapshot:" + snapshot
    nodes, edges = {sid: {"id": sid, "type": "Snapshot", **({"captured_at": seen_at} if seen_at else {})}}, []
    cid_of = {}
    for name in sorted(concepts):
        token = concept_meta[name].get("concept_id") or name
        cid = f"concept:{token}"
        cid_of[name] = cid
        nodes[cid] = {"id": cid, "type": "Concept", "name": name,
                      "elements_observed": concepts[name] is not None}
        if concept_meta[name].get("concept_id"):
            nodes[cid]["concept_id"] = concept_meta[name]["concept_id"]
        if concept_meta[name].get("notation"):
            nodes[cid]["notation"] = concept_meta[name]["notation"]
        if concepts[name] is not None:
            oid = f"observation:{snapshot}:{cid}"
            nodes[oid] = {"id": oid, "type": "Observation", "snapshot": sid, **when}
            edges.append({"kind": "observes", "source": oid, "target": cid, "basis": "observed", **when})
            edges.append({"kind": "derived_from", "source": oid, "target": sid, "basis": "observed", **when})
            c_basis = concept_meta[name]["basis"]
            for el in concepts[name]:
                eid = f"elem:{el}"
                nodes.setdefault(eid, {"id": eid, "type": "Element", "name": el})
                edges.append({"kind": "hasElement", "source": eid, "target": cid, "basis": c_basis, "lock": oid, **when})
        for el in maybe.get(name, ()):  # 🤷 a link allowed to be wrong: walked by nothing, decides nothing
            eid = f"elem:{el}"
            nodes.setdefault(eid, {"id": eid, "type": "Element", "name": el})
            edges.append({"kind": "hasElement", "source": eid, "target": cid, "basis": "hypothesis", "maybe": True, "lock": sid, **when})
        # 名前の辺が無い概念でも、構造化ラベルの lock は同じ規則（見た概念は観測、まだならスナップショット）。
        name_lock = f"observation:{snapshot}:{cid}" if concepts[name] is not None else sid
        for el in called.get(name, ()):  # 🏷️ the name side: how it is read, written, translated or called
            nid = f"name:{el}"
            nodes.setdefault(nid, {"id": nid, "type": "Name", "name": el})
            edges.append({"kind": "hasName", "source": nid, "target": cid, "basis": "observed", "lock": name_lock, **when})
        for row in labels:
            if row["concept"] != name:
                continue
            # 概念ごとに別ノード。同じ日本語というだけでは、別の概念と結ばない。
            nid = "label:" + token + ":" + row["lang"] + ":" + row["kind"] + ":" + row["text"]
            if row.get("context"):
                nid += ":" + row["context"]
            node = {"id": nid, "type": "Name", "name": row["text"], "lang": row["lang"], "label_kind": row["kind"]}
            edge = {"kind": "hasName", "source": nid, "target": cid, "basis": "observed", "lang": row["lang"],
                    "label_kind": row["kind"], "lock": name_lock, **when}
            if row.get("context"):
                node["context"] = row["context"]
                edge["context"] = row["context"]
            nodes.setdefault(nid, node)
            edges.append(edge)
        info = defined["concepts"][name]
        for el in info["definition"]["genus"]:
            eid = f"elem:{el}"
            nodes.setdefault(eid, {"id": eid, "type": "Element", "name": el})
            edges.append({"kind": "genusElement", "source": eid, "target": cid, "basis": info["basis"]})
        for el in info["definition"]["differentia"]:
            eid = f"elem:{el}"
            nodes.setdefault(eid, {"id": eid, "type": "Element", "name": el})
            edges.append({"kind": "differentiaElement", "source": eid, "target": cid, "basis": info["basis"]})
    for pair in pairs:
        a, b = cid_of[pair["left"]], cid_of[pair["right"]]
        extra = {k: v for k, v in pair.items() if k not in ("left", "right")}
        edges.append({"kind": "similarTo", "source": a, "target": b, **extra})
        edges.append({"kind": "similarTo", "source": b, "target": a, **extra})
    speeches = {}
    for row in records["observations"]:
        # 発言は要素の観測とは別の Observation。actor と role はフィールドで、人や役職のノードは作らない。
        oid = "observation:" + snapshot + ":note:" + digest(row)
        node = {"id": oid, "type": "Observation", "snapshot": sid, **when}
        for field in ("actor", "role", "evidence", "context", "statement"):
            if field in row:
                node[field] = row[field]
        if "slots" in row:
            node["slots"] = row["slots"]
        nodes[oid] = node
        cid = cid_of[row["concept"]]
        edges.append({"kind": "observes", "source": oid, "target": cid, "basis": "observed", "lock": oid, **when})
        edges.append({"kind": "derived_from", "source": oid, "target": sid, "basis": "observed", "lock": oid, **when})
        speeches.setdefault(row["concept"], []).append(oid)
    for row in records["judgments"]:
        # 判断は観測とは別の記録。basis を書かなければ hypothesis のままで、自動では上げない。
        jid = "judgment:" + digest({k: v for k, v in row.items()})
        basis = row["basis"]
        node = {"id": jid, "type": "Judgment", "basis": basis, **when}
        for field in ("actor", "role", "evidence", "context", "statement"):
            if field in row:
                node[field] = row[field]
        nodes[jid] = node
        edges.append({"kind": "judges", "source": jid, "target": cid_of[row["concept"]], "basis": basis, "lock": jid, **when})
        for target_name in row["rests_on"]:
            noted = speeches.get(target_name) or []
            if not noted and concepts[target_name] is not None:
                noted = [f"observation:{snapshot}:{cid_of[target_name]}"]
            if not noted:
                raise ValueError(f"判断が拠る観測がありません: {target_name!r}")
            for tid in noted:
                edges.append({"kind": "restsOn", "source": jid, "target": tid, "basis": basis, "lock": jid, **when})
    for row in records["candidates"]:
        # 外部候補は Name への hypothesis だけ。names には写さないので、表記の確定にはならない。
        nid = "candidate:" + cid_of[row["concept"]].split(":", 1)[1] + ":" + row["lang"] + ":" + row["kind"] + ":" + row["text"]
        nodes.setdefault(nid, {"id": nid, "type": "Name", "name": row["text"], "lang": row["lang"],
                               "label_kind": row["kind"], "candidate": True})
        edge = {"kind": "hasName", "source": nid, "target": cid_of[row["concept"]], "basis": "hypothesis",
                "lang": row["lang"], "label_kind": row["kind"], "candidate": True, "lock": sid, **when}
        if row.get("context"):
            edge["context"] = row["context"]
        if "claimed_basis" in row:
            edge["claimed_basis"] = row["claimed_basis"]
        if "confidence" in row:
            edge["confidence"] = row["confidence"]
        edges.append(edge)
    return {"schema": "ontautology-concept-graph/1",
            "nodes": [nodes[k] for k in sorted(nodes)],
            "edges": edges}


# ---------------------------------------------------------------- command line

def _read_json(path):
    """A file or one UTF-8 JSON document on stdin; no transport dependencies."""
    if str(path) == "-":
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        value = stream.read()
        return json.loads(value.decode("utf-8") if isinstance(value, bytes) else value)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load(path, load=None):
    """(data, core edges, node ids or None) from a file: what ``load`` knows first, then a concept corpus, then a
    plain {"edges": [...], "nodes": [...]} file."""
    data = _read_json(path)
    found = load(data) if load else None
    if found:
        return found
    if data.get("schema") == CONCEPT_SCHEMA or ("concepts" in data and "similar" in data and "edges" not in data):
        projected = concept_edges(data)
        return data, projected["edges"], [node["id"] for node in projected["nodes"]]
    return data, data["edges"], data.get("nodes")


def main(argv=None, *, commands=(), load=None):
    """0 = answered, 1 = input error, 2 = answered and something needs a look (findings, a cycle, blocked or unknown).

    A use of the core (gh_audit/gh_audit.py) passes ``commands`` — (name, help, add_arguments(parser), run(args) →
    (answer, needs_a_look)) — and ``load(data)`` → (data, edges, node ids) or None for its own files, so the
    core commands read those files too and there is one command line, one stdin rule and one set of exit codes.
    """
    parser = argparse.ArgumentParser(description="🧪 check · 💥 reach · 🔎 why · 🔁 cycles · 🪜 order / ladder · 🔑 keys · 🧩 define / roundtrip"
                                     + "".join(f" · {name}" for name, *_ in commands))
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("check", "shape, references, basis, duplicates"), ("ladder", "edges per basis")):
        sub.add_parser(name, help=text).add_argument("graph", type=Path)
    for name, text, terms in (("reach", "what a change of these nodes touches", "node ids"), ("why", "what these nodes rest on", "node ids"),
                              ("order", "batches, sources first", "edge kinds that mean 'before' (default: all)"),
                              ("cycles", "representative cycles", "edge kinds to look at (default: all)"),
                              ("keys", 'can these field sets be the key of "items"', "field sets like id+run"),
                              ("define", "derive genus + differentia definitions from similar concept pairs", "concept names (default: all)"),
                              ("roundtrip", "reverse-lookup concepts that satisfy all given elements", "elements")):
        add = sub.add_parser(name, help=text)
        add.add_argument("graph", type=Path)
        add.add_argument("terms", nargs="*" if name in ("order", "cycles", "define") else "+", help=terms)
    extra = {}
    for name, text, arguments, run in commands:
        arguments(sub.add_parser(name, help=text))
        extra[name] = run
    for command in sub.choices.values():
        command.add_argument("-o", "--output", type=Path, help="write here instead of stdout")
    args = parser.parse_args(argv)
    try:
        paths = [p for key, value in vars(args).items() if key != "output" for p in (value if isinstance(value, list) else [value])]
        if sum(isinstance(p, Path) and str(p) == "-" for p in paths) > 1:
            raise ValueError("stdin '-' may be used only once per command")
        look = False
        if args.command in extra:
            answer, look = extra[args.command](args)
        elif args.command == "define":
            answer = define_concepts(_read_json(args.graph), args.terms or None)
            look = bool(answer["unknown"]) or any(c["status"] != "unique" for c in answer["concepts"].values())
        elif args.command == "roundtrip":
            answer = roundtrip_elements(_read_json(args.graph), args.terms)
            look = answer["verdict"] != "unique"
        else:
            data, edges, nodes = _load(args.graph, load)
            if args.command == "check":
                answer = check(edges, nodes)
                look = bool(answer)
            elif any(finding["kind"] == "shape" for finding in check(edges)):
                raise ValueError("the graph has malformed edges; run check")
            elif args.command == "reach":
                answer = reach(edges, args.terms)
                look = bool(answer["unknown"])
            elif args.command == "why":
                answer = [why(edges, node) for node in args.terms]
                look = any(not found["rows"] for found in answer)
            elif args.command == "cycles":
                answer = cycles([e for e in edges if not args.terms or e["kind"] in args.terms])
                look = bool(answer)
            elif args.command == "order":
                answer = order([e for e in edges if not args.terms or e["kind"] in args.terms], nodes=() if args.terms else nodes or ())
                look = answer["cycle"] is not None
            elif args.command == "ladder":
                answer = ladder(edges)
            else:
                answer = key_report(data.get("items") or [], [tuple(term.split("+")) for term in args.terms])
                look = any(found["verdict"] != "key" for found in answer.values())
        text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ontautology: {error}", file=sys.stderr)
        return 1
    return 2 if look else 0


if __name__ == "__main__":
    raise SystemExit(main())

