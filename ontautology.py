"""Build a small, evidence-aware graph from a PR audit snapshot (Python 3.11+)."""
from __future__ import annotations

import argparse
import json
import sys
from graphlib import CycleError, TopologicalSorter
from itertools import combinations
from pathlib import Path

SCHEMA = "ontautology/pr-audit-graph/1"


def build_graph(snapshot: dict) -> dict:
    """Transform observations; only explicit dependencies are treated as ordering."""
    # The site exports either the integration object or the full observations.
    audit = snapshot.get("aoi_integration", snapshot)
    unresolved = []
    if "records" in audit:
        items = audit["records"]
        if not isinstance(items, list):
            raise ValueError("records must be a list")
        known = {item["id"] for item in items}
        deps = []
        for item in items:
            for prerequisite in item.get("dependencies", []):
                if prerequisite in known:
                    deps.append({"dependent": item["id"], "prerequisite": prerequisite})
                else:
                    unresolved.append({"dependent": item["id"], "prerequisite": prerequisite})
        snapshot = {
            "timestamp": audit.get("captured_at"),
            "result": [{"repo": item["repository"], "n": item["number"], "pr": item,
                        "files": {"filenames": item["files"]} if isinstance(item.get("files"), list) else None,
                        "runs": {"workflow_runs": item.get("runs", [])}}
                       for item in items],
            "dependencies": deps,
        }
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
                 status=run.get("status"), observed_head_sha=run.get("head_sha"),
                 current_pr_head_sha=pr.get("head_sha"), attempt=run.get("run_attempt"),
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
    if unresolved:
        batches = []  # An incomplete dependency graph cannot justify an order.
    return {"schema": SCHEMA, "observed_at": snapshot.get("timestamp"),
            "coverage": {"file_lists_missing": sorted(k for k, v in paths.items() if v is None),
                         "unresolved_dependencies": unresolved,
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


if __name__ == "__main__":
    raise SystemExit(main())
