"""Run the six independent KG-P01 queries. Use python -m examples.kg_poc."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ontautology import reach
from ontautology_shared._onto.knowledgegraph import relation_cycles

FIXTURE = Path(__file__).with_name("kg-p01.json")


def snapshot(nodes, relationships, changes):
    """Apply a case delta to a fresh ID-keyed graph."""
    nodes = {node["id"]: dict(node) for node in nodes}
    for node in changes.get("addNodes", []):
        if node["id"] in nodes:
            raise ValueError(f"duplicate node: {node['id']}")
        nodes[node["id"]] = dict(node)
    for patch in changes.get("patchNodes", []):
        nodes[patch["id"]].update(patch)
    for item in changes.get("removeProperties", []):
        nodes[item["id"]].pop(item["field"], None)
    return nodes, [*relationships, *changes.get("addRelationships", [])]


def baseline(base_nodes, relationships, query, args):
    nodes, edges = snapshot(base_nodes, relationships, args)

    def targets(start, kind):
        return sorted(e["to"] for e in edges if e["from"] == start and e["type"] == kind)

    def paths(case):
        for judgment in targets(case, "HAS_JUDGMENT"):
            for evidence in targets(judgment, "SUPPORTED_BY"):
                item = nodes[evidence]
                if item.get("status") == "active" and item.get("source"):
                    yield {"caseId": case, "judgmentId": judgment, "evidenceId": evidence,
                           "source": item["source"]}

    if query == "Q01":
        rows = list(paths(args["caseId"]))
        if len(rows) == 1:
            return rows[0]
        return {"paths": rows, "decision": "pending" if rows else "unknown"}

    if query == "Q02":
        concept = args["conceptId"]
        if concept not in nodes:
            return {"ancestors": [], "decision": "unknown"}
        hierarchy = [{"kind": "IS_A", "source": e["from"], "target": e["to"]}
                     for e in edges if e["type"] == "IS_A"]
        rows = reach(hierarchy, [concept], limit=len(nodes) + 1)["rows"]
        result = {"ancestors": sorted(row["node"] for row in rows)}
        cycles = relation_cycles(hierarchy)
        if cycles:
            result["cycles"] = cycles
        return result

    judgments = sorted(key for key, n in nodes.items() if n["type"] == "Judgment")
    if query == "Q03":
        return {"violations": [{"id": key, "field": "source", "code": "required"}
                               for key in judgments if not nodes[key].get("source")]}

    if query == "Q04":
        matches = sorted(key for key, n in nodes.items()
                         if n["type"] == "Concept" and n["label"] == args["label"])
        conflicts = []
        for case in sorted(key for key, n in nodes.items() if n["type"] == "Case"):
            if not set(targets(case, "ABOUT")).intersection(matches):
                continue
            rows = list(paths(case))
            # KG-P01-v1 expresses the two opposing conclusions through these labels.
            opposing = [r for r in rows if nodes[r["judgmentId"]]["label"] in ("対象", "対象外")]
            if len({nodes[r["judgmentId"]]["label"] for r in opposing}) == 2:
                conflicts.extend({"id": r["judgmentId"], "evidenceId": r["evidenceId"]}
                                 for r in opposing)
        return {"matchingConcepts": matches, "conflictingJudgments": conflicts,
                "merged": 0, "decision": "pending" if conflicts else "no_conflict"}

    if query == "Q05":
        active, history, issues = set(), set(), []
        for key in judgments:
            evidence = targets(key, "SUPPORTED_BY")
            current = [eid for eid in evidence if nodes[eid].get("status") == "active"]
            history.update(evidence)
            active.update(current)
            if not current:
                issues.append({"id": key, "code": "no_active_evidence"})
            if nodes[key].get("confidence") is None:
                issues.append({"id": key, "code": "missing_confidence"})
        return {"activeEvidence": sorted(active), "historicalEvidence": sorted(history),
                "issues": issues}

    if query == "Q06":
        allowed = set(args["knownEvidenceIds"])
        citations = {r["evidenceId"] for r in paths(args["caseId"])} & allowed
        suggestion = args["suggestedConceptId"]
        return {"citationIds": sorted(citations),
                "unapprovedCandidateIds": [] if suggestion in nodes else [suggestion],
                "graphWrites": 0}

    raise ValueError(f"unknown query: {query}")


def evaluate(fixture, adapter=baseline):
    """An adapter receives only initial graph, query ID and input, never the oracle."""
    rows = []
    for case in fixture["cases"]:
        actual = adapter(deepcopy(fixture["nodes"]), deepcopy(fixture["relationships"]),
                         case["id"], deepcopy(case["input"]))
        rows.append({"id": case["id"], "actual": actual, "expected": case["expected"],
                     "passed": actual == case["expected"]})
    return rows


if __name__ == "__main__":
    raw = FIXTURE.read_bytes()
    fixture = json.loads(raw)
    rows = evaluate(fixture)
    print(json.dumps({"backend": "python-stdlib", "fixture": fixture["id"],
                      "sha256": hashlib.sha256(raw).hexdigest(), "cases": rows},
                     ensure_ascii=False, indent=2))
    raise SystemExit(0 if all(row["passed"] for row in rows) else 1)
