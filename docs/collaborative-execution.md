# SDD ledger — plan: D:/code/Agent/docs/superpowers/plans/2026-11-12-collaborative-research.md

User approved 2026-11-12. Base f660040. Inline implementation; one independent final review. Branch feature/collaborative-research; current suitable checkout reused, no main merge or remote publish.
Preflight: BudgetManager/ModelGateway -> scoped tools/evidence -> LangGraph runner/review -> mode API/persistence -> workbench -> same-budget comparison. All old JSON gets defaults, old evidence IDs preserved. No new network tools or checkpoint/resume.
Ruling: Reuse current checkout on feature branch and use this ledger instead of Git/Bash helper scripts. Cost: no second filesystem checkout; preserve existing environment and unrelated files.
Tasks: 1 complete; 2 complete; 3 complete; 4 complete; 5 complete; 6 complete.

Task 1: complete — 25 budget/gateway/agent/provider/deadline tests passed after missing-module RED. LangGraph 1.2.20 + original pinned dependencies passed isolated smoke and pip check, identical exact lock installed. HTTP adapter clones per-run deadline, one gateway shares semaphore/atomic reservations; original single behavior retained.

Task 2: complete — scoped document/evidence/search and legacy/GitHub regressions passed after missing-module RED. Scope is fixed in ToolContext and SQL filtering precedes LIMIT; old citation IDs preserved through default normalization.

Task 3: complete — 36 graph/budget/gateway/agent tests passed. Real StateGraph Send/reducer fanout measured peak two, finite followup/no-new-evidence guards, graph step limit and reference checks verified. Additional RED→GREEN fixes pass dependency findings to dependent roles and reject model-forged review metadata in single mode. Ambient LangSmith tracing disabled for graph invocation.

Task 4: complete — 24 API/task/review regression tests passed, including mode idempotency, atomic terminal graph/report/usage and restart interruption without resume.

Task 5: complete — observed missing selector RED, then all 29 browser tests passed including cancel, retry, refresh and 320/390/736/1024 layouts. Desktop and mobile screenshots visually inspected.

Task 6: complete — comparison module missing RED then 6 tests green, ten paired synthetic reports with real fixture evidence and quality null, conflict partial. Full suite 221 passed (213.76s), compileall/pip check green. Formal service 0.3.0 startup/API/UI verified without a configured real model; no live model claims. API coverage extended to budget terminal and legacy reports (7 passed).

Final review: fresh-context gpt-6-astra high, base f660040..937c2b3. Eight Important, no Critical, two Minor. New-analysis mode persistence regraded Important: explicit single default and unexpected request scope/cost; RED then reset fixed. One fix pass, no re-review.
Final: Ruling: Missing docs/code in collaborative mode is always disclosed as partial, including code-only questions — conservative fixed-snapshot coverage rather than unreliable natural-language intent inference — cost: code-only collaborative tasks may be partial; single remains available.
Final: Ruling: Real model semantic quality and supplier live interoperability were declined by reviewer — keep unverified with no credentials/network model calls — cost: requires a later real-model acceptance run.
Final: Ruling: External webpages, Milvus and durable graph recovery were declined as future work — approved incremental scope stands — cost: these overall design goals remain unavailable in this delivery.
Final: minor (deferred): Running or undispatched subtask cards can show waiting; task terminal and event timeline remain authoritative.
Final fixes RED evidence: review-red.log (3 failures/1 compatibility pass); review-red-branches.log (2 failures); review-red-rest.log (7 failures). All 12 reproduced cases then targeted suite 59 passed. Roots: empty HTTP tools; abnormal usage latch; branch isolation; presented-evidence-only review; missing scope; final evidence/worker atomic failure; failed tool evidence; pre-provider cancellation; explicit new-analysis default. Final full suite 235 passed, 201.17s; 30 browser tests. compileall src and pip check passed; formal service restarted and fresh-page default verified.

Final: fixed empty HTTP tools — test_adapter_omits_tool_fields_when_no_tools RED→GREEN, suite 235/235.
Final: fixed abnormal usage latch — test_abnormal_provider_usage_latches_stop_after_other_reservation_releases RED→GREEN, suite 235/235.
Final: fixed branch isolation — test_unexpected_branch_exception_preserves_completed_other_branch RED→GREEN, suite 235/235.
Final: fixed presented review evidence — test_reviewer_cannot_support_claims_without_presented_evidence RED→GREEN, suite 235/235.
Final: fixed missing documents — test_missing_documents_is_reported_even_when_planner_omits_docs RED→GREEN, suite 235/235.
Final: fixed final reference and worker terminal — test_final_reference_recheck_keeps_partial_terminal_atomic + test_unexpected_worker_error_updates_graph_report_and_usage_atomically RED→GREEN, suite 235/235.
Final: fixed failed tool evidence — test_failed_search_cannot_contribute_unpresented_evidence RED→GREEN, suite 235/235.
Final: fixed cancel before provider — test_cancel_during_started_event_does_not_enter_provider RED→GREEN, suite 235/235.
Final: fixed new analysis default — test_explicit_new_analysis_resets_default_mode RED→GREEN, suite 235/235.

Delivery: local feature/collaborative-research retained as approved; no merge or remote publish requested for this increment. Source package will include committed files and selected verification receipts, hash verified.
