from typing import TypedDict
from langgraph.graph import StateGraph,START,END
from langsmith import tracing_context
from repolens.agent import AgentRunner
from repolens.direct import DirectRunner
from repolens.models import AnalysisResult
from repolens.budget import BudgetManager
from repolens.model_gateway import ModelGateway
from repolens.checkpoints import saver_for
from repolens.execution_store import RecoveryRejected


class SingleState(TypedDict):
    result:dict | None


class DurableSingleRunner:
    def __init__(self,model,registry,settings):
        self.model,self.registry,self.settings=model,registry,settings
        self.last_view=None

    def run(self,question,context,emit,cancelled,*,session):
        budget=BudgetManager(self.settings,session=session)
        gateway=ModelGateway(self.model,budget,emit,cancelled,context.task_id)
        def investigate(state):
            runner_type = DirectRunner if context.analysis_mode == "direct" else AgentRunner
            result=runner_type(self.model,self.registry,self.settings).run(question,context,emit,cancelled,budget=budget,gateway=gateway)
            return {'result':result.model_dump(mode='json')}
        builder=StateGraph(SingleState);builder.add_node('investigate',investigate);builder.add_edge(START,'investigate');builder.add_edge('investigate',END)
        config={'configurable':{'thread_id':context.task_id},'max_concurrency':2,'recursion_limit':self.settings.graph_recursion_limit}
        with saver_for(session) as saver,tracing_context(enabled=False):
            graph=builder.compile(checkpointer=saver);prior=graph.get_state(config)
            value=graph.invoke(None if prior.created_at else {'result':None},config,durability='sync')
        result=AnalysisResult.model_validate(value['result'])
        for claim in result.claims:
            if not all(self.registry.evidence.validate_evidence(ref,context.snapshot_id) for ref in claim.evidence_ids):raise RecoveryRejected('recovery_evidence_changed')
        result.usage=budget.snapshot();result.role_usage=budget.roles()
        return result
