# SDD ledger — plan: D:/code/Agent/docs/superpowers/plans/2026-11-17-evaluation-baselines.md

Base cefd98c; branch codex/evaluation-baselines.
Ruling: user-selected scope and repeated implementation requests authorize inline execution of the existing roadmap; use current checkout/new branch consistent with previous deliveries — cost: no extra filesystem isolation.
Ruling: AGENT.md overrides test-first workflow; compilation/static review only — cost: runtime behavior and real quality/cost effects remain unverified.
Ruling: deterministic rule_v1 tool-response compaction instead of LLM summaries — avoids extra provider calls and summary hallucination; cost: lossy snippets may omit facts and are not semantic memory.
Preflight: task flags -> idempotency/recovery/context; context -> direct graph/compression; result counters -> collaborative reducer/export; CONFIGS -> runner/review/comparisons. Shared interfaces accounted for in plan.

Task 1: complete — direct mode, task/API/idempotency/recovery binding, deterministic old-tool reduction and collaborative counters; Python compileall exit0.
Task 2: complete — nine supported configurations, runner flag checks, content/source-separated review, paired descriptive comparisons and UI reload/followup controls; Python compileall and node --check exit0.
Ruling: manual facts now require content_correct separately from source-supported passed; direct source verdict is always false — necessary for fair correctness comparison; cost: regenerate old manual review templates, preserving raw runs.
