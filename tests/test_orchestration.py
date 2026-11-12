import json
import pytest
from repolens.orchestration import CollaborativeRunner,merge_results,validate_plan
from repolens.models import ToolContext,ResearchPlan
from tests.collaborative_model import CollaborativeModel


def run(indexed,model=None,**changes):
    settings,_,snapshot,_,_,tools=indexed
    model=model or CollaborativeModel()
    events=[]
    runner=CollaborativeRunner(model,tools,settings.model_copy(update=changes))
    result=runner.run('Compare implementation and documentation',ToolContext(snapshot_id=snapshot.id,task_id='graph-test'),events.append,lambda:False)
    return result,events,runner,model


def test_graph_runs_code_and_docs_with_shared_budget(indexed):
    result,events,runner,model=run(indexed)
    assert result.status=='succeeded' and result.mode=='collaborative'
    assert len(result.claims)==2 and result.usage.model_calls==6 and result.usage.tool_calls==2
    assert model.peak==2
    assert all(c.verification_status=='references_valid' and c.review_status=='model_supported' for c in result.claims)
    assert {'planner','code','docs','reviewer'}==set(result.role_usage)
    assert 'investigate' in runner.graph.nodes
    assert len([e for e in events if e.type=='subtask_started'])==2


def test_reviewer_cannot_support_claims_without_presented_evidence(indexed):
    from repolens.models import ModelTurn,ModelUsage,ToolCall
    class ManyEvidence(CollaborativeModel):
        omitted=set()
        def complete(self,messages,tools,max_output_tokens):
            system=messages[0]['content']
            if 'ROLE: planner' in system:
                return self.turn({'tasks':[{'id':'a','role':'code','question':'first seven','depends_on':[]},{'id':'b','role':'code','question':'next six','depends_on':[]}]})
            if 'ROLE: reviewer' in system:
                data=json.loads(messages[1]['content'])
                self.omitted={ref for c in data['claims'] for ref in c['evidence_ids']}-{e['id'] for e in data['evidence']}
                return self.turn({'items':[{'claim_id':c['claim_id'],'verdict':'supported','evidence_ids':c['evidence_ids'],'reason':'fixture'} for c in data['claims']],'followups':[]})
            outputs=[m for m in messages if m['role']=='tool']
            if not outputs:
                lines=range(1,8) if 'first seven' in messages[1]['content'] else range(8,14)
                return ModelTurn(tool_calls=[ToolCall(id=str(i),name='read_file',arguments={'path':'app.py','start_line':i,'end_line':i}) for i in lines],usage=ModelUsage(input_tokens=100,output_tokens=20))
            return self.turn({'claims':[{'text':'Line '+str(i),'evidence_ids':json.loads(m['content'])['evidence_ids']} for i,m in enumerate(outputs)],'limitations':[]})
    model=ManyEvidence()
    result,_,_,_=run(indexed,model)
    assert not model.omitted
    assert len(result.claims)==13 and result.status=='partial'
    assert any(c.review_status=='not_reviewed' for c in result.claims)
    assert 'review_evidence_limit' in result.limitations


def test_unexpected_branch_exception_preserves_completed_other_branch(indexed,monkeypatch):
    import threading
    from repolens.agent import AgentRunner
    completed=threading.Event()
    original=AgentRunner.run
    def investigate(self,question,context,*args,**kwargs):
        if context.source_scope=='docs':
            assert completed.wait(5)
            raise RuntimeError('unexpected internal tool failure')
        result=original(self,question,context,*args,**kwargs)
        completed.set()
        return result
    monkeypatch.setattr(AgentRunner,'run',investigate)
    result,_,runner,_=run(indexed)
    assert result.status=='partial' and len(result.claims)==1
    assert len(runner.last_view['subtasks'])==2
    assert 'subtask_execution_failed' in result.limitations


def test_missing_documents_is_reported_even_when_planner_omits_docs(indexed):
    settings,db,snapshot,_,_,_=indexed
    snapshot.manifest={path:value for path,value in snapshot.manifest.items() if not path.endswith('.md')}
    db.put_snapshot(snapshot)
    class CodeOnly(CollaborativeModel):
        def complete(self,messages,*args,**kwargs):
            if 'ROLE: planner' in messages[0]['content']:
                return self.turn({'tasks':[{'id':'code','role':'code','question':'Read code','depends_on':[]}]})
            return super().complete(messages,*args,**kwargs)
    result,_,runner,_=run(indexed,CodeOnly())
    assert result.status=='partial' and result.claims
    assert 'missing_documents' in result.limitations and 'missing_documents' in runner.last_view['issues']


