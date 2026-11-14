"""Adapt the continuous-audit export to the existing OnTautoLogy graph."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from ontautology import build_graph


def convert(source: dict) -> dict:
    audit = source.get('aoi_integration', source)
    if not isinstance(audit, dict) or not isinstance(audit.get('records'), list):
        raise ValueError('expected integration export or observations with aoi_integration.records')
    records = audit['records']
    ids = {r.get('id') for r in records}
    rows, deps, missing, omitted = [], [], [], []
    for record in records:
        key, repo, number = record.get('id'), record.get('repository'), record.get('number')
        if not isinstance(repo, str) or not isinstance(number, int) or key != f'{repo}#{number}':
            raise ValueError(f'invalid PR identity: {key!r}')
        files = record.get('files')
        if files is not None and (not isinstance(files, list) or not all(isinstance(p, str) for p in files)):
            raise ValueError(f'{key}: files must be an array or null')
        head = record.get('head_sha')
        valid_runs = []
        for run in record.get('runs') or []:
            # The underlying model assigns the PR head to each run. Only pass
            # runs whose own SHA confirms that association.
            if head and run.get('head_sha') == head:
                valid_runs.append(run)
            else:
                omitted.append({'pr':key, 'run_id':run.get('id'), 'head_sha':run.get('head_sha'), 'reason':'run SHA missing or differs from PR head'})
        rows.append({'repo':repo, 'n':number, 'pr':{'url':record.get('url'), 'state':record.get('github_state'), 'merged':record.get('merged'), 'head_sha':head, 'base':record.get('base'), 'mergeable':record.get('mergeable'), 'draft':record.get('draft')}, 'files':None if files is None else {'filenames':files}, 'runs':{'workflow_runs':valid_runs}})
        for dep in record.get('dependencies') or []:
            if dep in ids: deps.append({'dependent':key,'prerequisite':dep,'evidence':'recorded in continuous-audit export'})
            else: missing.append({'dependent':key,'prerequisite':dep})
    graph=build_graph({'timestamp':audit.get('captured_at'), 'result':rows, 'dependencies':deps})
    by_id={r['id']:r for r in records}
    for node in graph['nodes']:
        if node['type']=='PullRequest':
            record=by_id[node['id'].removeprefix('pr:')]
            node.update(main_sha=record.get('main_sha'), observed_at=record.get('observed_at'), audit_state=record.get('state'))
    graph['coverage'].update(unobserved_dependencies=missing, omitted_runs=omitted, source='continuous-audit export', integration_batches_scope='all observed PRs, including merged; recorded dependencies only')
    return graph


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot',type=Path)
    parser.add_argument('-o','--output',type=Path)
    args=parser.parse_args(argv)
    try:
        graph=convert(json.loads(args.snapshot.read_text(encoding='utf-8')))
        rendered=json.dumps(graph,ensure_ascii=False,indent=2)+'\n'
        if args.output: args.output.write_text(rendered,encoding='utf-8')
        else: sys.stdout.write(rendered)
        return 2 if graph['dependency_cycle'] else 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(f'audit_adapter: {exc}',file=sys.stderr)
        return 1

if __name__=='__main__': raise SystemExit(main())
