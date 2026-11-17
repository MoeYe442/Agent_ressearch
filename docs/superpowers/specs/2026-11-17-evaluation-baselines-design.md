# Evaluation baselines

User chose: implement direct answers without retrieval, context compression, and comparison statistics.

Use existing model gateway, budgets, durable execution and frozen evaluation artifacts. No new dependencies. AGENT.md requires compilation, not tests; no service, evaluation or provider runs in this delivery.

Approaches: a model-generated summary adds cost and factual drift; deterministic tool-history reduction is the initial implementation choice. Keep the two newest tool responses intact; above 32 KiB shorten older response data while retaining all top-level evidence IDs, status and errors, and leave tool-call pairing intact. Full results stay in existing durable tool storage and can be reread. This is lossy excerpt compression, not semantic summarization or long-term memory. Its rules are versioned and fixed across compared tasks.

Direct mode sends only the question and repository source/commit identity, never file contents, documents, tool definitions or retrieval output. It shares model/time/token limits, stores durable model responses and rejects unexpected tool calls. Claims have no citations and remain unverified. Execution success means structured answer production only. Independent human answer correctness is separate from evidence-backed quality; direct mode cannot pass the latter.

Compression is opt-in per task and defaults off. It belongs to task idempotency and recovery configuration, propagates through collaborative investigations, and emits byte-reduction counters without pretending bytes are tokens. Compare matching case/repeat slots within one frozen plan; include failures, expose missing results, require complete known usage for savings, and human-approved rubric and completed judgments for correctness/coverage. No measured gain is claimed before actual runs.

Existing source annotations remain drafts. Existing plans retain default-off semantics. Preserve local .gitignore and AGENT.md edits. Work on a new codex branch in the current checkout as in prior deliveries.
