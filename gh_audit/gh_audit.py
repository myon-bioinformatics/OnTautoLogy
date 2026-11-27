"""第一弾 (phase 1) — GitHub audit dashboard: PR audit snapshots of many repositories → one graph with history.

Python 3.11+, standard library only. Phase 1 lives in this folder alone; phase 2 (concept definitions) is the
core and tools/tautology.py, and neither reads this file.

The use of the core for the parent's continuous audit pages (integration-audit/3) and the Flutter absorption
ledger. Everything GitHub-shaped lives here — repositories, PRs, commits, runs, jobs, tasks, transfers — so the
core (ontautology.py) and the generic tools stay free of it. Never fetches or mutates GitHub.

CLI: python -S gh_audit/gh_audit.py audit | plan | turtle | diff | transfers ...; the core commands (check, reach,
why, cycles, order, ladder, keys) read an audit graph here too, through the core's own command line.

Dependency goes one way: this file imports the core and ontautology_shared.ontology; nothing generic imports it.
Audit enhancements go into this folder (gh_audit/), not into the core or tools/.
Every function is callable by name from Python, and from Node through vendor/py_launch.cjs (--call).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ontautology as ot  # noqa: E402
from ontautology import digest, timestamp  # noqa: E402,F401  (the watch layer is shared with phase 2)
from ontautology_shared import ontology  # noqa: E402

__all__ = ["KG_SCHEMA", "RELATIONS", "STATES", "audit", "audit_entities", "audit_runs", "digest", "edges_of", "enrich", "inventory_entries", "observation_diff", "plan", "pr_id", "repository", "timestamp", "transfer_entities", "transfer_report", "turtle", "validate", "main"]


KG_SCHEMA = "ontautology/1"
NAMESPACE = "https://github.com/myon-bioinformatics/OnTautoLogy#"
STATES = ("調査中", "着手中", "完了", "保留", "ブロッカー")
# Relation: (domain, range). Observation links retain temporal head/base facts.
RELATIONS = {
    "hasIssue": (("Observation",), "Issue"),
    "hasReview": (("Observation",), "Review"),
    "hasJob": (("ActionsRun",), "Job"),
    "hasPin": (("Observation",), "FixedSHA"),
    "pinsCommit": (("FixedSHA",), "Commit"),
    "hasGeneratedArtifact": (("Observation",), "GeneratedArtifact"),
    "generatedFrom": (("GeneratedArtifact",), "Commit"),
    "hasEvidence": (("Observation",), "Evidence"),
    "missingEvidence": (("Observation",), "EvidenceGap"),
    "missingFromMain": (("Observation",), "MainGap"),
    "hasTask": (("Observation",), "Task"),
    "precedes": (("Task",), "Task"),
    "hasCompletion": (("Observation",), "CompletionRecord"),
    "verifiesCommit": (("CompletionRecord", "Task"), "Commit"),
    "belongsTo": (("PullRequest", "Commit", "Branch", "File", "ActionsRun"), "Repository"),
    "observes": (("Observation",), "PullRequest"),
    "hasHead": (("Observation",), "Commit"),
    "hasBase": (("Observation",), "Commit"),
    "hasMain": (("Observation",), "Commit"),
    "targetsBranch": (("Observation",), "Branch"),
    "changesFile": (("Observation",), "File"),
    "hasRun": (("Observation",), "ActionsRun"),
    "runsAt": (("ActionsRun",), "Commit"),
    "dependsOn": (("PullRequest",), "PullRequest"),
    "overlapsWith": (("PullRequest",), "PullRequest"),
}

# Public audit vocabulary; legacy relation names retain their meaning.
RELATIONS.update({
    "depends_on": (("PullRequest",), "PullRequest"),
    "duplicates": (("PullRequest",), "PullRequest"),
    "updates": (("Observation",), "File"),
    "verified_by": (("PullRequest",), "Evidence"),
    "derived_from": (("Observation",), "Snapshot"),
    "targets": (("Observation",), "PullRequest"),
    "blocks": (("PullRequest",), "PullRequest"),
    "integrates_into": (("PullRequest",), "Branch"),
    "same_as": (("Repository",), "Repository"),
    "supersedes": (("Snapshot",), "Snapshot"),
    "has_status": (("PullRequest", "Repository", "Task"), "Observation"),
    "migration_source": (("Task",), "File"),
    "migration_target": (("Task",), "Repository"),
})
RELATIONS['belongsTo'] = ((*RELATIONS['belongsTo'][0], "Issue"), "Repository")


def inventory_entries(entries):
    """Validate explicit repository coverage; incomplete is never an empty result."""
    if not isinstance(entries, list):
        raise ValueError("open_pr_inventory must be an array")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("inventory entry must be an object")
        repo = repository(entry.get("repository"))
        timestamp(entry.get("checked_at"))
        if repo in seen:
            raise ValueError("duplicate repository inventory")
        seen.add(repo)
        numbers = entry.get("open_pr_numbers")
        if type(entry.get("complete")) is not bool:
            raise ValueError("inventory complete must be boolean")
        if entry["complete"]:
            if not isinstance(numbers, list) or any(type(n) is not int or n < 1 for n in numbers):
                raise ValueError("complete inventory requires positive PR numbers")
            if len(numbers) != len(set(numbers)):
                raise ValueError("duplicate inventory PR number")
        elif numbers is not None:
            raise ValueError("incomplete inventory requires null open_pr_numbers")
    return entries


def transfer_report(document):
    """Offline absorption ledger. A recorded receipt is not independent CI verification."""
    from urllib.parse import urlparse
    doc = document.get('aoi_integration', document)
    if doc.get('schema') != 'integration-audit/3':
        raise ValueError('expected integration-audit/3 transfer ledger')
    timestamp(doc['captured_at'])
    rows, seen = [], set()
    def sha(value):
        return isinstance(value, str) and len(value) == 40 and all(c in '0123456789abcdef' for c in value)
    def paths(values):
        if not isinstance(values, list) or any(not isinstance(v, str) or not v or v.startswith('/') or '\\' in v or '..' in v.split('/') for v in values):
            raise ValueError('transfer paths must be repository-relative')
        return values
    for item in doc.get('transfers', []):
        key = item['id']
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError('transfer IDs must be nonempty and unique')
        seen.add(key)
        state = item.get('state', '調査中')
        if state not in STATES:
            raise ValueError('invalid transfer state')
        source, target = item['source'], item.get('target') or {}
        repository(source['repository'])
        if not sha(source.get('sha')):
            raise ValueError('transfer source requires a full SHA')
        source_paths = paths(source.get('paths', []))
        kind = item.get('kind', 'feature')
        if kind not in ('feature', 'request') or (kind == 'feature' and not source_paths):
            raise ValueError('existing features require source paths; requests may have none')
        if target.get('repository'):
            repository(target['repository'])
        target_paths = paths(target.get('paths', []))
        if target.get('sha') is not None and not sha(target['sha']):
            raise ValueError('transfer target SHA must be full or unknown')
        criteria = item.get('acceptance', [])
        if not criteria or any(not isinstance(c, dict) or not c.get('id') or not c.get('description') for c in criteria):
            raise ValueError('transfer acceptance criteria are required')
        ids = [c['id'] for c in criteria]
        if any(not isinstance(k, str) for k in ids) or len(ids) != len(set(ids)):
            raise ValueError('transfer acceptance IDs must be unique strings')
        receipt = item.get('verification') or {}
        accepted = receipt.get('accepted', [])
        if not isinstance(accepted, list) or any(not isinstance(k, str) for k in accepted) or set(accepted) - set(ids):
            raise ValueError('receipt contains unknown acceptance criteria')
        url = urlparse(receipt.get('evidence_url', ''))
        verified = bool(target.get('repository') and target_paths and sha(target.get('sha'))
                        and receipt.get('source_sha') == source['sha']
                        and receipt.get('target_sha') == target['sha']
                        and receipt.get('target_in_main') is True
                        and set(accepted) == set(ids) and url.scheme == 'https' and url.netloc == 'github.com'
                        and url.path.startswith('/' + target['repository'] + '/actions/runs/')
                        and url.path.removeprefix('/' + target['repository'] + '/actions/runs/').split('/')[0].isdigit())
        if state == '完了' and not verified:
            raise ValueError('absorbed transfer requires exact source/target SHAs, target paths, main receipt and all acceptance evidence')
        rows.append(dict(item, state=state, kind=kind, receipt_complete=verified,
                         source=dict(source, paths=source_paths), target=dict(target, paths=target_paths)))
    pending = [r['id'] for r in rows if r['state'] != '完了']
    features = [r['id'] for r in rows if r['kind'] == 'feature' and r['state'] != '完了']
    scope = doc.get('transfer_scope', {})
    return {'schema': 'ontautology/transfers/1', 'captured_at': doc['captured_at'], 'records': rows,
            'pending': pending, 'unabsorbed_features': features,
            'counts': {state: sum(r['state'] == state for r in rows) for state in sorted(STATES)},
            'inventory_complete': scope.get('inventory_complete') is True,
            'archive_readiness': '未確定' if scope.get('inventory_complete') is not True else '未吸収あり' if features else '記録上の未吸収なし',
            'note': '記録された受入証跡の整合性。GitHubのCI成功・main包含・機能同等性は独立再検証しない。アーカイブ操作は行わない。'}


def transfer_entities(graph, doc, sid):
    for item in transfer_report(doc)['records']:
        source, target = item['source'], item['target']
        key = 'transfer:' + source['repository'] + ':' + item['id']
        obs = graph.node('transfer-observation:' + digest(doc) + ':' + key, 'Observation',
                         transfer_key=key, observed_at=doc['captured_at'], snapshot=digest(doc),
                         state=item['state'], source='https://github.com/' + source['repository'])
        task = graph.node('task:' + digest(doc) + ':' + key, 'Task', key=key, title=item['title'],
                          phase='再検証', state=item['state'], detail=json.dumps(item, ensure_ascii=False, sort_keys=True))
        graph.edge(obs, 'hasTask', task)
        graph.edge(task, 'has_status', obs)
        graph.edge(obs, 'derived_from', sid)
        graph.edge(obs, 'hasHead', graph.commit(source['repository'], source['sha']))
        for path in source['paths']:
            node = graph.node('file:' + source['repository'] + ':' + path, 'File', path=path)
            graph.edge(node, 'belongsTo', graph.repo(source['repository']))
            graph.edge(task, 'migration_source', node, observation=obs, source_sha=source['sha'])
        if target.get('repository'):
            graph.edge(task, 'migration_target', graph.repo(target['repository']), observation=obs,
                       basis=target.get('basis', 'hypothesis: destination not yet verified'))
            for path in target['paths']:
                node = graph.node('file:' + target['repository'] + ':' + path, 'File', path=path)
                graph.edge(node, 'belongsTo', graph.repo(target['repository']))
                graph.edge(obs, 'updates', node)
        gaps = []
        if not target.get('repository'):
            gaps.append({'reason':'移管先未確定'})
        if not target['paths']:
            gaps.append({'reason':'移管先ファイル未確定'})
        if not item['receipt_complete']:
            gaps.append({'reason':'全受入条件に対応するmainの検証証跡が未確定'})
        audit_entities(graph, {'gaps':gaps, 'evidence':[item['verification']] if item.get('verification') else []},
                       obs, source['repository'], doc['captured_at'])
        if item['state'] == '完了':
            graph.edge(task, 'verifiesCommit', graph.commit(target['repository'], target['sha']),
                       observation=obs, evidence_url=item['verification']['evidence_url'])


def enrich(value, documents, owner):
    """Project observed inventory and aliases without guessing identity or run SHAs."""
    graph = Graph()
    graph.nodes = {n['id']: n for n in value['nodes']}
    graph.edges = {digest(e): e for e in value['edges']}
    # Create actual snapshots before predecessor stubs, independent of input order.
    for doc in documents:
        properties = {"captured_at": doc["captured_at"], "digest": digest(doc)}
        if "open_pr_inventory" in doc:
            properties["open_pr_inventory"] = inventory_entries(doc["open_pr_inventory"])
        graph.node("snapshot:" + digest(doc), "Snapshot", **properties)
        for entry in properties.get("open_pr_inventory", []):
            graph.repo(entry["repository"])
            for number in entry["open_pr_numbers"] or []:
                graph.pr(pr_id(f"{entry['repository']}#{number}", owner))
    for doc in documents:
        sid = 'snapshot:' + digest(doc)
        previous = doc.get('previous_snapshot')
        if previous:
            old = 'snapshot:' + previous['digest']
            if old not in graph.nodes:
                graph.node(old, 'Snapshot', captured_at=previous['captured_at'])
            graph.edge(sid, 'supersedes', old, basis='observed: snapshot sequence')
        for inv in doc.get('inventory', []):
            name = inv['repo'] if '/' in inv['repo'] else owner + '/' + inv['repo']
            name = repository(name)
            state = inv.get('state', '調査中')
            if state not in STATES:
                raise ValueError('invalid inventory state')
            obs = graph.node('repository-observation:' + digest(doc) + ':' + name, 'Observation',
                             observed_at=doc['captured_at'], snapshot=digest(doc), state=state,
                             source=inv.get('source_url'))
            graph.edge(graph.repo(name), 'has_status', obs)
            graph.edge(obs, 'derived_from', sid)
            if inv.get('main'):
                graph.edge(obs, 'hasMain', graph.commit(name, inv['main']))
            runs = inv.get('main_runs', [])
            audit_runs(graph, runs, obs, name, doc['captured_at'], 'main')
            row = {'issues': inv.get('issues', []),
                   'evidence': inv.get('evidence', []),
                   'pins': [dict(repository=p.get('repository', name), sha=p['commit'],
                                 destination=p.get('destination'))
                            for p in inv.get('pin_records', []) if p.get('commit')],
                   'artifacts': [dict(a, source_sha=(a.get('workflow_run') or {}).get('head_sha'))
                                 for w in runs for a in w.get('artifacts', [])],
                   'gaps': [g if isinstance(g, dict) else {'reason': g} for g in inv.get('gaps', [])]}
            audit_entities(graph, row, obs, name, doc['captured_at'])
        transfer_entities(graph, doc, 'snapshot:' + digest(doc))
    observations = {e['source']: e['target'] for e in graph.edges.values() if e['relation'] == 'observes'}
    aliases = {'dependsOn': 'depends_on', 'overlapsWith': 'duplicates', 'changesFile': 'updates', 'observes': 'targets'}
    for e in list(graph.edges.values()):
        relation = e['relation']
        props = {k:v for k,v in e.items() if k not in ('source','relation','target')}
        if relation in aliases:
            if relation == 'overlapsWith':
                props.update(basis='hypothesis', interpretation='shared changed path; duplicate-change candidate only')
            graph.edge(e['source'], aliases[relation], e['target'], **props)
        if relation == 'dependsOn':
            graph.edge(e['target'], 'blocks', e['source'], **props)
        if relation == 'observes':
            graph.edge(e['target'], 'has_status', e['source'])
            graph.edge(e['source'], 'derived_from', 'snapshot:' + graph.nodes[e['source']]['snapshot'])
        if relation == 'targetsBranch':
            graph.edge(observations[e['source']], 'integrates_into', e['target'], **props)
        if relation == 'hasEvidence' and e['source'] in observations:
            graph.edge(observations[e['source']], 'verified_by', e['target'], **props)
    return validate(graph.export())


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
        return {"schema": KG_SCHEMA, "ontology": {"namespace": NAMESPACE, "classes": ontology.classes(RELATIONS),
                "relations": {k: {"domain": list(v[0]), "range": v[1]} for k, v in RELATIONS.items()}},
                "nodes": sorted(self.nodes.values(), key=lambda x: x["id"]),
                "edges": sorted(self.edges.values(), key=lambda x: (x["source"], x["relation"], x["target"], digest(x)))}



def audit_runs(graph, runs, observation, repo, observed, scope):
    for run in runs:
        run_id, attempt = run.get("id"), run.get("run_attempt")
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
            raise ValueError("workflow run id must be a positive integer")
        if attempt is not None and (not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1):
            raise ValueError("run_attempt must be a positive integer or null")
        rid = f"run:{repo}:{run_id}:attempt:{attempt if attempt is not None else 'unknown'}"
        # Run outcomes are observations, not timeless properties of the run.
        graph.node(rid, "ActionsRun", run_id=run_id, attempt=attempt, name=run.get("name"),
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
        ident = entity("GeneratedArtifact", value)
        graph.edge(observation, "hasGeneratedArtifact", ident, **evidence)
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


def _keep_latest(latest, key, obs):
    """Keep the newest observation per key; True when a different one carries the very same time (ambiguous)."""
    current = latest.get(key)
    if current is None or timestamp(obs["observed_at"]) > timestamp(current["observed_at"]):
        latest[key] = obs
        return False
    return timestamp(obs["observed_at"]) == timestamp(current["observed_at"]) and obs["id"] != current["id"]


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
                key, obs = edge["target"], nodes[edge["source"]]
            elif edge["relation"] == "has_status" and nodes[edge["source"]]["type"] == "Repository":
                key, obs = edge["source"], nodes[edge["target"]]
            elif edge['relation'] == 'has_status' and nodes[edge['source']]['type'] == 'Task' and nodes[edge['target']].get('transfer_key'):
                obs = nodes[edge['target']]
                key = obs['transfer_key']
            else:
                continue
            _keep_latest(latest, key, obs)
        result = {}
        for pr, obs in latest.items():
            values = {k:v for k,v in obs.items() if k not in ("id", "snapshot", "observed_at", "source")}
            def claim(edge):
                target = nodes[edge["target"]]
                return {"relation": edge["relation"], "target": {k:v for k,v in target.items() if k != "id"},
                        "facts": {k:v for k,v in edge.items() if k not in ("source", "target", "observation", "observed_at", "snapshot")}}
            relevant = [edge for edge in graph["edges"] if (edge["source"] == obs["id"] or edge.get("observation") == obs["id"])
                        and edge["relation"] != "derived_from"]
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
    documents = [doc.get("aoi_integration", doc) for doc in documents]
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
                                     files_observed=isinstance(files, list), github_state=row.get("github_state"), **facts)
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
                audit_runs(graph, runs, observation, repo, observed, scope)
            audit_entities(graph, row, observation, repo, observed)
        for file, prs in overlap.items():
            prs = sorted(set(prs))
            for i, left in enumerate(prs):
                for right in prs[i + 1:]:
                    graph.edge(left, "overlapsWith", right, file=file, snapshot=snapshot,
                               observed_at=observed, basis="derived: same repository and changed path; not a conflict")
    result = graph.export()
    validate(result)
    return enrich(result, documents, owner)


def validate(graph):
    """An audit graph against its vocabulary (tools/ontology.violations lists every place it is left; the first is
    raised) and the audit's own rules: work states, timestamps, the open-PR inventory, observed dependency claims."""
    if graph.get("schema") != KG_SCHEMA:
        raise ValueError("unsupported graph schema")
    found = ontology.violations(graph, RELATIONS)
    if found:
        raise ValueError(f"{found[0]['kind']}: {found[0]['detail']}")
    nodes = {n["id"]: n for n in graph["nodes"]}
    for node in nodes.values():
        if node["type"] in ("Task", "CompletionRecord") and node.get("state") not in STATES:
            raise ValueError("invalid task/completion state")
        if node["type"] == "Snapshot":
            timestamp(node["captured_at"])
            if "open_pr_inventory" in node:
                inventory_entries(node["open_pr_inventory"])
        if node["type"] == "Observation":
            timestamp(node["observed_at"])
            if node.get("state") not in STATES:
                raise ValueError("invalid observation state")
    for edge in graph["edges"]:
        if edge["relation"] == "dependsOn" and nodes.get(edge.get("observation"), {}).get("type") != "Observation":
            raise ValueError("dependency claim needs an observation")
    return graph


