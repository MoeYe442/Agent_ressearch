# Evaluation Baselines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add real direct-answer and deterministic context-compression baselines with auditable comparisons.
**Architecture:** Extend task configuration and the existing durable single graph; compress only tool history inside investigations; extend frozen benchmark configurations and manual review/reporting.
**Tech Stack:** Existing Python, Pydantic, LangGraph, FastAPI and JavaScript.
**Spec:** docs/superpowers/specs/2026-11-17-evaluation-baselines-design.md

## Global Constraints
- Compile/static checks only, no tests, service startup, benchmark execution or provider calls (AGENT.md).
- Defaults remain single/keyword/compression off; preserve user files; no automatic push/merge.
- Keep fixed denominators and unknown usage; draft/synthetic results publish no official quality rates.

## Review Focus
- Direct tasks must never invoke retrieval or consume attached documents, nor acquire evidence-backed status.
- Compression must retain tool protocol pairing, evidence IDs and error information, and remain bounded/replayable.
- Idempotency/recovery must bind compression and mode, including old default-off task records.
- Human direct-answer correctness must not imply citation accuracy or evidence-backed completion.
- Comparison data must expose unrun/invalid slots and never report unknown usage as zero or bytes as saved tokens.

### Task 1: Task execution baselines
Files: models.py, api.py, tasks.py, recovery.py, single_graph.py, agent.py, orchestration.py; new direct.py and context_compression.py.
Interfaces: task/context context_compression bool; context analysis_mode; result context_stats counters. DirectRunner.run matches AgentRunner.run and uses ModelGateway. compact_history(messages) returns messages and reduced response count.
- [x] Add and validate task configuration, idempotency and recovery binding.
- [x] Implement durable direct mode with empty tools and unverified, citation-free claims.
- [x] Implement bounded deterministic old-tool compaction and propagate counters through collaborative output.
- [x] Compile affected Python; inspect direct/recovery boundaries.

### Task 2: Evaluation and user controls
Files: benchmark/protocol.py, runner.py, review.py, report.py; new benchmark/comparisons.py; static/workspace.js, templates/workspace.html.
Interfaces: configuration tuples(mode,retrieval,rerank,compression); answer_pass and fact coverage human judgments; comparisons computed from same-plan rows.
- [x] Extend actual supported configurations with direct and paired compression variants.
- [x] Validate frozen task flags; permit citation-free direct review with separate correctness metric.
- [x] Compute descriptive matched comparisons with complete usage and explicit missingness, output in reports.
- [x] Expose mode/compression controls, preserve followup and reload configuration, mark direct reports unverified.
- [x] Compile Python and check JavaScript syntax.

### Task 3: Delivery
Files: docs/evaluation.md, docs/evaluation-baselines.md, README.md, version files, compile receipt and execution ledger.
- [x] Document protocol, limitations and actual configuration matrix; no fabricated measurements.
- [x] Run Python/Jinja compilation, JS syntax, dependency and Compose configuration checks, diff whitespace check.
- [x] Obtain one fresh-context static whole-branch review; fix important issues in one pass, compile again if changed.
- [x] Commit code/docs and leave branch local for user-requested push.
