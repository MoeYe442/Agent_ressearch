import json
import threading
from pydantic import ValidationError
from repolens.budget import BudgetExceeded
from repolens.model_client import HTTPChatModel, ProviderError
from repolens.models import TaskEvent
from repolens.models import ModelTurn
from repolens.execution_store import RecoveryRejected,WorkerPaused,LeaseLost


class ModelGateway:
    def __init__(self, model, budget, emit, cancelled, task_id):
        self.model, self.budget = model, budget
        self.emit, self.cancelled, self.task_id = emit, cancelled, task_id
        self.slots = budget.provider_slots
        self.session=budget.session

    def check(self):
        if self.session:self.session.check()
        if self.cancelled():
            raise BudgetExceeded("cancelled")
        self.budget.check()

    def event(self, type, role, subtask_id, **payload):
        self.emit(TaskEvent(task_id=self.task_id, type=type, payload={"role": role, "subtask_id": subtask_id, **payload}))

    def complete(self, messages, tools, role="single", subtask_id="single"):
        self.check()
        if self.model is None:
            raise ProviderError("model_not_configured")
        while not self.slots.acquire(timeout=.05):
            self.check()
        try:
            for retry in range(3):
                self.check()
                key=self.session.cache_key('model',{'messages':messages,'tools':tools,'role':role,'subtask_id':subtask_id,'retry':retry}) if self.session else None
                cached=self.session.get_cache('model',key) if self.session else None
                if cached:
                    self.event('model_replayed',role,subtask_id,usage=self.budget.snapshot().model_dump())
                    if cached.get('status')=='error':
                        exc=ProviderError(cached['code'],cached['retryable'])
                        if exc.retryable and retry<2:continue
                        raise exc
                    try:return ModelTurn.model_validate(cached['data'])
                    except (ValueError,KeyError):raise RecoveryRejected('recovery_cache_corrupt') from None
                bound = len(json.dumps([messages, tools], ensure_ascii=False).encode("utf-8")) + 1024 * (len(messages) + 1)
                reservation = self.budget.reserve_model(bound, self.budget.settings.max_output_tokens, role, subtask_id,cache_key=key)
                try:
                    self.event("model_started", role, subtask_id, call=self.budget.snapshot().model_calls, input_reserved=bound, output_reserved=reservation.output_tokens, usage=self.budget.snapshot().model_dump())
                    self.check()
                except BaseException as exc:
                    self.budget.release_unsent(reservation.id)
                    if isinstance(exc, BudgetExceeded):
                        self.event("model_aborted", role, subtask_id, error_code=str(exc), usage=self.budget.snapshot().model_dump())
                    raise
                try:
                    model = self.model.with_deadline(self.budget.deadline) if isinstance(self.model, HTTPChatModel) else self.model
                    turn = model.complete(messages, tools, max_output_tokens=reservation.output_tokens)
                except ProviderError as exc:
                    cache=('model',key,{'status':'error','code':exc.code,'retryable':exc.retryable}) if key else None
                    self.budget.settle_model(reservation.id, None, failed=True,cache=cache)
                    self.event("model_error", role, subtask_id, error_code=exc.code, retryable=exc.retryable, usage=self.budget.snapshot().model_dump())
                    if exc.retryable and retry < 2:
                        continue
                    raise
                except (WorkerPaused,LeaseLost,RecoveryRejected):
                    raise
                except BaseException:
                    self.budget.settle_model(reservation.id, None, failed=True)
                    raise ProviderError("provider_unexpected_error") from None
                cache=('model',key,{'status':'ok','data':turn.model_dump(mode='json')}) if key else None
                self.budget.settle_model(reservation.id, turn.usage,cache=cache)
                self.event("model_completed", role, subtask_id, usage=self.budget.snapshot().model_dump())
                self.check()
                usage = self.budget.snapshot()
                if usage.input_tokens + usage.output_tokens > self.budget.settings.max_tokens:
                    raise BudgetExceeded("budget_exhausted")
                return turn
        finally:
            self.slots.release()

    def structured(self, messages, schema, role, subtask_id):
        messages = list(messages)
        for attempt in range(2):
            turn = self.complete(messages, [], role, subtask_id)
            try:
                if turn.tool_calls:
                    raise ValueError("unexpected_tool_calls")
                return schema.model_validate_json(turn.content)
            except (ValidationError, ValueError):
                if attempt:
                    raise ProviderError("invalid_model_json") from None
                messages.extend([{"role": "assistant", "content": turn.content[:10000]}, {"role": "user", "content": "Invalid structured JSON. Return exactly this schema: " + json.dumps(schema.model_json_schema())}])

    def external(self, call, input_bound, role, subtask_id, *, output_bound=0,cache_payload=None):
        """One auxiliary model call, charged to the same atomic investigation ledger."""
        self.check()
        if self.session and cache_payload is None:raise RecoveryRejected('recovery_external_key_missing')
        key=self.session.cache_key('external',{'payload':cache_payload,'role':role,'subtask_id':subtask_id}) if self.session else None
        cached=self.session.get_cache('external',key) if self.session else None
        if cached:
            self.event('model_replayed',role,subtask_id,usage=self.budget.snapshot().model_dump())
            if cached.get('status')=='error':raise ProviderError(cached['code'])
            if cached.get('status')!='ok' or 'data' not in cached:raise RecoveryRejected('recovery_cache_corrupt')
            return cached['data']
        while not self.slots.acquire(timeout=.05):
            self.check()
        try:
            self.check()
            reservation = self.budget.reserve_model(input_bound, output_bound, role, subtask_id, allow_zero_output=True,cache_key=key)
            try:
                self.event("model_started", role, subtask_id, usage=self.budget.snapshot().model_dump())
                self.check()
            except BaseException as exc:
                self.budget.release_unsent(reservation.id)
                if isinstance(exc, BudgetExceeded):
                    self.event("model_aborted", role, subtask_id, error_code=str(exc), usage=self.budget.snapshot().model_dump())
                raise
            try:
                data, measured = call()
            except (WorkerPaused,LeaseLost,RecoveryRejected):
                raise
            except BaseException as exc:
                cache=('external',key,{'status':'error','code':exc.code if isinstance(exc,ProviderError) else 'auxiliary_request_failed'}) if key else None
                self.budget.settle_model(reservation.id, None, failed=True,cache=cache)
                self.event("model_error", role, subtask_id, error_code="auxiliary_request_failed", usage=self.budget.snapshot().model_dump())
                raise
            cache=('external',key,{'status':'ok','data':data}) if key else None
            self.budget.settle_model(reservation.id, measured,cache=cache)
            self.event("model_completed", role, subtask_id, usage=self.budget.snapshot().model_dump())
            self.check()
            return data
        finally:
            self.slots.release()
