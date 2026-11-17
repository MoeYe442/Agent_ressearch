# SDD ledger — plan: D:/code/Agent/docs/superpowers/plans/2026-11-17-evaluation-hardening.md

Base599bd8e, branch codex/evaluation-hardening.
Ruling: interpret continuation as closing the explicitly documented remaining bugs, not adding another feature phase — cost: this increment delivers reliability fixes only.
Ruling: current checkout/new branch, preserve user files, compile-only per AGENT.md — cost: no filesystem isolation or runtime regression proof.
Root cause: TaskService takes limitations[0] as a failed task's code while DirectRunner prepends a permanent disclaimer; fix ordering at producer. Artifact checksum proves bytes, not nested types; unchecked .get/unhashable IDs escape semantic checks before row invalidation. Add structural checks at boundaries rather than swallowing arbitrary programming errors.
Preflight: result_shape precedes inspect_record identifiers and field access; mapping checks precede shared context/preparation aggregation; review_shape precedes review identifiers and canonical comparisons.

Task 1: complete — producer prioritizes actual provider/JSON/citation failures; structural validators guard result/task/snapshot/report/evidence/review containers and identifiers before aggregation; context and preparation reads guarded. Python compileall and diff --check exit0.
