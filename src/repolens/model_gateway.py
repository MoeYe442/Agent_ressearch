import json
import threading
from pydantic import ValidationError
from repolens.budget import BudgetExceeded
from repolens.model_client import HTTPChatModel, ProviderError
from repolens.models import TaskEvent


class ModelGateway:
    def __init__(self, model, budget, emit, cancelled, task_id):
        self.model, self.budget = model, budget
        self.emit, self.cancelled, self.task_id = emit, cancelled, task_id
        self.slots = threading.BoundedSemaphore(2)

    def check(self):
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
                bound = len(json.dumps([messages, tools], ensure_ascii=False).encode("utf-8")) + 1024 * (len(messages) + 1)
                reservation = self.budget.reserve_model(bound, self.budget.settings.max_output_tokens, role, subtask_id)
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
                    self.budget.settle_model(reservation.id, None, failed=True)
                    self.event("model_error", role, subtask_id, error_code=exc.code, retryable=exc.retryable, usage=self.budget.snapshot().model_dump())
                    if exc.retryable and retry < 2:
                        continue
                    raise
                except BaseException:
                    self.budget.settle_model(reservation.id, None, failed=True)
                    raise ProviderError("provider_unexpected_error") from None
                self.budget.settle_model(reservation.id, turn.usage)
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
