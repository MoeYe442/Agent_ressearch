# SDD ledger — plan: D:/code/Agent/docs/superpowers/plans/2026-11-17-evaluation-hardening.md

Base599bd8e, branch codex/evaluation-hardening.
Ruling: interpret continuation as closing the explicitly documented remaining bugs, not adding another feature phase — cost: this increment delivers reliability fixes only.
Ruling: current checkout/new branch, preserve user files, compile-only per AGENT.md — cost: no filesystem isolation or runtime regression proof.
Root cause: TaskService takes limitations[0] as a failed task's code while DirectRunner prepends a permanent disclaimer; fix ordering at producer. Artifact checksum proves bytes, not nested types; unchecked .get/unhashable IDs escape semantic checks before row invalidation. Add structural checks at boundaries rather than swallowing arbitrary programming errors.
Preflight: result_shape precedes inspect_record identifiers and field access; mapping checks precede shared context/preparation aggregation; review_shape precedes review identifiers and canonical comparisons.

Task 1: complete — producer prioritizes actual provider/JSON/citation failures; structural validators guard result/task/snapshot/report/evidence/review containers and identifiers before aggregation; context and preparation reads guarded. Python compileall and diff --check exit0.

Final static review hardening_final_review: no Critical, one Important (missing shared server.model_identifier accepted as null), no Minor. Verified downstream inspect_record indexes the key inside the row error boundary. Fixed by requiring key presence before any row inspection, still permitting explicit null/string; one fix pass, compilation repeated, no runtime tests or re-review.
Final: Ruling: runtime/provider/error propagation remains unjudged — user's compile-only requirement — cost: no runtime regression proof.
Final: Ruling: runner resume/recollection parsing is not changed — this bugfix is scoped to report/review boundaries — cost: malformed runner-state behavior remains unverified.
Final: Ruling: deep JSON recursion and filesystem races/failures are outside the stated boundary — no broad exception suppression — cost: such failures may still interrupt reporting.
Final: Ruling: checksums are consistency checks, not operator-authenticity signatures — existing protocol unchanged — cost: full artifact rewrites can fabricate records.
Final: Ruling: budget/cancellation ordering stays unchanged — these statuses are partial/cancelled rather than the failed-task error-code defect — cost: existing status/error presentation semantics remain.
Task 2: complete — 0.9.1 docs and static receipt, Python src+eval/Jinja/schema/catalog, node syntax, pip and Compose config all exit0. New source fingerprint rejects old unfinished-task recovery as usual; no runtime deployment/acceptance. All changes committed locally, no push/merge, .gitignore and AGENT.md preserved. No plan scratch directory was created or deleted.
