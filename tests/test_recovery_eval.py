import json
from eval.recovery import collect_report,CASES


def test_missing_failed_and_stale_cases_remain_in_recovery_denominator(tmp_path):
    (tmp_path/'response.json').write_text(json.dumps({'run_id':'current','passed':True,'new_provider_calls':2,'quality_pass':True}))
    (tmp_path/'inflight.json').write_text(json.dumps({'run_id':'stale','passed':True}))
    result=collect_report(tmp_path,'current')
    assert result['summary']['interruption_cases']==4 and result['summary']['successful_resumes']==1
    assert result['summary']['all_cases']==8 and result['summary']['missing_or_failed']==7
    assert all(row['quality_pass'] is None for row in result['results'])
    assert result['synthetic'] and not result['exactly_once_claim']
