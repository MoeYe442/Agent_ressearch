# SDD ledger — plan: D:/code/RepoLens-V1-Implementation-Plan.md

Implementation authorized by user on 2026-11-10. Use current empty D:/code/Agent as new project root; no Git exists, so retain local files and deliver ZIP as plan permits. No worktree or Git initialization required.

Pre-flight: Task 1 snapshot + SQLite -> Task 2 indexing/evidence -> Task 3 runner -> Task 4 queue/API -> Task 5 UI -> Task 6 evaluation. Shared IDs are strings, Pydantic JSON persisted in SQLite, snapshot scope fixed in ToolContext.
Ruling: Plan is the explicit V1 delivery scope; broader design features (GitHub import, multi-agent, cross-process resume) remain deferred. Cost: narrower V1 than eventual design.
Ruling: repository import receives an ID immediately and has persistent importing/ready/failed status; indexing runs on the single background worker. No model required for import or indexing.
Ruling: No Git available; use this ledger and test logs instead of Git-specific shell helper scripts, which assume a Git/Bash workspace.

Tasks: 1 pending; 2 pending; 3 pending; 4 pending; 5 pending; 6 pending.
`nTask 1: complete — pytest tests/test_repositories.py -q: 5 passed. RED missing repolens.config observed before implementation.
`nTask 2: complete — 11 passed; RED missing indexing module observed. FTS5 required explicitly; symbol and text hits produce scope-checked, hash-verified evidence.
`nTask 3: complete — 10 passed; RED missing agent module observed. Real HTTP adapter, 3-attempt bounded retries, conservative pre-call reservation and usage reconciliation, one JSON repair, observed-evidence allowlist.
`nTask 4: complete — 8 passed; RED missing tasks/API modules observed. Persistent single worker, atomic state/events, idempotency transaction, SSE cursors and restart failure/requeue covered. Dependency deprecation warning noted for lockfile reconciliation.
`nTask 5: complete — 8 browser tests passed using installed Chromium 1234 via REPOLENS_BROWSER_EXECUTABLE while matching-browser download continues. Missing-template RED observed before implementation. Desktop/mobile PNGs visually inspected; four viewport overflow checks passed.
`nTask 6: core implementation complete — 50 tests passed (including 8 browser tests and five-question synthetic regression), compileall src succeeded. No real model configured; no real-model performance claim. Final review and packaging pending. Synthetic-model shared-round state bug was reproduced then fixed in test-only adapter by deriving round from each conversation.

Ruling: Replace Git subprocess provenance with bounded pure-data loose SHA-1 metadata verification. Untrusted fsmonitor reproduction proved the original approach could execute repository code; packed/unsupported metadata now uses manifest only. Cost: no commit annotation for those formats, analysis and exact evidence still work.
Ruling: Missing local paths are a user-visible validation failure worth fixing now despite reviewer Minor grade; stable repository_not_found replaces 500. Cost: none.
Ruling: Capability validation occurs on first real model request rather than a charged startup probe. Cost: incompatible-provider errors surface at first analysis; README states this.
Final review: one fresh-context read-only reviewer; 2 Critical, 9 Important and 1 Minor findings reproduced and addressed in one fix pass. No re-review claimed. Every product fix had a failing regression before implementation; specific mapping in docs/implementation-decisions.md.
Final: fixed Git program execution, junction race, byte/commit attribution, readiness publication, report/terminal transaction, total HTTP deadline, retry idempotency, stale async UI state, physical line coordinates, Markdown forged markers, and five-topic evaluation positive controls. Missing-path response fixed too.
Final: full suite 64/64 passed in 48.82s, 10 browser checks included; compileall src passed; pip check clean. Known third-party deprecation warning documented. No deferred minor findings.
Final: real model unconfigured. Formal local service startup, health and browser banner verified, no model call fabricated. Model quality/cost remain unassessed; future V1 scope exclusions retained.
Task 6: complete — five-question synthetic structure controls 5/5, quality pending manual; documentation and source package prepared. No Git integration applies; plan explicitly selects local ZIP delivery.
