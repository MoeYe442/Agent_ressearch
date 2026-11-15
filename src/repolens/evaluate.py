"""V4 evaluation CLI. Only the explicit run --execute command contacts the local API."""
import argparse
import json
from pathlib import Path
import re
from uuid import uuid4
from repolens.benchmark.files import Artifacts,read_json,runner_lock,MAX_FILE
from repolens.benchmark.protocol import Suite,CONFIGS,create_plan,matrix


def plain_file(path,value):
    path=Path(path)
    if path.is_symlink():raise ValueError('artifact_path_denied')
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=value.encode('utf-8')
    if len(raw)>MAX_FILE:raise ValueError('artifact_size_limit')
    with path.open('xb') as output:output.write(raw)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    plan=commands.add_parser('plan',help='Freeze a new matrix without network or model calls')
    plan.add_argument('--suite',type=Path,required=True)
    plan.add_argument('--directory',type=Path,required=True)
    plan.add_argument('--api-url',default='http://127.0.0.1:8000')
    plan.add_argument('--configurations',nargs='+',choices=list(CONFIGS),default=['single_keyword','collaborative_keyword'])
    plan.add_argument('--repeats',type=int,choices=[1,2,3],default=3)
    plan.add_argument('--partition',choices=['development','reserved','all'],default='development')
    plan.add_argument('--protocol-id',help='Required operator attestation that settings are frozen before reserved use')
    plan.add_argument('--timeout',type=float,default=960.0)
    plan.add_argument('--case-id',action='append',help='Freeze a small explicit development subset before execution')
    run=commands.add_parser('run',help='Submit remaining slots; may incur real provider charges')
    run.add_argument('--directory',type=Path,required=True)
    run.add_argument('--execute',action='store_true',help='Explicitly authorize API submissions and provider use')
    run.add_argument('--allow-draft',action='store_true',help='Development runs only; draft rubrics never yield published quality rates')
    review=commands.add_parser('review-template',help='Prepare an editable human-review JSON packet from verified raw records')
    review.add_argument('--directory',type=Path,required=True)
    review.add_argument('--output',type=Path,required=True)
    report=commands.add_parser('report',help='Recompute fixed-denominator local reports; never contacts the API')
    report.add_argument('--directory',type=Path,required=True)
    report.add_argument('--reviews',type=Path,action='append',default=[])
    report.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.command=='plan':
            suite=Suite.model_validate(read_json(args.suite));files=Artifacts(args.directory)
            if files.root.exists() and any(files.root.iterdir()):raise ValueError('new_empty_run_directory_required')
            frozen=create_plan(suite,args.api_url,args.configurations,args.repeats,args.partition,args.protocol_id,args.timeout,args.case_id)
            with runner_lock(files):files.write('plan.json',frozen.model_dump(mode='json'),exclusive=True)
            result={'run_id':frozen.run_id,'planned_slots':len(matrix(frozen)),'annotation_status':suite.annotation_status,'executed':False}
        elif args.command=='run':
            if not args.execute:raise ValueError('explicit_execute_flag_required_provider_charges_possible')
            from repolens.benchmark.runner import Runner
            runner=Runner(args.directory,allow_draft=args.allow_draft);runner.run()
            result={'run_id':runner.plan.run_id,'runner_returned':True,'quality':'requires approved rubric and independent human review'}
        elif args.command=='review-template':
            from repolens.benchmark.report import review_packet
            packet=review_packet(args.directory);plain_file(args.output,json.dumps(packet,ensure_ascii=False,indent=2,allow_nan=False))
            result={'review_rows':len(packet['rows']),'network_calls':False}
        else:
            from repolens.benchmark.report import build_report,csv_text,markdown,html_text
            value=build_report(args.directory,args.reviews);output=Path(args.output).resolve()
            if output.exists() and any(output.iterdir()):raise ValueError('new_empty_report_directory_required')
            output.mkdir(parents=True,exist_ok=True)
            plain_file(output/'report.json',json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False))
            plain_file(output/'rows.csv',csv_text(value));plain_file(output/'report.md',markdown(value));plain_file(output/'report.html',html_text(value))
            result={'run_id':value['run_id'],'report_directory':str(output),'network_calls':False}
        print(json.dumps(result,ensure_ascii=False))
    except KeyboardInterrupt:
        print(json.dumps({'error_code':'runner_interrupted_rerun_same_plan_to_observe_existing_task'}));raise SystemExit(130) from None
    except (ValueError,OSError,KeyError,TypeError) as exc:
        message=str(exc)
        code=message if isinstance(exc,ValueError) and re.fullmatch('[a-z0-9_]+',message) else 'invalid_evaluation_input_or_artifact'
        print(json.dumps({'error_code':code}));raise SystemExit(1) from None


if __name__=='__main__':main()
