# SDD ledger — plan: D:/code/Agent/docs/superpowers/plans/2026-11-14-durable-recovery.md

User explicitly chose V3 task durability/interruption recovery. Base296778b, branchcodex/durable-recovery; inline execution, one final fresh-context reviewer, no push/merge.
Ruling: Existing approved overall design plus explicit start/selected V3 authorize this incremental execution without repeating approval — technical defaults recorded in plan — cost: not the full Redis/Postgres/web V3 milestone.
Ruling: Reuse current clean checkout on feature branch and native Windows ledger rather than a second checkout/Bash helper scripts — preserve environment and prior completed branch — cost: no second filesystem isolation.
Ruling: Persist original absolute900s deadline across interruption — cannot extend task wall-clock budget through restart — cost: after expiry, original task cannot resume and needs a new explicit investigation.
Preflight: WorkerLease->all fenced state/journal/checkpoint writers; session->budget and cached responses with atomic settlement; stable model/tool keys->single replay and graph checkpoint; official saver->task resume eligibility and finalization; task defaults->legacyfailed/interrupted preserved; UI->explicit resume keys and event sequence. No locks/clients/secrets serialized.
Dependencies: isolated original lock+langgraph-checkpoint-sqlite3.1.3 installed; original FastAPI/Pydantic/LangGraph unchanged; smoke and pip check next before project install.
Tasks:1pending;2pending;3pending;4pending;5pending.

Task1complete: missing-moduleRED then6tests passed; isolated official sync/pending-write smoke retained completed sibling once; original locked packages unchanged, project lock installed and pipcheck green. Fenced saver uses same SQLite transaction for authority check and official checkpoint writes; pickle fallback disabled.

Task2complete: six missing-session RED plus tool transcript replay RED (five instead of three provider calls), then new durable/original Agent/retrieval budget regressions green. Budgets/child caps/stop latch/deadline persist; response+settlement atomic; cached turns/tools reuse original transcript and do not increment cost. Auxiliary keys fixed to model/input/index/scope. Pending reservations retained as unknown estimates.

Task3complete: shutdown-cancelled/missing-resume RED and atomic resume trigger RED, then task/graph/API/old failure regressions green. Official checkpointer wraps single and parallel graphs; stop preserves partial, user cancel remains terminal; response before stop replays without replanning or extra provider calls. Resume key/queue/event/graph transition atomic; global lease and task epoch fence writers. API route connected early alongside producer contracts.

Task4complete: missing resume API/button and atomic resume trigger RED; context rejects, cache-body tamper RED then checksum guard, and interrupted-state UI RED then separate recovery notice. Fifteen lease/checkpoint/API cases and all42 browser tests passed; six recovery UI cases include lost-response reload and320/390/736/1024. Heartbeat delayed by writer lock may renew only unchanged owner/epoch; takeover still fences old renew/write. Deadline shown; unknown fee warning and cumulative usage preserved.

Task5 validation finding: first full326 had325pass + legacy trickle timing failure. Measured client construction SSL load1.0–1.5s; actual bounded resolve .13–.16s. Ruling: measure trickling network operation after constructing adapter, preserving .15s deadline and strict<1s assertion — removes unrelated certificate-loader timing from network timeout test — cost: this assertion does not bound SSL initialization. No GitHub runtime/security behavior changed.

Task5 implementation verified: four real process exits passed with exact observed calls3/4/3/7, eight audit cases all observed/pass, missing/stale denominator collector RED thenGREEN. New task/graph/replay/API/browser checks passed; first full325pass plus legacy SSL-initialization timing failure, corrected network timer targeted2pass. Unchanged full compatibility rerun ongoing; code frozen for concurrent read-only final review. Overall completion awaits green whole suite and review fixes.

Task5 first final suite: 326passed/4warnings/375.03s; audit8/8, four real-process recoveries and four no-new-provider rejections. Fresh-context whole-branch reviewer durability_final_review reviewed296778b..215c706 read-only; three Important, one Minor, no Critical. Findings accepted at their effect grades; one fix pass, no re-review.
Final fixes targeted: arbitrary msgpack constructor sentinel RED (invoked os.getcwd)→GREEN with explicit strict safe-type allowlist, real pending Send branch remains GREEN; unavailable/replaced hybrid index eligibility RED and after-acceptance usage-zero race RED→GREEN, durable usage/role usage/verified prior claims retained; graph limit/provider timeout/Milvus collection plus six omitted execution modules RED→GREEN with all package Python sources and all non-secret/path-independent settings bound. Targeted22passed. Whole339-case suite running.
Final: minor (deferred): recoverable partial cannot be cancelled from workbench; backend cancellation works, UI cancellation button stays disabled on terminal partial. Users can leave it paused (no automatic cost) or explicitly cancel via API.
Final: Ruling: Redis/PostgreSQL/distributed queues/multiple active workers/Docker remain excluded — approved scope is one SQLite worker — cost: no production or distributed durability acceptance.
Final: Ruling: import/index construction retain failure-and-explicit-retry semantics — this increment recovers investigations only — cost: interrupted import/index work must be repeated explicitly.
Final: Ruling: actual billing/live compatibility/answer quality remain unjudged — real providers are unconfigured and no live calls were made — cost: production effectiveness and monetary savings remain unproven.
Final: Ruling: do not extend original deadline or depleted budget — preserve approved cumulative limits — cost: late/exhausted investigations require a new explicitly created task.
Final: Ruling: do not promise exactly-once for responses never saved — retain unknown reservations before a possible resend — cost: external providers may charge duplicate requests.

Task 1: complete (296778b..9dfa45d; official saver/lease smoke and targeted tests GREEN).
Task 2: complete (9dfa45d..cced4a5; durable budgets, transcript/tool replay regressions GREEN).
Task 3: complete (cced4a5..91f230b; task/graph/atomic-resume lifecycle regressions GREEN).
Task 4: complete (91f230b..783a67c; API and all42browser regressions GREEN).
Task 5: complete (783a67c..final delivery; real process crashes/auditable fixed denominator, final whole suite GREEN).
Final: fixed permissive msgpack constructors — test_checkpoint_deserializer_never_invokes_unregistered_constructor RED→GREEN, suite339/339.
Final: fixed hybrid generation eligibility/accounting race — tests/test_hybrid_recovery.py (three cases) RED→GREEN, suite339/339; report/event/task preserve durable model_calls=1 rather than0.
Final: fixed incomplete runtime/code binding — tests/test_recovery_signature.py (nine cases) RED→GREEN, suite339/339.
Final evidence: .venv/Scripts/python -m pytest -q --tb=short →339passed/4warnings/371.57s (42browser included); eval.recovery →8/8, four real exits resumed and four invalid contexts rejected, quality null; compileall exit0, pipcheck no broken requirements. Formal0.5.0 service restarted after fixes; local import, unconfigured model zero calls, resume409, default single/keyword and no page errors verified. No live provider calls.
Final disposition: keep local codex/durable-recovery branch and current checkout; do not push or merge. Archive this ledger in docs/durable-execution.md, package tracked source plus selected receipts, verify CRC and every SHA256, then attempt cleanup of this plan workspace only.
