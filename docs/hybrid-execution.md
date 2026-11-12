# SDD ledger — plan: D:/code/Agent/docs/superpowers/plans/2026-11-12-hybrid-retrieval.md

User requested implementation and selected configurable integration/offline regression, real services accepted later. Base 0a32cf4, branch codex/hybrid-retrieval, current clean suitable checkout reused. No push/merge.
Ruling: The already-approved overall V2 design and this turn's explicit implementation + approach choice authorize execution without another approval gate — avoid repeating user decisions — cost: technical defaults are implementer choices, recorded in plan.
Ruling: Reuse current checkout and native Windows ledger/commands, no extra worktree — project environment already available and branch isolated — cost: no second filesystem checkout.
Preflight: semantic chunk identity -> staged vector generation; shared Gateway zero-output reservations -> Embedding/Rerank query and independent bounded build job; task/context policy -> server-selected search; old fields -> keyword/false defaults; eval uses authoritative evidence and no semantic quality claim. No conflicts identified.
Environment: Docker installed but daemon not running; 16 GB total/~3 GB free; no Embedding configuration. No Docker/model installation or real supplier requests authorized/needed for selected route. Only existing httpx is needed.
Tasks: 1 complete; 2 complete; 3 complete; 4 complete; 5 complete.

Task 1: complete — missing-module RED then 16 chunk/index/scope tests passed. AST/headings retain original excerpts and hashes; bounded overlapping windows and deterministic per-channel dedup RRF. Old index and evidence untouched.

Task 2: complete — missing HTTP module RED; 38 retrieval HTTP/aux-budget/original budget/gateway/model tests passed. No paid retry, shared semaphore across Gateways, strict vectors/ranking/response limits, safe error codes and scoped Milvus filters. HTTP contracts tested offline, real servers not accepted yet.

Task 3: complete — missing module RED; 51 retrieval/chunk/HTTP/budget/tool/graph regressions passed. Staged publication, strict config/generation and scope, fresh source verification and explicit failure. Test corrected one-batch assumption to no additional calls: fixture has 17 blocks so two size-limited batches are expected.

Task 4: complete — missing API/config and missing UI selector RED; 52 API/task/agent/graph regressions and all 36 browser tests green, plus provider-error-as-tool regression RED to GREEN. New index status, fixed task policy, idempotency/default compatibility, explicit form choice, inherited followup, lost-response retries and mobile layouts verified. Mobile screenshot inspected.

Task 5: complete — missing eval module RED then 3 evaluation tests green; five cases x three configs produced 15 synthetic rows, all quality pending. Deliberately reversed rerank is a negative control (Recall@5 .4 vs1.0); not a model-quality claim. Full suite 280 passed (277.88s), old235 retained, 36 browsers. compileall/pip check green; installed editable0.4.0; formal service startup/default keyword and unconfigured hybrid denial verified. Real Milvus/Embedding/Rerank intentionally not configured per user choice. Final fresh review pending.

Final review: one fresh-context gpt-6-astra high, base0a32cf4..c724a35, six Important/noCritical/threeMinor. UpsertCount bool/float regraded Important because false acknowledgements can publish a ready index; included in one fix pass. Other two minors deferred, no re-review.
Final: Ruling: Accept physically reordered Embedding rows only with validated unique complete index mapping — supplier protocol identifies input association by index, reviewer agrees to correct over-strict plan wording — cost: providers are trusted to label indices accurately; no claim of semantic embedding correctness.
Final: Ruling: Real service availability/latency/cost/semantic performance were declined by reviewer — follow user's explicit offline-first acceptance choice — cost: live acceptance remains required after configuration.
Final: Ruling: Remote failed-generation cleanup, multi-process coordination, external webpages and durable graph recovery remain outside this increment — single worker and generation isolation are explicit — cost: orphan vectors may use remote space and these future features are unavailable.
Final: minor (deferred): Auxiliary model events currently use investigation-level subtask_id, limiting per-subtask auxiliary tracing.
Final: minor (deferred): search_text tool description still says keyword although the server-fixed hybrid policy can also use vectors/rerank.
Final fixes: review-red.log initially11 failures. Chunk-cap fixture corrected to distinct headings; executing pre-fix git-show source yielded20004chunks/read both files (RED), current code stops within first file. Targeted review suite50 passed plus empty-scope positive boundary1 passed. Seven roots: persistent hybrid failure, lost-vector generation invalidation, bounded/preflight rerank, schema guard, failed-query accounting/config, streaming count/cancel, strict upload acknowledgement. Final full suite292 passed,273.96s;36browser regressions. compileall/pipcheck green; formal service restarted and startup/default keyword/accounted hybrid refusal verified.

Final: fixed persistent hybrid failure — test_hybrid_failure_cannot_be_hidden_by_valid_read_fallback RED→GREEN, suite292/292.
Final: fixed lost-vector invalidation and explicit retry — test_missing_remote_vectors_invalidate_generation_and_allow_explicit_retry RED→GREEN, suite292/292.
Final: fixed bounded source rerank and preflight — test_rerank_uses_bounded_source_windows_for_legacy_fts_spans + test_invalid_query_is_rejected_before_auxiliary_reservation RED→GREEN, suite292/292.
Final: fixed collection guard before paid embedding — test_incompatible_collection_rejected_before_embedding RED→GREEN, suite292/292.
Final: fixed failed query cost/reason/config export — test_failed_query_keeps_usage_reason_generation_and_rerank_model RED→GREEN, suite292/292.
Final: fixed streaming count/time/cancel — test_chunk_limit_stops_inside_first_file_without_reading_more + test_chunk_cancel_is_checked_during_generation RED→GREEN, suite292/292.
Final: fixed strict upload acknowledgement — test_malformed_upsert_ack_cannot_publish_success RED→GREEN, suite292/292.

Delivery: local codex/hybrid-retrieval retained as selected, no automatic merge/push. Source ZIP includes committed source and verification receipts; hash/integrity checks required. Real services remain unconfigured by user choice.
