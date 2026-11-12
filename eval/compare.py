"""Paired execution comparison. Semantic quality is always pending manual review."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx
from eval.run import summarize, structural_check, wait_for

MODES = ('single', 'collaborative')


def comparison_summary(rows):
    return {mode: summarize([row for row in rows if row['mode'] == mode]) for mode in MODES}


def run_comparison(base_url, tasks, root=None, synthetic=False, timeout=960):
    root = Path(root or Path.cwd()).resolve()
    rows, snapshots = [], {}
    with httpx.Client(base_url=base_url, timeout=30) as client:
        health = client.get('/health').raise_for_status().json()
        synthetic = synthetic or health.get('test_environment', False)
        for case in tasks:
            snapshot, import_error = None, None
            try:
                source = str((root / case['repository']).resolve())
                if source not in snapshots:
                    imported = client.post('/repositories', json={'path':source}).raise_for_status().json()
                    snapshot = wait_for(client, '/repositories/'+imported['id'], 'status', {'importing'}, timeout)
                    if snapshot['status'] != 'ready':
                        raise ValueError(snapshot.get('error_code') or 'import_failed')
                    snapshots[source] = snapshot
                snapshot = snapshots[source]
            except Exception as exc:
                import_error = str(exc) if isinstance(exc, (ValueError, TimeoutError)) else type(exc).__name__
            pair_config = None
            for mode in MODES:
                started = time.monotonic()
                row = {'id':case['id'], 'question':case['question'], 'mode':mode, 'status':'failed', 'usage':None, 'quality_pass':None, 'synthetic':synthetic, 'has_report':False}
                try:
                    if import_error:
                        raise ValueError(import_error)
                    row.update(snapshot_id=snapshot['id'], manifest_hash=snapshot['manifest_hash'])
                    submitted = client.post('/tasks', json={'snapshot_id':snapshot['id'], 'question':case['question'], 'mode':mode}).raise_for_status().json()
                    row['task_id'] = submitted['id']
                    completed = wait_for(client, '/tasks/'+submitted['id'], 'status', {'queued', 'running'}, timeout)
                    row.update({key:completed.get(key) for key in ['status','usage','error_code','model_identifier','budget_limits','prompt_version']})
                    config = (row['model_identifier'], row['budget_limits'])
                    if pair_config is not None and config != pair_config:
                        raise ValueError('comparison_configuration_changed')
                    pair_config = config
                    response = client.get('/tasks/'+submitted['id']+'/report')
                    if response.status_code == 200:
                        report = response.json()
                        ids = sorted({e for c in report['claims'] for e in c['evidence_ids']})
                        evidence = [client.get('/evidence/'+e).raise_for_status().json() for e in ids]
                        row.update(has_report=True, report=report, evidence=evidence, role_usage=report.get('role_usage',{}), **structural_check(case, report, evidence))
                except Exception as exc:
                    row['status'] = 'failed'
                    row['error_code'] = str(exc) if isinstance(exc, (ValueError, TimeoutError)) else type(exc).__name__
                row['elapsed_ms'] = round((time.monotonic()-started)*1000, 2)
                rows.append(row)
    return {'created_at':datetime.now(timezone.utc).isoformat(), 'synthetic':synthetic, 'quality_improvement':None, 'quality_note':'Execution and model review are not quality scores. Independent manual semantic review is pending. Synthetic runs cannot establish model improvement.', 'summary':comparison_summary(rows), 'results':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--tasks',type=Path,default=Path('eval/collaborative_tasks.jsonl'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--synthetic',action='store_true')
    args=parser.parse_args()
    cases=[json.loads(line) for line in args.tasks.read_text(encoding='utf-8').splitlines() if line.strip()]
    result=run_comparison(args.base_url,cases,synthetic=args.synthetic)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result['summary'],ensure_ascii=False))


if __name__=='__main__':
    main()
