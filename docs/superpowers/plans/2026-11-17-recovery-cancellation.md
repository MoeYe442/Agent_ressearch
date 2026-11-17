# Recovery Cancellation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for this bounded bugfix, including one fresh static review.

**Goal:** Allow the UI to cancel recoverable interrupted tasks while preserving their saved partial report.
**Architecture:** Reuse the existing cancel API and atomic backend transition. Share a frontend cancellation predicate and per-task action lock; preserve the saved AnalysisResult on cancellation, falling back to the saved graph only when no report exists.
**Tech Stack:** Existing Python/FastAPI and native JavaScript.
**Spec:** Existing deferred UI cancellation finding in docs/durable-execution.md and backend cancellation contract in docs/RepoLens-Design-v1.md; this plan defines the bounded fix.

## Global Constraints
- AGENT.md: compile only, no tests, services, browser or model execution.
- Keep cancellation idempotent and preserve authoritative task/graph/report transaction.
- Preserve user .gitignore and AGENT.md; leave branch local.

## Review Focus
- Ordinary terminal tasks cannot be cancelled; resumable partial tasks can.
- Pending cancel/resume actions exclude duplicate/conflicting UI actions, including across polls.
- Cancellation retains claims, evidence, role usage and compression counters; status/usage remain aligned.
- Task changes during a request must not receive another task's UI updates.
- Missing-report fallback and repeated cancellation must not introduce model/tool calls.

### Task 1: Correct cancellation and deliver
Files: tasks.py, static/workspace.js, version files, docs/recovery-cancellation.md, docs/results/recovery-cancellation-compile.json.
- [x] Trace root causes: terminal-status-only button condition; partial cancel rebuilt report without prior findings.
- [x] Add shared cancellation predicate and per-task action lock; explicitly refresh terminal report after cancel.
- [x] Preserve saved report fields and update cancellation status/usage atomically; fallback reads existing graph only.
- [ ] Compile Python/Jinja, JS syntax, schema/catalog, pip and Compose configuration; no runtime verification.
- [ ] One independent static review, one important-fix pass if needed, compile and commit locally.