def plan(graph):
    """Dependency order only. Never equates CI success with merge permission."""
    validate(graph)
    nodes = {n["id"]: n for n in graph["nodes"]}
    latest, by_snapshot = {}, {}
    for edge in graph["edges"]:
        if edge["relation"] == "observes":
            obs = nodes[edge["source"]]
            target = edge["target"]
            by_snapshot[(target, obs.get("snapshot"))] = obs
            if _keep_latest(latest, target, obs):
                raise ValueError("ambiguous observations at the same time; select a snapshot")
    pending = {key for key, obs in latest.items() if obs.get("contained_in_main") is not True and obs.get("merged") is not True and obs.get("github_state") != "closed"}
    inventories = {}
    explicit = False
    for node in nodes.values():
        if node["type"] != "Snapshot" or "open_pr_inventory" not in node:
            continue
        explicit = True
        for entry in node["open_pr_inventory"]:
            repo = entry["repository"]
            candidate = {**entry, "snapshot": node["digest"]}
            previous = inventories.get(repo)
            if previous is None or timestamp(entry["checked_at"]) > timestamp(previous["checked_at"]):
                inventories[repo] = candidate
            elif timestamp(entry["checked_at"]) == timestamp(previous["checked_at"]) and candidate != previous:
                raise ValueError("ambiguous inventory at the same time; select a snapshot")
    uncertain, missing_rows = {}, set()
    for repo, entry in inventories.items():
        prefix = "pr:" + repo + "#"
        pending = {key for key in pending if not key.startswith(prefix)}
        if not entry["complete"]:
            uncertain[repo] = entry
            continue
        for number in entry["open_pr_numbers"]:
            key = prefix + str(number)
            # Membership and evidence must come from the same source snapshot.
            observation = by_snapshot.get((key, entry["snapshot"]))
            if observation is None:
                missing_rows.add(key)
            else:
                latest[key] = observation
            if observation is None or (observation.get("contained_in_main") is not True
                                       and observation.get("merged") is not True
                                       and observation.get("github_state") != "closed"):
                pending.add(key)
    dependencies = {key: set() for key in pending}
    missing = {key: set() for key in pending}
    for edge in graph["edges"]:
        source, target = edge["source"], edge["target"]
        if edge["relation"] != "dependsOn" or source not in pending:
            continue
        if source in missing_rows or edge["observation"] != latest[source]["id"]:
            continue
        if target not in latest or (latest[target].get("github_state") == "closed" and latest[target].get("merged") is not True and latest[target].get("contained_in_main") is not True):
            missing[source].add(target)
        elif target in pending:
            dependencies[source].add(target)
        elif target.removeprefix("pr:").rsplit("#", 1)[0] in inventories and latest[target].get("contained_in_main") is not True:
            missing[source].add(target)
    # Core ot.order(): prerequisite first; a cycle blocks itself and what waits on it, nothing else.
    found = ot.order([{"kind": "dependsOn", "source": need, "target": key} for key, needs in dependencies.items() for need in sorted(needs)],
                  nodes=sorted(pending))
    cycle = found["cycle"] or []
    waiting = [{"kind": "dependsOn", "source": need, "target": key} for key, needs in dependencies.items() for need in needs]
    unmet = sorted({key for key, deps in missing.items() if deps} | missing_rows)
    blocked = set(found["blocked"]) | set(unmet) | {row["node"] for row in ot.reach(waiting, unmet)["rows"]}
    order_ = [key for batch in found["batches"] for key in batch]
    result = {"order": [key for key in order_ if key not in blocked], "batches": [[key for key in batch if key not in blocked] for batch in found["batches"] if any(key not in blocked for key in batch)], "blocked": sorted(blocked),
            "missing": {k: sorted(v) for k, v in missing.items() if v}, "cycle": cycle,
            "note": "依存関係だけの順序。CI・レビュー・競合・保留の確認は別途必要。未観測の依存先は完了扱いにしない。"}

    if explicit:
        result.update(inventory_uncertainty=uncertain, missing_rows=sorted(missing_rows))
    return result


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
        flip = edge["relation"] in ("dependsOn", "depends_on", "changesFile", "updates")
        note = edge.get("basis")
        edges.append({**{k: v for k, v in edge.items() if k not in ("relation", "basis")}, "kind": edge["relation"],
                      "source": edge["target"] if flip else edge["source"], "target": edge["source"] if flip else edge["target"],
                      "basis": note if note in ot.BASIS else "derived" if str(note or "").startswith("derived") else "observed",
                      **({"note": note} if note else {}), **({"lock": edge["observation"]} if edge.get("observation") else {})})
        if edge["relation"] == "overlapsWith":
            edges.append({**edges[-1], "source": edge["target"], "target": edge["source"]})
    return edges