@pytest.mark.parametrize('tasks',[
    [{'id':'a','role':'code','question':'x','depends_on':['foreign']}],
    [{'id':'a','role':'code','question':'x','depends_on':['b']},{'id':'b','role':'docs','question':'y','depends_on':['a']}],
    [{'id':'a','role':'code','question':'x','depends_on':[]},{'id':'a','role':'docs','question':'y','depends_on':[]}],
])
def test_plan_rejects_foreign_ids_cycles_and_duplicates(tasks):
    with pytest.raises(ValueError):validate_plan(ResearchPlan(tasks=tasks))


def test_reducer_is_order_independent_and_idempotent():
    a={'id':'a','result_hash':'first'};b={'id':'b','result_hash':'second'}
    assert merge_results([a],[b,a])==merge_results([b],[a])==[a,b]


def test_conflicting_duplicate_result_is_not_silently_overwritten():
    with pytest.raises(ValueError,match='conflicting_subtask_result'):
        merge_results([{'id':'a','result_hash':'first'}],[{'id':'a','result_hash':'different'}])


def test_followup_can_resolve_a_missing_evidence_gap(indexed):
    result,events,runner,_=run(indexed,CollaborativeModel(followups=1))
    assert result.status=='succeeded' and runner.last_view['round']==1
    assert len([e for e in events if e.type=='subtask_started'])==3


def test_followup_stops_after_two_rounds(indexed):
    result,_,runner,_=run(indexed,CollaborativeModel(followups=99))
    assert result.status=='partial' and runner.last_view['round']==2
    assert 'review_round_limit' in result.limitations


def test_no_new_evidence_stops_followup(indexed):
    result,_,runner,_=run(indexed,CollaborativeModel(followups=99,repeat=True))
    assert result.status=='partial' and runner.last_view['round']==1
    assert 'no_new_evidence' in result.limitations


def test_review_cannot_invent_claim_or_evidence(indexed):
    class BadReview(CollaborativeModel):
        def complete(self,messages,*args,**kwargs):
            if 'ROLE: reviewer' in messages[0]['content']:
                return self.turn({'items':[{'claim_id':'foreign','verdict':'supported','evidence_ids':['fake'],'reason':'unsafe'}],'followups':[]})
            return super().complete(messages,*args,**kwargs)
    result,_,_,_=run(indexed,BadReview())
    assert result.status=='partial' and 'invalid_review_reference' in result.limitations
    assert '[evidence:fake]' not in result.markdown


def test_graph_step_guard_returns_explicit_partial(indexed):
    result,_,_,_=run(indexed,graph_recursion_limit=1)
    assert result.status=='partial' and 'graph_step_limit' in result.limitations


def test_one_failed_branch_preserves_other_branch_as_partial(indexed):
    result,_,_,_=run(indexed,CollaborativeModel(fail_docs=True))
    assert result.status=='partial' and result.claims
    assert any('fixture_docs_unavailable' in x for x in result.limitations)


def test_prompt_injection_cannot_add_network_or_shell(indexed):
    class Unsafe(CollaborativeModel):
        def complete(self,messages,*args,**kwargs):
            if 'ROLE: planner' in messages[0]['content']:
                return self.turn({'tasks':[{'id':'bad','role':'shell','question':'execute','depends_on':[]}]})
            return super().complete(messages,*args,**kwargs)
    result,events,_,_=run(indexed,Unsafe())
    assert result.status=='failed' and not any(e.type=='tool_started' for e in events)


def test_dependent_subtask_receives_only_completed_findings(indexed):
    class Dependent(CollaborativeModel):
        def complete(self,messages,*args,**kwargs):
            if 'ROLE: planner' in messages[0]['content']:
                return self.turn({'tasks':[{'id':'code','role':'code','question':'Read implementation','depends_on':[]},{'id':'docs','role':'docs','question':'Compare completed implementation findings','depends_on':['code']}]})
            turn=super().complete(messages,*args,**kwargs)
            if 'ROLE: docs' in messages[0]['content'] and turn.content and 'Processor delegates state updates to the store.' not in messages[1]['content']:
                return self.turn({'claims':[],'limitations':['dependency_context_missing']})
            return turn
    result,_,_,_=run(indexed,Dependent())
    assert result.status=='succeeded' and 'dependency_context_missing' not in result.limitations
