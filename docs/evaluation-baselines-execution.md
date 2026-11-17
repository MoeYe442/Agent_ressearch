# SDD ledger — plan: D:/code/Agent/docs/superpowers/plans/2026-11-17-evaluation-baselines.md

Base cefd98c; branch codex/evaluation-baselines.
Ruling: user-selected scope and repeated implementation requests authorize inline execution of the existing roadmap; use current checkout/new branch consistent with previous deliveries — cost: no extra filesystem isolation.
Ruling: AGENT.md overrides test-first workflow; compilation/static review only — cost: runtime behavior and real quality/cost effects remain unverified.
Ruling: deterministic rule_v1 tool-response compaction instead of LLM summaries — avoids extra provider calls and summary hallucination; cost: lossy snippets may omit facts and are not semantic memory.
Preflight: task flags -> idempotency/recovery/context; context -> direct graph/compression; result counters -> collaborative reducer/export; CONFIGS -> runner/review/comparisons. Shared interfaces accounted for in plan.

Task 1: complete — direct mode, task/API/idempotency/recovery binding, deterministic old-tool reduction and collaborative counters; Python compileall exit0.
Task 2: complete — nine supported configurations, runner flag checks, content/source-separated review, paired descriptive comparisons and UI reload/followup controls; Python compileall and node --check exit0.
Ruling: manual facts now require content_correct separately from source-supported passed; direct source verdict is always false — necessary for fair correctness comparison; cost: regenerate old manual review templates, preserving raw runs.

Final review: baselines_final_review, one fresh-context static reviewer, cefd98c..31ad0df. No Critical, one Important (claim content/source support mixed), one Minor (direct failure error code is baseline disclaimer). Accepted Important: separate claim content_correct from supported in all modes; direct source support fixed false; answer metric uses content only, evidence quality uses both. Fixed in one pass; compiled only, no runtime proof or re-review.
Final: minor (deferred): direct failure task.error_code selects the permanent unverified disclaimer before the actionable provider/JSON/citation failure; actual reason remains in report limitations.
Final: Ruling: runtime model quality, savings, compatibility, interruption recovery and browser behavior remain unjudged — compile-only user instruction — cost: real acceptance pending.
Final: Ruling: no hard 32 KiB request ceiling — preserve recent tool results/questions/protocol — cost: large recent payloads can still exhaust budget.
Final: Ruling: compressed facts may be omitted — accepted lossy excerpt algorithm — cost: quality may decline; human coverage comparison is required.
Final: Ruling: reject pre-upgrade recovery fingerprint mismatches — keep original strict recovery semantics — cost: older unfinished tasks need original installation or a new task.
Final: Ruling: direct mode shares import/index preparation but never receives contents — hold corpus identity constant across configurations — cost: preparation still takes time and may use optional indexing services for other configurations.
Final: Ruling: counters exclude planner/reviewer, internal retries and replay event counts — describe only investigation message history transformations — cost: cannot infer whole-task savings from bytes.
Final: Ruling: local direct prompt uses generic identity — avoid exposing local paths and assigning false repository identity — cost: prior-knowledge answers may be less useful for local snapshots.
Final: Ruling: generic malformed nested-artifact robustness remains outside this increment except explicit task type checks — existing documented limitation — cost: some corrupted artifacts can still abort a report.

Task 3: complete — version0.9.0, protocol/UI/docs delivered, full Python src+eval compileall, Jinja template, Pydantic schemas/catalog, node syntax, pip check and Compose config all exit0. Independent Important finding fixed in one pass and compilation repeated; no tests, runtime/evaluation/provider/container calls or second review. One direct failure-label Minor retained above. Branch stays local, user .gitignore/AGENT.md preserved. All decisions retained in this tracked ledger; no plan scratch directory was created or deleted.
