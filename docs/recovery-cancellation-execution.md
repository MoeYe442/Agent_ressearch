# SDD ledger — plan: D:/code/Agent/docs/superpowers/plans/2026-11-17-recovery-cancellation.md

Base d468337; branch codex/recovery-cancellation.
Ruling: continuation closes the previously documented recovery cancellation gap — cost: no new roadmap feature in this increment.
Ruling: preserve current checkout/user files and compile-only instruction — cost: no extra filesystem isolation or runtime/browser regression proof.
Root causes: taskControls/updateTask disable all terminal statuses, including resumable partial; backend cancel rebuilds paused_report without graph and discards saved findings. Fix frontend predicate and producer transition, retaining the existing API.
Preflight: UI per-task actions cover resume/cancel/poll controls; backend saved AnalysisResult -> cancelled report, updated authoritative task usage -> one _save transaction. No changed model/tool interfaces.