def turtle(graph):
    validate(graph)
    uri = lambda ident: "<urn:ontautology:" + quote(ident, safe="") + ">"
    def literal(value):
        # Collections are JSON text literals, not invalid Turtle array/object syntax.
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return json.dumps(value, ensure_ascii=False)
    lines = [f"@prefix ot: <{NAMESPACE}> .", "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
             "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .", ""]
    for kind in ontology.classes(RELATIONS):
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


# ---------------------------------------------------------------- command line

def _load(data):
    """An audit graph as (data, core edges, node ids) for the core commands; None for any other file."""
    if data.get("schema") == KG_SCHEMA:
        validate(data)
        return data, edges_of(data), [node["id"] for node in data["nodes"]]
    return None


def _graph(parser):
    parser.add_argument("graph", type=Path)


def _inputs(parser):
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--owner", default="myon-bioinformatics", help="owner for repository names given without one")
    parser.add_argument("--format", choices=("json", "turtle"), default="json")


def _pair(parser):
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)


def _audit(args):
    graph = audit([ot._read_json(path) for path in args.inputs], owner=args.owner)
    return (turtle(graph) if args.format == "turtle" else graph), False


def _plan(args):
    found = plan(ot._read_json(args.graph))
    return found, bool(found["blocked"] or found["cycle"] or found.get("inventory_uncertainty"))


def _transfers(args):
    found = transfer_report(ot._read_json(args.graph))
    return found, bool(found["pending"]) or not found["inventory_complete"]


def _diff(args):
    found = observation_diff(ot._read_json(args.before), ot._read_json(args.after))
    return found, bool(found["added"] or found["removed"] or found["changed"])


def main(argv=None):
    """Exit codes as the core: 0 answered, 1 input error, 2 answered and something needs a look."""
    return ot.main(argv, load=_load, commands=(
        ("audit", "🔭 第一弾 · integration-audit/3 snapshots (one or more, kept as history) → graph", _inputs, _audit),
        ("plan", "🔭 第一弾 · 🪜 audit graph → dependency order of PRs not yet in main", _graph, _plan),
        ("turtle", "🔭 第一弾 · 🐢 audit graph → RDF/Turtle", _graph, lambda args: (turtle(ot._read_json(args.graph)), False)),
        ("diff", "🔭 第一弾 · 🆚 two audit graphs → what changed between their latest observations", _pair, _diff),
        ("transfers", "🔭 第一弾 · 📦 unabsorbed features, destinations and acceptance receipts", _graph, _transfers)))


if __name__ == "__main__":
    raise SystemExit(main())
