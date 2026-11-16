"""OnTautoLogy: look across repositories as one small knowledge graph (Python 3.11+, standard library).

The name: take an ontology up to the level of a tautology. A statement starts as a guess, becomes something
seen, and only at the top is true whatever the data — a proof. One file, two parts:

1. Core — logic any such graph needs, on plain dicts and lists; knows no repository and fetches nothing.
     check  reach  why  cycles  order  ladder  key_report
2. Cross-repository audit — the first use: PR audit snapshots of many repositories become one graph that
   keeps every observation (head, base, runs, attempts, jobs, files, dependencies, tasks) with its time.
     audit  validate  plan  observation_diff  turtle  edges_of

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
from urllib.parse import quote

# ---------------------------------------------------------------- 1. core

BASIS = ("hypothesis", "derived", "observed", "proof")
__all__ = ["BASIS", "check", "reach", "why", "cycles", "order", "ladder", "key_report",
           "audit", "validate", "plan", "observation_diff", "turtle", "edges_of",
           "define_concepts", "roundtrip_elements", "concept_edges", "main"]


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


# ---------------------------------------------------------------- 2. cross-repository audit

KG_SCHEMA = "ontautology/1"
NAMESPACE = "https://github.com/myon-bioinformatics/OnTautoLogy#"
STATES = ("調査中", "着手中", "完了", "保留", "ブロッカー")
# Relation: (domain, range). Observation links retain temporal head/base facts.
RELATIONS = {
    "hasIssue": (("Observation",), "Issue"),
    "hasReview": (("Observation",), "Review"),
    "hasJob": (("WorkflowRun",), "Job"),
    "hasPin": (("Observation",), "FixedSHA"),
    "pinsCommit": (("FixedSHA",), "Commit"),
    "hasArtifact": (("Observation",), "Artifact"),
    "generatedFrom": (("Artifact",), "Commit"),
    "hasEvidence": (("Observation",), "Evidence"),
    "missingEvidence": (("Observation",), "EvidenceGap"),
    "missingFromMain": (("Observation",), "MainGap"),
    "hasTask": (("Observation",), "Task"),
    "precedes": (("Task",), "Task"),
    "hasCompletion": (("Observation",), "CompletionRecord"),
    "verifiesCommit": (("CompletionRecord", "Task"), "Commit"),
    "belongsTo": (("PullRequest", "Commit", "Branch", "File", "WorkflowRun"), "Repository"),
    "observes": (("Observation",), "PullRequest"),
    "hasHead": (("Observation",), "Commit"),
    "hasBase": (("Observation",), "Commit"),
    "hasMain": (("Observation",), "Commit"),
    "targetsBranch": (("Observation",), "Branch"),
    "changesFile": (("Observation",), "File"),
    "hasRun": (("Observation",), "WorkflowRun"),
    "runsAt": (("WorkflowRun",), "Commit"),
    "dependsOn": (("PullRequest",), "PullRequest"),
    "overlapsWith": (("PullRequest",), "PullRequest"),
}


def _classes():
    """The classes are exactly the types the relations name; no second list to keep in step."""
    return sorted({kind for domains, range_type in RELATIONS.values() for kind in (*domains, range_type)})


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("observed_at must be an ISO timestamp with timezone")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("observed_at must include a timezone")
    return result


def repository(value):
    value = str(value or "")
    if value.count("/") != 1 or any(c.isspace() for c in value) or any(c in value for c in "#@:"):
        raise ValueError(f"repository must be owner/name: {value!r}")
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("invalid repository")
    return value


def pr_id(value, owner):
    value = str(value)
    if value.startswith("https://github.com/"):
        parts = value.removeprefix("https://github.com/").split("/")
        if len(parts) != 4 or parts[2] != "pull":
            raise ValueError("dependency URL must identify a PR")
        value = f"{parts[0]}/{parts[1]}#{parts[3]}"
    repo, sep, number = value.rpartition("#")
    if not sep or not number.isdigit() or int(number) < 1:
        raise ValueError(f"invalid PR reference: {value!r}")
    if "/" not in repo:
        repo = owner + "/" + repo
    return f"pr:{repository(repo)}#{int(number)}"


class Graph:
    def __init__(self):
        self.nodes = {}
        self.edges = {}

    def node(self, ident, node_type, **properties):
        node = {"id": ident, "type": node_type, **properties}
        if ident in self.nodes and self.nodes[ident] != node:
            raise ValueError(f"conflicting node identity: {ident}")
        self.nodes[ident] = node
        return ident

    def edge(self, source, relation, target, **evidence):
        edge = {"source": source, "relation": relation, "target": target, **evidence}
        self.edges[digest(edge)] = edge

    def repo(self, name):
        return self.node("repo:" + name, "Repository", name=name)

    def pr(self, ident):
        name, number = ident.removeprefix("pr:").rsplit("#", 1)
        self.node(ident, "PullRequest", number=int(number), url=f"https://github.com/{name}/pull/{number}")
        self.edge(ident, "belongsTo", self.repo(name))
        return ident

    def commit(self, name, sha):
        if not isinstance(sha, str) or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError(f"expected full lowercase commit SHA: {sha!r}")
        ident = self.node(f"commit:{name}@{sha}", "Commit", sha=sha)
        self.edge(ident, "belongsTo", self.repo(name))
        return ident

    def export(self):
        return {"schema": KG_SCHEMA, "ontology": {"namespace": NAMESPACE, "classes": _classes(),
                "relations": {k: {"domain": list(v[0]), "range": v[1]} for k, v in RELATIONS.items()}},
                "nodes": sorted(self.nodes.values(), key=lambda x: x["id"]),
                "edges": sorted(self.edges.values(), key=lambda x: (x["source"], x["relation"], x["target"], digest(x)))}



def audit_entities(graph, row, observation, repo, observed):
    """Optional audit facts share one vocabulary and stay scoped to observations.

    Issues/reviews/pins/artifacts/evidence/gaps/tasks/completion_records are lists
    of objects. Jobs live under each run. No GitHub state is inferred or changed.
    Complete tasks/records require evidence_url and a full verified_sha.
    """
    evidence = {"observation": observation, "observed_at": observed}
    def entries(name):
        values = row.get(name, [])
        if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
            raise ValueError(name + " must be a list of objects")
        return values
    def entity(kind, value):
        ident = f"{kind.lower()}:{observation}:{digest(value)}"
        # JSON-valued details are encoded as a literal, also valid RDF/Turtle.
        properties = {k:v for k,v in value.items() if k not in ("id", "type", "detail")
                      and isinstance(v, (str, int, float, bool, type(None)))}
        if "id" in value:
            properties["external_id"] = str(value["id"])
        return graph.node(ident, kind, detail=json.dumps(value, ensure_ascii=False, sort_keys=True), **properties)
    for key, kind, relation in (("issues", "Issue", "hasIssue"), ("reviews", "Review", "hasReview"),
                                 ("evidence", "Evidence", "hasEvidence"), ("gaps", "EvidenceGap", "missingEvidence")):
        for value in entries(key):
            graph.edge(observation, relation, entity(kind, value), **evidence)
    for value in entries("pins"):
        ident = entity("FixedSHA", value)
        source_repo = repository(value.get("repository", repo))
        graph.edge(observation, "hasPin", ident, **evidence)
        graph.edge(ident, "pinsCommit", graph.commit(source_repo, value["sha"]), **evidence)
    for value in entries("artifacts"):
        ident = entity("Artifact", value)
        graph.edge(observation, "hasArtifact", ident, **evidence)
        if value.get("source_sha"):
            source_repo = repository(value.get("repository", repo))
            graph.edge(ident, "generatedFrom", graph.commit(source_repo, value["source_sha"]), **evidence)
    if row.get("contained_in_main") is False:
        ident = graph.node("main-gap:" + observation, "MainGap", target_repository=repo,
                           basis="explicit contained_in_main=false; not inferred from unequal SHAs")
        graph.edge(observation, "missingFromMain", ident, **evidence)
    tasks = {}
    for value in entries("tasks"):
        key = value.get("id")
        if not isinstance(key, str) or not key or key in tasks:
            raise ValueError("task IDs must be nonempty and unique per observation")
        state = value.get("state", "調査中")
        if state not in STATES:
            raise ValueError("invalid task state")
        phase = value.get("phase", "確認")
        if phase not in ("確認", "修正", "統合順序", "再検証"):
            raise ValueError("invalid task phase")
        ident = graph.node("task:" + observation + ":" + key, "Task", key=key, state=state,
                           phase=phase, title=value.get("title", key), acceptance=value.get("acceptance"))
        tasks[key] = ident
        graph.edge(observation, "hasTask", ident, **evidence)
        if state == "完了":
            if not value.get("evidence_url") or not value.get("verified_sha"):
                raise ValueError("completed task needs evidence_url and verified_sha")
            graph.edge(ident, "verifiesCommit", graph.commit(repo, value["verified_sha"]),
                       evidence_url=value["evidence_url"], **evidence)
    for value in entries("tasks"):
        for key in value.get("after", []):
            if key not in tasks:
                raise ValueError("unknown task predecessor: " + str(key))
            graph.edge(tasks[key], "precedes", tasks[value["id"]], basis="recommended work order", **evidence)
    for value in entries("completion_records"):
        if not value.get("evidence_url") or not value.get("verified_sha"):
            raise ValueError("completion record needs evidence_url and verified_sha")
        ident = graph.node("completion:" + observation + ":" + digest(value), "CompletionRecord",
                           state="完了", evidence_url=value["evidence_url"], title=value.get("title"))
        graph.edge(observation, "hasCompletion", ident, **evidence)
        graph.edge(ident, "verifiesCommit", graph.commit(repo, value["verified_sha"]), **evidence)


def observation_diff(before, after):
    """Compare latest PR observations; retain SHA/run/job/evidence differences."""
    def facts(graph):
        validate(graph)
        # Reuse temporal conflict detection rather than silently choosing a tie.
        plan(graph)
        nodes = {n["id"]: n for n in graph["nodes"]}
        latest = {}
        for edge in graph["edges"]:
            if edge["relation"] == "observes":
                obs = nodes[edge["source"]]
                if edge["target"] not in latest or timestamp(obs["observed_at"]) > timestamp(latest[edge["target"]]["observed_at"]):
                    latest[edge["target"]] = obs
        result = {}
        for pr, obs in latest.items():
            values = {k:v for k,v in obs.items() if k not in ("id", "snapshot", "observed_at", "source")}
            def claim(edge):
                target = nodes[edge["target"]]
                return {"relation": edge["relation"], "target": {k:v for k,v in target.items() if k != "id"},
                        "facts": {k:v for k,v in edge.items() if k not in ("source", "target", "observation", "observed_at", "snapshot")}}
            relevant = [edge for edge in graph["edges"] if edge["source"] == obs["id"] or
                        edge.get("observation") == obs["id"]]
            run_ids = {edge["target"] for edge in relevant if edge["relation"] == "hasRun"}
            relevant.extend(edge for edge in graph["edges"] if edge["source"] in run_ids and edge["relation"] == "runsAt")
            values["claims"] = sorted((claim(edge) for edge in relevant), key=digest)
            result[pr] = values
        return result
    old, new = facts(before), facts(after)
    return {"schema": "ontautology/diff/1", "added": sorted(new.keys() - old.keys()),
            "removed": sorted(old.keys() - new.keys()),
            "changed": [{"pr": key, "before": old[key], "after": new[key]}
                        for key in sorted(old.keys() & new.keys()) if old[key] != new[key]]}

def audit(documents, *, owner="myon-bioinformatics"):
    """Cross-repository PR audit: integration-audit/3 snapshots → one graph with history. Never fetches or
    mutates GitHub. A snapshot wrapped as {"aoi_integration": {...}} (the site's observation export) is unwrapped."""
    graph = Graph()
    for doc in documents:
        doc = doc.get("aoi_integration", doc)
        if doc.get("schema") != "integration-audit/3":
            raise ValueError("expected integration-audit/3; export 統合証跡JSON from the audit view")
        observed = doc.get("captured_at")
        timestamp(observed)
        snapshot = digest(doc)
        overlap = {}
        for row in doc["records"]:
            repo = row.get("repository", "")
            if "/" not in repo:
                repo = owner + "/" + repo
            repo = repository(repo)
            ident = graph.pr(pr_id(f"{repo}#{row['number']}", owner))
            source = f"https://github.com/{repo}/pull/{row['number']}"
            facts = {key: row.get(key) for key in ("merged", "mergeable", "contained_in_main", "draft")}
            state = row.get("state")
            if state not in STATES:
                raise ValueError(f"invalid audit state: {state!r}")
            for key, value in facts.items():
                if value is not None and not isinstance(value, bool):
                    raise ValueError(f"{key} must be boolean or null")
            files = row.get("files")
            if files is not None and not isinstance(files, list):
                raise ValueError("files must be a list or null")
            observation = graph.node(f"observation:{snapshot}:{ident}", "Observation", observed_at=observed,
                                     source=source, snapshot=snapshot, state=state,
                                     files_observed=isinstance(files, list), **facts)
            graph.edge(observation, "observes", ident)
            for key, relation in (("head_sha", "hasHead"), ("base_sha", "hasBase"), ("main_sha", "hasMain")):
                if row.get(key):
                    graph.edge(observation, relation, graph.commit(repo, row[key]))
            if row.get("base"):
                branch = graph.node(f"branch:{repo}:{row['base']}", "Branch", name=row["base"])
                graph.edge(branch, "belongsTo", graph.repo(repo))
                graph.edge(observation, "targetsBranch", branch)
            for path in sorted(set(files or [])):
                if not isinstance(path, str) or not path or path.startswith("/") or ".." in path.split("/"):
                    raise ValueError("changed file paths must be repository-relative")
                file = graph.node(f"file:{repo}:{path}", "File", path=path)
                graph.edge(file, "belongsTo", graph.repo(repo))
                graph.edge(observation, "changesFile", file)
                overlap.setdefault(file, []).append(ident)
            for dep in row.get("dependencies", []):
                graph.edge(ident, "dependsOn", graph.pr(pr_id(dep, owner)), observation=observation,
                           observed_at=observed, evidence_url=source, basis="audit snapshot; curator claim")
            for scope, runs in (("pr_head", row.get("runs", [])), ("main", row.get("postmerge_runs", []))):
                for run in runs:
                    run_id, attempt = run.get("id"), run.get("run_attempt")
                    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
                        raise ValueError("workflow run id must be a positive integer")
                    if attempt is not None and (not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1):
                        raise ValueError("run_attempt must be a positive integer or null")
                    rid = f"run:{repo}:{run_id}:attempt:{attempt if attempt is not None else 'unknown'}"
                    # Run outcomes are observations, not timeless properties of the run.
                    graph.node(rid, "WorkflowRun", run_id=run_id, attempt=attempt, name=run.get("name"),
                               url=f"https://github.com/{repo}/actions/runs/{run_id}")
                    graph.edge(rid, "belongsTo", graph.repo(repo))
                    graph.edge(observation, "hasRun", rid, scope=scope, conclusion=run.get("conclusion"),
                               status=run.get("status"), event=run.get("event"),
                               workflow_id=run.get("workflow_id"), observed_at=observed)
                    for job in run.get("jobs", []):
                        job_id = job.get("id")
                        if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id < 1:
                            raise ValueError("job id must be a positive integer")
                        jid = graph.node(f"job:{repo}:{run_id}:attempt:{attempt}:{job_id}", "Job",
                                         job_id=job_id, run_id=run_id, attempt=attempt, name=job.get("name"))
                        graph.edge(rid, "hasJob", jid, observation=observation, observed_at=observed,
                                   conclusion=job.get("conclusion"), status=job.get("status"),
                                   evidence_url=job.get("html_url"))
                    if run.get("head_sha"):
                        graph.edge(rid, "runsAt", graph.commit(repo, run["head_sha"]))
            audit_entities(graph, row, observation, repo, observed)
        for file, prs in overlap.items():
            prs = sorted(set(prs))
            for i, left in enumerate(prs):
                for right in prs[i + 1:]:
                    graph.edge(left, "overlapsWith", right, file=file, snapshot=snapshot,
                               observed_at=observed, basis="derived: same repository and changed path; not a conflict")
    result = graph.export()
    validate(result)
    return result


def validate(graph):
    if graph.get("schema") != KG_SCHEMA:
        raise ValueError("unsupported graph schema")
    nodes = {n["id"]: n for n in graph["nodes"]}
    classes = _classes()
    if len(nodes) != len(graph["nodes"]):
        raise ValueError("duplicate node ID")
    for node in nodes.values():
        if node["type"] not in classes:
            raise ValueError("unknown ontology class")
        if node["type"] in ("Task", "CompletionRecord") and node.get("state") not in STATES:
            raise ValueError("invalid task/completion state")
        if node["type"] == "Observation":
            timestamp(node["observed_at"])
            if node.get("state") not in STATES:
                raise ValueError("invalid observation state")
    for edge in graph["edges"]:
        if edge["source"] not in nodes or edge["target"] not in nodes:
            raise ValueError("dangling edge")
        if edge["relation"] not in RELATIONS:
            raise ValueError("unknown ontology relation")
        domains, range_type = RELATIONS[edge["relation"]]
        if nodes[edge["source"]]["type"] not in domains or nodes[edge["target"]]["type"] != range_type:
            raise ValueError("relation domain/range mismatch")
        if edge["relation"] == "dependsOn":
            obs = nodes.get(edge.get("observation"), {})
            if obs.get("type") != "Observation":
                raise ValueError("dependency claim needs an observation")
    return graph


def plan(graph):
    """Dependency order only. Never equates CI success with merge permission."""
    validate(graph)
    nodes = {n["id"]: n for n in graph["nodes"]}
    latest = {}
    for edge in graph["edges"]:
        if edge["relation"] == "observes":
            obs = nodes[edge["source"]]
            target = edge["target"]
            if target not in latest or timestamp(obs["observed_at"]) > timestamp(latest[target]["observed_at"]):
                latest[target] = obs
            elif timestamp(obs["observed_at"]) == timestamp(latest[target]["observed_at"]) and obs["id"] != latest[target]["id"]:
                raise ValueError("ambiguous observations at the same time; select a snapshot")
    pending = {key for key, obs in latest.items() if obs.get("contained_in_main") is not True}
    dependencies = {key: set() for key in pending}
    missing = {key: set() for key in pending}
    for edge in graph["edges"]:
        source, target = edge["source"], edge["target"]
        if edge["relation"] != "dependsOn" or source not in pending:
            continue
        if edge["observation"] != latest[source]["id"]:
            continue
        if target not in latest:
            missing[source].add(target)
        elif target in pending:
            dependencies[source].add(target)
    # Core order(): prerequisite first; a cycle blocks itself and what waits on it, nothing else.
    found = order([{"kind": "dependsOn", "source": need, "target": key} for key, needs in dependencies.items() for need in sorted(needs)],
                  nodes=sorted(pending))
    cycle = found["cycle"] or []
    waiting = [{"kind": "dependsOn", "source": need, "target": key} for key, needs in dependencies.items() for need in needs]
    unmet = sorted(key for key, deps in missing.items() if deps)
    blocked = set(found["blocked"]) | set(unmet) | {row["node"] for row in reach(waiting, unmet)["rows"]}
    order_ = [key for batch in found["batches"] for key in batch]
    return {"order": [key for key in order_ if key not in blocked], "blocked": sorted(blocked),
            "missing": {k: sorted(v) for k, v in missing.items() if v}, "cycle": cycle,
            "note": "依存関係だけの順序。CI・レビュー・競合・保留の確認は別途必要。未観測の依存先は完了扱いにしない。"}


def edges_of(graph):
    """An audit graph as core edges, so reach / why / cycles / ladder answer on it too.

    Core direction is "depended on → look again". Three relations point the other way in the audit vocabulary
    and are turned round: dependsOn (dependent → prerequisite), changesFile (observation → file) and
    precedes stays as it is (earlier task → later task). overlapsWith has no direction — two PRs touch the
    same path — so it is given both ways; ask cycles and order about dependsOn only. Free-text ``basis``
    notes become the core basis (a note starting with "derived" → derived, anything else → observed).
    """
    edges = []
    for edge in graph["edges"]:
        flip = edge["relation"] in ("dependsOn", "changesFile")
        note = edge.get("basis")
        edges.append({**{k: v for k, v in edge.items() if k not in ("relation", "basis")}, "kind": edge["relation"],
                      "source": edge["target"] if flip else edge["source"], "target": edge["source"] if flip else edge["target"],
                      "basis": "derived" if str(note or "").startswith("derived") else "observed",
                      **({"note": note} if note else {}), **({"lock": edge["observation"]} if edge.get("observation") else {})})
        if edge["relation"] == "overlapsWith":
            edges.append({**edges[-1], "source": edge["target"], "target": edge["source"]})
    return edges


def turtle(graph):
    validate(graph)
    uri = lambda ident: "<urn:ontautology:" + quote(ident, safe="") + ">"
    literal = lambda value: json.dumps(value, ensure_ascii=False)
    lines = [f"@prefix ot: <{NAMESPACE}> .", "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
             "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .", ""]
    for kind in _classes():
        lines.append(f"ot:{kind} a rdfs:Class .")
    for relation, (domains, range_type) in RELATIONS.items():
        lines.append(f"ot:{relation} a rdf:Property ; rdfs:range ot:{range_type} .")
        if len(domains) == 1:
            lines.append(f"ot:{relation} rdfs:domain ot:{domains[0]} .")
    for node in graph["nodes"]:
        lines.append(f"{uri(node['id'])} a ot:{node['type']} .")
        for key, value in node.items():
            if key not in ("id", "type") and value is not None:
                lines.append(f"{uri(node['id'])} ot:{key} {literal(value)} .")
    for edge in graph["edges"]:
        source, relation, target = uri(edge["source"]), "ot:" + edge["relation"], uri(edge["target"])
        # Reify evidence-bearing assertions: history must not become timeless triples.
        attrs = {k: v for k, v in edge.items() if k not in ("source", "relation", "target")}
        if not attrs:
            lines.append(f"{source} {relation} {target} .")
        else:
            claim = uri("claim:" + digest(edge))
            lines.append(f"{claim} a rdf:Statement ; rdf:subject {source} ; rdf:predicate {relation} ; rdf:object {target} .")
            for key, value in attrs.items():
                if value is not None:
                    obj = uri(value) if key in ("observation", "file") else literal(value)
                    lines.append(f"{claim} ot:{key} {obj} .")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 3. concept similarity & definition

CONCEPT_SCHEMA = "ontautology-concepts/1"


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
        items = raw_concepts.items()
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
    return concepts, concept_meta, pairs, neighbors


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


def concept_edges(corpus):
    """Project a concept-similarity corpus onto core edges for check / reach / why / cycles / ladder."""
    concepts, concept_meta, pairs, _ = _normalize_corpus(corpus)
    defined = define_concepts(corpus)
    nodes, edges = {}, []
    for name in sorted(concepts):
        cid = f"concept:{name}"
        nodes[cid] = {"id": cid, "type": "Concept", "name": name,
                      "elements_observed": concepts[name] is not None}
        if concepts[name] is not None:
            c_basis = concept_meta[name]["basis"]
            for el in concepts[name]:
                eid = f"elem:{el}"
                nodes.setdefault(eid, {"id": eid, "type": "Element", "name": el})
                edges.append({"kind": "hasElement", "source": eid, "target": cid, "basis": c_basis})
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
        a, b = f"concept:{pair['left']}", f"concept:{pair['right']}"
        extra = {k: v for k, v in pair.items() if k not in ("left", "right")}
        edges.append({"kind": "similarTo", "source": a, "target": b, **extra})
        edges.append({"kind": "similarTo", "source": b, "target": a, **extra})
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


def _load(path):
    """(data, core edges, node ids or None) from an audit graph, concept corpus, or plain {"edges": [...]} file."""
    data = _read_json(path)
    if data.get("schema") == KG_SCHEMA:
        validate(data)
        return data, edges_of(data), [node["id"] for node in data["nodes"]]
    if data.get("schema") == CONCEPT_SCHEMA or ("concepts" in data and "similar" in data and "edges" not in data):
        projected = concept_edges(data)
        return data, projected["edges"], [node["id"] for node in projected["nodes"]]
    return data, data["edges"], data.get("nodes")


def main(argv=None):
    """0 = answered, 1 = input error, 2 = answered and something needs a look (findings, a cycle, blocked or unknown)."""
    parser = argparse.ArgumentParser(description="🔭 audit across repositories · 🧩 define / roundtrip · 🧪 check · 💥 reach · 🔎 why · 🔁 cycles · 🪜 order / ladder / plan · 🔑 keys · 🐢 turtle · 🆚 diff")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("audit", help="integration-audit/3 snapshots (one or more, kept as history) → graph")
    add.add_argument("inputs", nargs="+", type=Path)
    add.add_argument("--owner", default="myon-bioinformatics", help="owner for repository names given without one")
    add.add_argument("--format", choices=("json", "turtle"), default="json")
    for name, text in (("check", "shape, references, basis, duplicates; an audit graph is validated against its ontology"),
                       ("plan", "audit graph → dependency order of PRs not yet in main"), ("turtle", "audit graph → RDF/Turtle"),
                       ("ladder", "edges per basis")):
        commands.add_parser(name, help=text).add_argument("graph", type=Path)
    for name, text, terms in (("reach", "what a change of these nodes touches", "node ids"), ("why", "what these nodes rest on", "node ids"),
                              ("order", "batches, sources first", "edge kinds that mean 'before' (default: all)"),
                              ("cycles", "representative cycles", "edge kinds to look at (default: all)"),
                              ("keys", 'can these field sets be the key of "items"', "field sets like id+run"),
                              ("define", "derive genus + differentia definitions from similar concept pairs", "concept names (default: all)"),
                              ("roundtrip", "reverse-lookup concepts that satisfy all given elements", "elements")):
        add = commands.add_parser(name, help=text)
        add.add_argument("graph", type=Path)
        add.add_argument("terms", nargs="*" if name in ("order", "cycles", "define") else "+", help=terms)
    add = commands.add_parser("diff", help="two audit graphs → what changed between their latest observations")
    add.add_argument("before", type=Path)
    add.add_argument("after", type=Path)
    for command in commands.choices.values():
        command.add_argument("-o", "--output", type=Path, help="write here instead of stdout")
    args = parser.parse_args(argv)
    try:
        inputs = args.inputs if args.command == "audit" else [args.before, args.after] if args.command == "diff" else [args.graph]
        if sum(str(path) == "-" for path in inputs) > 1:
            raise ValueError("stdin '-' may be used only once per command")
        look = False
        if args.command == "audit":
            answer = audit([_read_json(path) for path in args.inputs], owner=args.owner)
            answer = turtle(answer) if args.format == "turtle" else answer
        elif args.command == "diff":
            answer = observation_diff(*(_read_json(path) for path in (args.before, args.after)))
            look = bool(answer["added"] or answer["removed"] or answer["changed"])
        elif args.command == "define":
            answer = define_concepts(_read_json(args.graph), args.terms or None)
            look = bool(answer["unknown"]) or any(c["status"] != "unique" for c in answer["concepts"].values())
        elif args.command == "roundtrip":
            answer = roundtrip_elements(_read_json(args.graph), args.terms)
            look = answer["verdict"] != "unique"
        else:
            data, edges, nodes = _load(args.graph)
            if args.command == "check":
                answer = check(edges, nodes)
                look = bool(answer)
            elif any(finding["kind"] == "shape" for finding in check(edges)):
                raise ValueError("the graph has malformed edges; run check")
            elif args.command == "plan":
                answer = plan(data)
                look = bool(answer["blocked"] or answer["cycle"])
            elif args.command == "turtle":
                answer = turtle(data)
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
