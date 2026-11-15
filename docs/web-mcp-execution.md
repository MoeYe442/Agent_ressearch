# SDD ledger — plan: D:/code/Agent/docs/superpowers/plans/2026-11-15-web-documents-mcp.md

Base9da4106, branch codex/web-documents-mcp.
Ruling: explicit selected scope and approved overall design authorize conservative implementation without repeated permission — cost: no full-web search or arbitrary external MCP server execution.
Ruling: user AGENT.md requires compile only, overriding TDD and runtime acceptance — cost: runtime collection/render/MCP compatibility remains unverified.
Ruling: reuse current checkout on new branch preserving user .gitignore/AGENT.md — cost: no second filesystem isolation.
Ruling: require exact host allowlist and HTTPS/public pinned IP; optional dynamic rendering only in network-disabled Linux sidecar — cost: cross-host resources need explicit configuration and native Windows has static fallback.
Preflight: immutable source IDs -> task/context/signature/evidence; web jobs -> durable dispatch/fencing; registry -> Agent and stdio MCP; broker -> no-network renderer; web metadata -> migration and UI.
Tasks1–5 pending.

Tasks1–4 implemented: public pinned HTTPS/destination checks, bounded extraction and immutable web evidence; Linux no-network renderer verifies loopback-only interfaces, private bounded IPC with resource GET broker, process group/time/memory limits and fallback; API/queue/task attachment/role/restore/migration integration; UI submission retries and URL/paragraph metadata; official MCP1.25 stdio uses exact same registry schema/scope and per-process tool budget, no collection/model/shell capability.
Dependencies: MCP1.25 installed constrained by original lock; existing FastAPI/Pydantic/LangGraph versions unchanged. pywin32 pin has Windows marker so Linux container does not install a Windows-only wheel. No full SDK major upgrade.
Initial compile receipt: Python/Jinja1 template, node--check, pipcheck, Compose browser+migration config--quiet all exit0; tests/web/MCP/browser/container/model execution all false. Code freezing for one whole-branch static review, not runtime acceptance.

Final review web_mcp_final_review: no Critical, two Important accepted, one Minor deferred. One fix pass: pageerror and active-resource requestfailed now set renderer incomplete before navigation, causing existing static fallback; final collaboration presence check now treats attached documents like the investigate guard. No tests run, compile follows. The initial CORS example was withdrawn after installed Playwright driver source showed automatic fulfilled-response CORS handling; no CORS-policy change made.
Final: minor (deferred): successful dynamic rendering may display first body line instead of original HTML page title — provenance URL, hash and paragraph citation remain intact, label polish deferred.
Final: Ruling: actual DNS/TLS, Chromium sandbox/container compatibility, extraction quality, cancellation/crash timing, MCP interoperability, migration execution and model quality remain unjudged — user required compile only — cost: runtime/deployment acceptance still needed.
Final: Ruling: retain exact explicitly supplied URL query parameters rather than guessing credentials from parameter names — preserves source provenance and legitimate document URLs — cost: complete URL including query can be persisted and exposed in model-readable metadata.

Task 1: complete — bounded anonymous public pinned HTTPS, UTF-8 extraction, immutable paragraphs and cross-snapshot/hash evidence checks implemented and compiled.
Task 2: complete — network-disabled optional renderer, private broker frames, request/byte/time/process limits and static fallback implemented and compiled; no browser/container run.
Task 3: complete — explicit collection jobs with outbox/fencing, cancel/interruption behavior, fixed task attachments/signature and web-only/docs scope, migration refusal for active collection implemented and compiled.
Task 4: complete — UI collection intent/retry/followup and evidence provenance, saved-document list/search/fetch, official readonly stdio MCP adapter implemented and compiled; no UI/MCP runtime session.
Task 5: complete — one fresh static whole-branch review34fe632, two Important fixes in one pass, one Minor deferred. Final compile_delivery.py exit0: Python compileall, Jinja1 template compile, JS syntax, pipcheck, Compose browser+migration config--quiet, git diff--check. Tests, webpages, MCP, browser, containers and providers all NOT run. No second review.
Final disposition: preserve local codex/web-documents-mcp commits, no push/merge; preserve user .gitignore and AGENT.md. Archive this ledger in docs/web-mcp-execution.md and compile receipt in docs/results/web-mcp-compile.json. Source-only ZIP comes from committed tree; current native service untouched. Runtime acceptance remains pending.
