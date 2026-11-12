from pathlib import Path
from tests.server import running_app
from tests.test_retrieval_http import config
from tests.retrieval_services import RetrievalServices,RetrievalModel
from eval.retrieval import run_retrieval,score_retrieval


def test_three_configurations_share_snapshot_and_keep_manual_quality(indexed):
    settings=config(indexed[0].data_dir.parent).model_copy(update={'test_environment':True});fixtures=RetrievalServices(settings)
    cases=[{'id':'storage','repository':indexed[2].source,'query':'StateStore','expected_evidence':[{'path':'storage.py','start_line':4,'end_line':12}]}]
    with running_app(settings,RetrievalModel(),retrieval_factory=lambda s,db:fixtures.service(db)) as url:
        result=run_retrieval(url,cases)
    assert len(result['results'])==3 and len({r['snapshot_id'] for r in result['results']})==1
    assert all(r['quality_pass'] is None for r in result['results'])
    assert result['synthetic'] and result['quality_improvement'] is None
    assert all(r['status']=='succeeded' and r['usage'] is not None for r in result['results'])


def test_failures_keep_each_configuration_denominator(indexed):
    with running_app(indexed[0],None) as url:result=run_retrieval(url,[{'id':'bad','repository':'missing','query':'x','expected_evidence':[]}],root=Path(indexed[2].source))
    assert len(result['results'])==3
    assert all(s['total']==1 and s['unknown_usage']==1 for s in result['summary'].values())


def test_wrong_excerpt_hash_cannot_count_as_recall():
    case={'expected_evidence':[{'path':'app.py','start_line':1,'end_line':2}]}
    hits=[{'evidence':{'snapshot_id':'s','path':'app.py','start_line':1,'end_line':2,'excerpt':'Invented source','content_hash':'wrong'}}]
    result=score_retrieval(case,hits,'s',5)
    assert result['recall_at_k']==0 and result['invalid_evidence']==1 and result['quality_pass'] is None
