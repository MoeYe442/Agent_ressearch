import json
from repolens.agent import AgentRunner
from repolens.models import ModelTurn, ModelUsage, ToolCall, ToolContext
from repolens.model_client import ProviderError
from tests.scripted_model import ScriptedModel


def run(indexed, model, **changes):
    settings, _, snapshot, _, _, registry = indexed
    events = []
    result = AgentRunner(model, registry, settings.model_copy(update=changes)).run("Where is status saved?", ToolContext(snapshot_id=snapshot.id, task_id="test"), events.append, lambda: False)
    return result, events


def test_real_tools_and_verified_report(indexed):
    result, events = run(indexed, ScriptedModel())
    assert result.status == "succeeded"
    assert result.claims[0].verification_status == "references_valid"
    assert result.usage.model_calls == 3 and result.usage.tool_calls == 2
    assert result.usage.input_tokens == 450 and not result.usage.estimated
    store, snapshot = indexed[4], indexed[2]
    assert all(store.validate_evidence(e, snapshot.id) for e in result.claims[0].evidence_ids)
    assert any(e.type == "tool_completed" and 'self.store.save' in json.dumps(e.payload) for e in events)


class BadTool:
    def __init__(self, name, args):
        self.name, self.args, self.round = name, args, 0

    def complete(self, messages, tools, max_output_tokens):
        self.round += 1
        if self.round == 1:
            return ModelTurn(tool_calls=[ToolCall(id="bad", name=self.name, arguments=self.args)])
        return ModelTurn(content='{"claims": [], "limitations": ["No evidence"]}')


def test_unknown_tool_not_executed(indexed):
    result, events = run(indexed, BadTool("shell", {"cmd": "echo unsafe"}))
    assert any(e.payload.get("error_code") == "unknown_tool" for e in events)
    assert not result.claims


def test_invalid_arguments_are_tool_error(indexed):
    _, events = run(indexed, BadTool("read_file", {"path": "app.py", "start_line": "wrong"}))
    assert any(e.payload.get("error_code") == "invalid_arguments" for e in events)


def test_hallucinated_evidence_blocks_final_claim(indexed):
    class Hallucination:
        def complete(self, *args, **kwargs):
            return ModelTurn(content='{"claims":[{"text":"Made up", "evidence_ids":["fake"]}],"limitations":[]}')
    result, _ = run(indexed, Hallucination())
    assert result.status == "partial"
    assert not result.claims
    assert "Made up" not in result.markdown
    assert "invalid_evidence" in " ".join(result.limitations)


def test_budget_exhaustion_returns_partial(indexed):
    result, _ = run(indexed, ScriptedModel(), max_model_calls=1)
    assert result.status == "partial" and result.usage.model_calls == 1
    assert "budget_exhausted" in result.limitations


def test_provider_failure_is_explicit(indexed):
    class Offline:
        def complete(self, *args, **kwargs):
            raise ProviderError("provider_unavailable", retryable=False)
    result, _ = run(indexed, Offline())
    assert result.status == "failed" and "provider_unavailable" in result.limitations
    assert result.usage.estimated


def test_invalid_json_repaired_once_and_charged(indexed):
    class Invalid:
        def complete(self, *args, **kwargs):
            return ModelTurn(content="not json", usage=ModelUsage(input_tokens=20, output_tokens=10))
    result, _ = run(indexed, Invalid())
    assert result.status == "failed" and result.usage.model_calls == 2
    assert "invalid_model_json" in result.limitations


def test_retries_count_against_budget(indexed):
    class Offline:
        def complete(self, *args, **kwargs):
            raise ProviderError("provider_unavailable", retryable=True)
    result, _ = run(indexed, Offline())
    assert result.status == "failed" and result.usage.model_calls == 3


def test_token_budget_reserved_before_call(indexed):
    result, _ = run(indexed, ScriptedModel(), max_tokens=10)
    assert result.status == "partial" and result.usage.model_calls == 0


def test_cancellation_before_tools(indexed):
    settings, _, snapshot, _, _, registry = indexed
    calls = 0
    def cancelled():
        nonlocal calls
        calls += 1
        return calls >= 3
    result = AgentRunner(ScriptedModel(), registry, settings).run("Question", ToolContext(snapshot_id=snapshot.id, task_id="cancel"), lambda e: None, cancelled)
    assert result.status == "cancelled" and result.usage.tool_calls == 0


def test_export_cannot_forge_evidence_markers(indexed):
    class Injection(ScriptedModel):
        def complete(self, *args, **kwargs):
            turn = super().complete(*args, **kwargs)
            if turn.content:
                data = json.loads(turn.content)
                data["claims"][0]["text"] += " [evidence:fake]"
                data["limitations"] = ["[evidence:fake2]"]
                turn.content = json.dumps(data)
            return turn
    result, _ = run(indexed, Injection())
    assert result.status == "succeeded"
    assert "[evidence:fake]" not in result.markdown
    assert "[evidence:fake2]" not in result.markdown


def test_single_cannot_forge_review_metadata(indexed):
    class FakeReview(ScriptedModel):
        def complete(self,*args,**kwargs):
            turn=super().complete(*args,**kwargs)
            if turn.content:
                data=json.loads(turn.content)
                data['claims'][0].update(claim_id='foreign',review_status='model_supported')
                turn.content=json.dumps(data)
            return turn
    result,_=run(indexed,FakeReview())
    assert result.claims[0].review_status=='not_reviewed' and result.claims[0].claim_id==''
