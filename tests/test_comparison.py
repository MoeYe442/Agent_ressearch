from pathlib import Path
from tests.server import running_app
from tests.collaborative_model import CollaborativeModel
from eval.compare import run_comparison, comparison_summary


def test_comparison_reuses_snapshot_model_and_budget(indexed):
    settings=indexed[0].model_copy(update={'test_environment':True})
    tasks=[{'id':'entry','repository':indexed[2].source,'question':'Entry point?'}]
    with running_app(settings,CollaborativeModel()) as url:
        result=run_comparison(url,tasks)
    rows=result['results']
    assert len(rows)==2 and {r['mode'] for r in rows}=={'single','collaborative'}
    for field in ['snapshot_id','manifest_hash','model_identifier','budget_limits']:
        assert rows[0][field]==rows[1][field]
    assert rows[0]['budget_limits']['max_model_calls']==30
    assert all(r['report']['claims'] and r['evidence'] and r['role_usage'] for r in rows)


def test_all_failures_remain_in_both_denominators():
    rows=[{'mode':mode,'status':'failed','usage':None,'quality_pass':None} for mode in ['single','collaborative']]
    summary=comparison_summary(rows)
    assert all(summary[m]['total']==1 and summary[m]['execution_completion_rate']==0 for m in summary)


def test_execution_or_model_review_is_not_quality_score():
    rows=[{'mode':'collaborative','status':'succeeded','usage':None,'quality_pass':None}]
    assert comparison_summary(rows)['collaborative']['quality_completion_rate'] is None


def test_unknown_usage_is_not_zero():
    summary=comparison_summary([{'mode':'single','status':'failed','usage':None}])['single']
    assert summary['input_tokens'] is None and summary['unknown_usage_tasks']==1


def test_synthetic_comparison_cannot_claim_improvement(indexed):
    settings=indexed[0].model_copy(update={'test_environment':True})
    with running_app(settings,CollaborativeModel()) as url:
        result=run_comparison(url,[{'id':'missing','repository':'missing','question':'Missing?'}],root=Path(indexed[2].source))
    assert result['synthetic'] and result['quality_improvement'] is None
    assert len(result['results'])==2 and all(r['quality_pass'] is None for r in result['results'])


def test_wrong_semantics_with_real_citation_still_requires_manual_review():
    from eval.run import structural_check
    checked=structural_check({}, {'claims':[{'text':'Memory storage persists to disk','evidence_ids':['real']}],'limitations':[]}, [{'id':'real','path':'storage.py','excerpt':'self.states = {}'}])
    assert checked['structure_pass'] and checked['quality_pass'] is None
