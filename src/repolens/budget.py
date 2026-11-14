"""One atomic ledger for an entire investigation, including all graph branches."""
from dataclasses import dataclass,asdict
import threading
import time
from uuid import uuid4
from repolens.models import Usage
from repolens.execution_store import RecoveryRejected


class BudgetExceeded(ValueError):
    pass


@dataclass(frozen=True)
class Reservation:
    id: str
    input_tokens: int
    output_tokens: int
    role: str
    subtask_id: str
    cache_key: str | None = None


class BudgetManager:
    def __init__(self, settings, deadline=None, *, session=None):
        self.settings = settings
        self.started = time.monotonic()
        self.deadline = deadline if deadline is not None else self.started + settings.max_seconds
        self.lock = threading.RLock()
        self.usage = Usage()
        self.pending = {}
        self.unknown_usage = False
        self.stop_reason = None
        self.subtask_tools = {}
        self.role_usage = {}
        self.provider_slots = threading.BoundedSemaphore(2)
        self.session = session
        if session:
            self.deadline = time.monotonic() + session.deadline_utc-time.time()
            state=session.load_budget()
            if state:
                try:
                    required={'model_calls','tool_calls','input_tokens','output_tokens','revision'}
                    if state['version']!=1 or state['limits']!=self._limits() or not required<=state['usage'].keys():raise ValueError()
                    self.usage=Usage.model_validate(state['usage'])
                    if any(getattr(self.usage,k)<0 for k in required):raise ValueError()
                    self.unknown_usage=state['unknown_usage'];self.stop_reason=state['stop_reason']
                    self.subtask_tools=state['subtask_tools'];self.role_usage=state['role_usage']
                    if any(type(n) is not int or not 0<=n<=8 for n in self.subtask_tools.values()):raise ValueError()
                    pending=[Reservation(**r) for r in state['pending']]
                    if pending:
                        self.unknown_usage=True;self.usage.revision+=1
                        self._persist(record=[{**asdict(r),'status':'unknown'} for r in pending])
                except (TypeError,ValueError,KeyError):raise RecoveryRejected('recovery_budget_corrupt') from None
            else:self._persist()

    def _limits(self):
        return {key:getattr(self.settings,key) for key in ('max_model_calls','max_tool_calls','max_tokens','max_seconds','max_output_tokens')}

    def _persist(self,*,record=None,cache=None):
        if self.session:
            state={'version':1,'limits':self._limits(),'usage':self.snapshot().model_dump(),'unknown_usage':self.unknown_usage,'stop_reason':self.stop_reason,'subtask_tools':self.subtask_tools,'role_usage':self.role_usage,'pending':[asdict(r) for r in self.pending.values()]}
            self.session.save_budget(state,record=record,cache=cache)

    def check(self):
        if self.stop_reason:
            raise BudgetExceeded(self.stop_reason)
        if time.monotonic() >= self.deadline:
            raise BudgetExceeded("time_budget_exhausted")

    def reserve_model(self, input_bound, output_limit, role, subtask_id, *, allow_zero_output=False, cache_key=None):
        with self.lock:
            self.check()
            remaining = self.settings.max_tokens - self.usage.input_tokens - self.usage.output_tokens
            output = min(output_limit, self.settings.max_output_tokens, remaining - input_bound)
            if self.usage.model_calls >= self.settings.max_model_calls or input_bound < 0 or output < (0 if allow_zero_output else 1):
                raise BudgetExceeded("budget_exhausted")
            reservation = Reservation(uuid4().hex, input_bound, output, role, subtask_id,cache_key)
            self.pending[reservation.id] = reservation
            self.usage.model_calls += 1
            self.usage.input_tokens += input_bound
            self.usage.output_tokens += output
            self.usage.revision += 1
            row = self.role_usage.setdefault(role, {"model_calls": 0, "input_tokens": 0, "output_tokens": 0})
            row["model_calls"] += 1
            row["input_tokens"] += input_bound
            row["output_tokens"] += output
            self._persist(record={**asdict(reservation),'status':'pending'})
            return reservation

    def settle_model(self, reservation_id, usage_or_none, failed=False, *, cache=None):
        with self.lock:
            reservation = self.pending.pop(reservation_id, None)
            if reservation is None:
                return
            if usage_or_none is None or failed:
                self.unknown_usage = True
            else:
                if usage_or_none.input_tokens > reservation.input_tokens or usage_or_none.output_tokens > reservation.output_tokens:
                    self.stop_reason = "provider_usage_exceeded_reservation"
                delta_in = usage_or_none.input_tokens - reservation.input_tokens
                delta_out = usage_or_none.output_tokens - reservation.output_tokens
                self.usage.input_tokens += delta_in
                self.usage.output_tokens += delta_out
                self.role_usage[reservation.role]["input_tokens"] += delta_in
                self.role_usage[reservation.role]["output_tokens"] += delta_out
            self.usage.revision += 1
            self._persist(record={**asdict(reservation),'status':'error' if failed else 'completed'},cache=cache)

    def release_unsent(self, reservation_id):
        """Rollback only a request that has not entered the provider."""
        with self.lock:
            reservation = self.pending.pop(reservation_id, None)
            if reservation is None:
                return
            self.usage.model_calls -= 1
            self.usage.input_tokens -= reservation.input_tokens
            self.usage.output_tokens -= reservation.output_tokens
            row = self.role_usage[reservation.role]
            row["model_calls"] -= 1
            row["input_tokens"] -= reservation.input_tokens
            row["output_tokens"] -= reservation.output_tokens
            if row["model_calls"] == 0:
                self.role_usage.pop(reservation.role)
            self.usage.revision += 1
            self._persist(record={**asdict(reservation),'status':'unsent'})

    def reserve_tool(self, subtask_id=None):
        with self.lock:
            self.check()
            if self.usage.tool_calls >= self.settings.max_tool_calls:
                raise BudgetExceeded("budget_exhausted")
            if subtask_id is not None and self.subtask_tools.get(subtask_id, 0) >= 8:
                raise BudgetExceeded("subtask_tool_limit")
            self.usage.tool_calls += 1
            self.usage.revision += 1
            if subtask_id is not None:
                self.subtask_tools[subtask_id] = self.subtask_tools.get(subtask_id, 0) + 1
            self._persist()

    def snapshot(self):
        with self.lock:
            elapsed=time.time()-self.session.started if self.session else time.monotonic()-self.started
            return self.usage.model_copy(update={"estimated": self.unknown_usage or bool(self.pending), "elapsed_ms": round(max(0,elapsed)*1000, 2)})

    def roles(self):
        with self.lock:
            return {name: dict(row) for name, row in self.role_usage.items()}
