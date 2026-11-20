"""Validate a caller-supplied vocabulary and test candidate identities."""
import json

__all__ = ["classes", "violations", "identity"]


def classes(relations):
    """The classes a vocabulary names, sorted."""
    return sorted({kind for domains, range_type in relations.values() for kind in (*domains, range_type)})


def violations(graph, relations):
    """Every place ``graph`` ({"nodes": [{"id", "type"}], "edges": [{"source", "relation", "target"}]}) leaves
    the vocabulary: a node id used twice, an unknown class, an edge to a node that is not there, an unknown
    relation, a relation between the wrong classes. An empty list means the vocabulary holds for these
    nodes and edges — nothing more."""
    known, findings, nodes = set(classes(relations)), [], {}
    for index, node in enumerate(graph["nodes"]):
        if node["id"] in nodes:
            findings.append({"kind": "duplicate-node", "node": index, "detail": f"{node['id']} is listed twice"})
        nodes[node["id"]] = node
        if node["type"] not in known:
            findings.append({"kind": "unknown-class", "node": index, "detail": f"{node['id']} has class {node['type']!r}"})
    for index, edge in enumerate(graph["edges"]):
        missing = [end for end in ("source", "target") if edge[end] not in nodes]
        for end in missing:
            findings.append({"kind": "missing-reference", "edge": index, "detail": f"{end} {edge[end]} is not a known node"})
        if edge["relation"] not in relations:
            findings.append({"kind": "unknown-relation", "edge": index, "detail": f"unknown relation {edge['relation']!r}"})
        elif not missing:
            domains, range_type = relations[edge["relation"]]
            source, target = nodes[edge["source"]]["type"], nodes[edge["target"]]["type"]
            if source not in domains or target != range_type:
                findings.append({"kind": "domain-range", "edge": index,
                                 "detail": f"{edge['relation']} joins {source} → {target}, expected {' | '.join(domains)} → {range_type}"})
    return findings


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


def identity(items, candidates):
    """Which attribute set may be promoted from handle to key: the first candidate, in the caller's order of
    preference, that is complete and unique over these entries (core ``key_report`` verdict ``key``).

    ``key`` is None while no candidate qualifies — the entries keep their handles and the report says why
    (collides, repeat, incomplete). One more entry can take a key away again; identity is settled last.
    """
    candidates = [tuple(fields) for fields in candidates]
    report = key_report(items, candidates)
    key = next((fields for fields in candidates if report["+".join(fields)]["verdict"] == "key"), None)
    return {"key": list(key) if key else None, "report": report}
