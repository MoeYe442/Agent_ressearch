"""Collect one explicitly identified OFFLINE fault-injection run; never grade answers."""
import argparse
import json
from pathlib import Path
from datetime import datetime,timezone

CASES=('response','inflight','terminal','parallel','expired','model','snapshot','cancel')


def collect_report(directory,run_id):
    rows=[]
    for name in CASES:
        try:
            row=json.loads((Path(directory)/(name+'.json')).read_text(encoding='utf-8'))
            if row.get('run_id')!=run_id:raise ValueError('stale')
            row={**row,'case':name,'observed':True,'quality_pass':None,'synthetic':True}
        except (OSError,ValueError,TypeError):
            row={'case':name,'observed':False,'passed':False,'quality_pass':None,'synthetic':True,'error_code':'missing_or_stale_case'}
        rows.append(row)
    interruptions=rows[:4];controls=rows[4:]
    summary={'all_cases':8,'interruption_cases':4,'successful_resumes':sum(row.get('passed') is True for row in interruptions),'negative_controls':4,'correctly_rejected':sum(row.get('passed') is True for row in controls),'missing_or_failed':sum(row.get('passed') is not True for row in rows)}
    summary['recovery_rate']=summary['successful_resumes']/4
    return {'created_at':datetime.now(timezone.utc).isoformat(),'run_id':run_id,'synthetic':True,'exactly_once_claim':False,'quality_note':'Scripted provider counts verify recovery mechanics, not real quality or billing. Unknown in-flight requests retain conservative reservations and may be paid again. Missing/failed cases remain in the denominator.','summary':summary,'results':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--results-dir',type=Path,required=True);parser.add_argument('--run-id',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report=collect_report(args.results_dir,args.run_id);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report['summary']))


if __name__=='__main__':main()
