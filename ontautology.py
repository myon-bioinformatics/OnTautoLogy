"""Build a small, evidence-aware graph from a PR audit snapshot (Python 3.11+)."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from urllib.parse import quote
from graphlib import CycleError, TopologicalSorter
from itertools import combinations
from pathlib import Path

SCHEMA = "ontautology/pr-audit-graph/1"


def build_graph(snapshot: dict) -> dict:
    """Transform observations; only explicit dependencies are treated as ordering."""
    records = snapshot.get("result")
    if not isinstance(records, list):
        raise ValueError("result must be a list")
    nodes, edges, prs, paths = {}, [], {}, {}

    def node(identifier: str, kind: str, **properties: object) -> None:
        nodes[identifier] = {"id": identifier, "type": kind, **properties}

    def edge(source: str, relation: str, target: str, **properties: object) -> None:
        edges.append({"source": source, "relation": relation, "target": target, **properties})

    for item in records:
        repo, number, pr = item["repo"], item["n"], item["pr"]
        key = f"{repo}#{number}"
        if key in prs:
            raise ValueError(f"duplicate PR: {key}")
        prs[key] = item
        rid, pid = f"repository:{repo}", f"pr:{key}"
        node(rid, "Repository", name=repo)
        node(pid, "PullRequest", number=number, url=pr.get("url"), state=pr.get("state"),
             merged=pr.get("merged"), head_sha=pr.get("head_sha"), base=pr.get("base"),
             mergeable=pr.get("mergeable"), draft=pr.get("draft"))
        edge(pid, "belongs_to", rid)
        file_result = item.get("files")
        if not isinstance(file_result, dict) or not isinstance(file_result.get("filenames"), list):
            paths[key] = None
        else:
            paths[key] = set(file_result["filenames"])
            for path in sorted(paths[key]):
                fid = f"file:{repo}:{path}"
                node(fid, "File", repository=repo, path=path)
                edge(pid, "changes", fid)
        run_result = item.get("runs") or {}
        for run in run_result.get("workflow_runs", []):
            wid = f"workflow_run:{repo}:{run['id']}"
            node(wid, "WorkflowRun", name=run.get("name"), conclusion=run.get("conclusion"),
                 status=run.get("status"), observed_head_sha=pr.get("head_sha"),
                 url=f"https://github.com/myon-bioinformatics/{repo}/actions/runs/{run['id']}")
            edge(pid, "has_run", wid)

    for a, b in combinations(sorted(prs), 2):
        if prs[a]["repo"] != prs[b]["repo"] or paths[a] is None or paths[b] is None:
            continue
        shared = sorted(paths[a] & paths[b])
        if shared:
            edge(f"pr:{a}", "shares_changed_paths_with", f"pr:{b}", paths=shared,
                 interpretation="shared paths only; not proof of conflict")

    dependencies = snapshot.get("dependencies", [])
    order = {key: set() for key in prs}
    for dep in dependencies:
        dependent, prerequisite = dep["dependent"], dep["prerequisite"]
        if dependent not in prs or prerequisite not in prs:
            raise ValueError(f"dependency refers to unknown PR: {dependent}, {prerequisite}")
        order[dependent].add(prerequisite)
        edge(f"pr:{dependent}", "depends_on", f"pr:{prerequisite}",
             evidence=dep.get("evidence"), assertion="explicit")
    try:
        batches = []
        sorter = TopologicalSorter(order)
        sorter.prepare()
        while sorter.is_active():
            ready = sorted(sorter.get_ready())
            batches.append(ready)
            sorter.done(*ready)
        cycle = None
    except CycleError as exc:
        batches, cycle = [], list(exc.args[1])
    return {"schema": SCHEMA, "observed_at": snapshot.get("timestamp"),
            "coverage": {"file_lists_missing": sorted(k for k, v in paths.items() if v is None),
                         "dependency_source": "explicit input only", "workflow_scope": "input snapshot only"},
            "nodes": list(nodes.values()), "edges": edges, "integration_batches": batches,
            "dependency_cycle": cycle}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="PR audit snapshot JSON")
    parser.add_argument("-o", "--output", type=Path, help="output JSON (default: stdout)")
    args = parser.parse_args(argv)
    try:
        graph = build_graph(json.loads(args.snapshot.read_text(encoding="utf-8")))
        rendered = json.dumps(graph, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 2 if graph["dependency_cycle"] else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ontautology: {exc}", file=sys.stderr)
        return 1



# Temporal ontology extension. The original build_graph/main API above is retained.
KG_SCHEMA = "ontautology/1"
NAMESPACE = "https://github.com/myon-bioinformatics/OnTautoLogy#"
STATES = ("調査中", "着手中", "完了", "保留", "ブロッカー")
CLASSES = ("Repository", "PullRequest", "Commit", "Branch", "File", "WorkflowRun", "Observation")
# Relation: (domain, range). Observation links retain temporal head/base facts.
RELATIONS = {
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

    def node(self, ident, kind, **properties):
        node = {"id": ident, "type": kind, **properties}
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
        return {"schema": KG_SCHEMA, "ontology": {"namespace": NAMESPACE, "classes": list(CLASSES),
                "relations": {k: {"domain": list(v[0]), "range": v[1]} for k, v in RELATIONS.items()}},
                "nodes": sorted(self.nodes.values(), key=lambda x: x["id"]),
                "edges": sorted(self.edges.values(), key=lambda x: (x["source"], x["relation"], x["target"], digest(x)))}


def build(documents, *, owner="myon-bioinformatics"):
    """Import integration-audit/3 snapshots; never fetch or mutate GitHub."""
    graph = Graph()
    for doc in documents:
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
                               status=run.get("status"), observed_at=observed)
                    if run.get("head_sha"):
                        graph.edge(rid, "runsAt", graph.commit(repo, run["head_sha"]))
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
    if len(nodes) != len(graph["nodes"]):
        raise ValueError("duplicate node ID")
    for node in nodes.values():
        if node["type"] not in CLASSES:
            raise ValueError("unknown ontology class")
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
    sorter = TopologicalSorter(dependencies)
    cycle = []
    try:
        sorter.prepare()
    except CycleError as error:
        cycle = list(error.args[1])
    order = []
    while sorter.is_active():
        ready = sorted(sorter.get_ready())
        if not ready:
            break
        order.extend(ready)
        sorter.done(*ready)
    blocked = {key for key, deps in missing.items() if deps} | (pending - set(order))
    while True:
        after = blocked | {key for key, deps in dependencies.items() if deps & blocked}
        if after == blocked:
            break
        blocked = after
    return {"order": [key for key in order if key not in blocked], "blocked": sorted(blocked),
            "missing": {k: sorted(v) for k, v in missing.items() if v}, "cycle": cycle,
            "note": "依存関係だけの順序。CI・レビュー・競合・保留の確認は別途必要。未観測の依存先は完了扱いにしない。"}


def turtle(graph):
    validate(graph)
    uri = lambda ident: "<urn:ontautology:" + quote(ident, safe="") + ">"
    literal = lambda value: json.dumps(value, ensure_ascii=False)
    lines = [f"@prefix ot: <{NAMESPACE}> .", "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
             "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .", ""]
    for kind in CLASSES:
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


def ontology_main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build_cmd = commands.add_parser("build", help="import one or more integration-audit/3 snapshots")
    build_cmd.add_argument("inputs", nargs="+", type=Path)
    build_cmd.add_argument("--owner", default="myon-bioinformatics")
    build_cmd.add_argument("--format", choices=("json", "turtle"), default="json")
    build_cmd.add_argument("-o", "--output", type=Path)
    for name in ("check", "plan", "turtle"):
        command = commands.add_parser(name)
        command.add_argument("input", type=Path)
        command.add_argument("-o", "--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build([json.loads(p.read_text()) for p in args.inputs], owner=args.owner)
            text = turtle(result) if args.format == "turtle" else json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        else:
            graph = validate(json.loads(args.input.read_text()))
            result = plan(graph) if args.command == "plan" else {"valid": True, "nodes": len(graph["nodes"]), "edges": len(graph["edges"])}
            text = turtle(graph) if args.command == "turtle" else json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"ontautology: {error}\n")



def cli(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("build", "check", "plan", "turtle"):
        return ontology_main(argv)
    if argv and argv[0] in ("-h", "--help"):
        print("Commands: build, check, plan, turtle; or use the original snapshot.json -o graph.json form.")
    return main(argv)


if __name__ == "__main__":
    raise SystemExit(cli())
