# SDD ledger — plan: D:/code/Agent/docs/superpowers/plans/2026-11-11-github-import.md

User approved on 2026-11-12. Inline execution, one fresh-context final review.
Base: 9d26ea6. Feature branch feature/github-import; reuse current suitable checkout rather than add a worktree. Original main retained.
Pre-flight: Task 1 GitHubSource/ResolvedGitHubSource -> Task 2 validated archive snapshot -> Task 3 persistent API -> Task 4 UI. Existing snapshot JSON stays compatible through default-valued fields. No new dependencies.
Ruling: Existing shared checkout is suitable; use feature branch for integration isolation and local ledger instead of Git/Bash-only helper scripts. Cost: no separate filesystem checkout; protect unrelated files and inspect git status each task.
Tasks: 1 complete; 2 complete; 3 complete; 4 complete.

Task 1: complete — 31 tests passed; missing-module RED observed. Fixed HTTPS hosts, public DNS/peer checks, per-operation/shared deadline, response size counters, no codeload auth, branch/ref resolved once.

Task 2: complete — 47 importer/local safety/evidence regressions passed. RED missing importer observed. Shared SnapshotWriter preserves secure local source reads; ZIP metadata validated before writes, each included blob checked against pinned tree, omitted files recorded. One test fixture limit was moved to the boundary under test after initial resolution (no product bypass).

Task 3: complete — 20 GitHub/API/task tests passed. RED unknown create_app factory argument observed. Public source/ref normalization, backward-compatible local imports/JSON, cross-source idempotency, persistent failures, async queue and commit-bound report citations verified.

Task 4: UI core complete — 8 new browser tests passed after missing-source-selector RED. Real network smoke blocked explicitly: system DNS returns 198.18.0.80 / 198.18.0.174 for fixed GitHub hosts. Ruling: keep public-destination protections, do not mutate user networking or mislabel mock as real. Cost: true GitHub import remains unverified on this host until DNS meets the constraint. Full suite / final review pending.

Final review: one fresh-context read-only reviewer; 6 Important and 3 Minor findings. No second review claimed. Reviewer mapping and concrete regression names are recorded in docs/github-import.md.
Ruling: Re-grade unstable protocol error codes, legacy list default fields, and mutable in-flight form controls as implementation requirements (compatibility/error/request consistency), not optional polish. All were reproduced RED then fixed. Cost: small regression additions, no expanded feature scope.
Ruling: Use a public HTTPCore network backend through an HTTPX transport bridge; pin validated numeric IPs, retain original Host/SNI/TLS, and cap outstanding daemon OS DNS jobs per fixed host. Cost: adapter needs regression when upgrading pinned HTTP libraries; no new installed packages.
Ruling: Reject unsupported ZIP64/multi-disk/SFX and BZIP2/LZMA compression, bound central-directory allocation, path depth/length and implicit prefix aliases. Existing resource limits do not require ZIP64. Cost: forced uncommon archive formats fail explicitly rather than entering an unbounded decoder.
Final: fixed DNS rebinding gap and request/total DNS deadlines; path aliases/devices; central-directory/decompression allocation; worker shutdown; restart/index-failure cleanup and exclusive download ownership; protocol errors; legacy list records; active form state. All covering tests observed failing then passing.
Final: pinned-IP implementation's first-address-only route failure was reproduced and fixed with bounded fallback across checked public addresses. Full suite includes this new regression.
Final verification: 165 passed in 142.93s, including 19 browser tests; compileall src passed; pip check clean; editable install version 0.2.0. Desktop/mobile screenshots visually inspected. Two known test warnings documented.
Final live startup: 127.0.0.1:8000, version 0.2.0, test_environment false. Real GitHub import still blocked by non-public DNS (198.18.0.0/15); actual page shows explicit failure, no JS errors or mobile overflow. No model call or quality/cost claim.
Ruling: Keep feature/github-import local, with main and origin/main intact. Prior push was for the earlier V1 commit, not a standing publication request. Cost: this increment is not yet on the remote until requested.
Task 4: complete — UI, full regression, independent review fixes, truthful blocked-network record, startup verification, and delivery documentation finished. Source ZIP must pass byte/hash/exclusion checks before final response.
