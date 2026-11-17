# Evaluation Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close documented direct-answer diagnostics and malformed evaluation artifact gaps.
**Architecture:** Correct the producer's failure limitation order; validate artifact structure at read boundaries before field access, hashing identifiers, or aggregation. Invalid individual results retain their planned denominator slot; invalid shared context/preparations or review packets fail closed with a controlled validation error.
**Tech Stack:** Existing Python, no new dependencies.
**Spec:** This plan's following constraints and contracts define this bounded bugfix increment; sources are the deferred findings in docs/evaluation-baselines-execution.md and docs/v4-execution.md.

## Global Constraints
- AGENT.md: compile, no tests. No benchmark, provider or service runs.
- Preserve user's .gitignore and AGENT.md; keep changes on local codex branch until explicit push.
- No fabricated runtime acceptance; no alteration of evidence or quality criteria.

## Review Focus
- Provider/JSON/invented-citation failures must expose their actionable code while retaining the unverified disclaimer.
- Checksum-valid non-object result/task/snapshot/report/evidence fields must not raise AttributeError or corrupt known usage counts.
- Evidence/review IDs must be strings before dictionary/set use; malformed review groups must fail as invalid input.
- Malformed shared context/index/preparation must not produce misleading partial summaries or silently skip authority checks.
- Invalid single result stays in the planned denominator, and quality/cost totals stay unknown where appropriate.

### Task 1: Validation and diagnostics
Files: src/repolens/direct.py, benchmark/validation.py (new), benchmark/review.py, benchmark/report.py.
Interfaces: mapping(value,code)->dict; result_shape(record)->None; review_shape(review)->None. Boundary checks raise ValueError with stable codes.
- [ ] Prioritize actual direct failures before baseline disclaimer.
- [ ] Validate nested artifact shapes before field access; keep semantic checks in inspect_record/adjudicate.
- [ ] Compile Python and inspect all aggregate consumers.

### Task 2: Delivery
Files: docs/evaluation-hardening.md, docs/results/evaluation-hardening-compile.json, docs/evaluation-hardening-execution.md.
- [ ] Document invalid-row versus shared-input behavior and existing-record compatibility.
- [ ] Compile Python/templates, validate schemas/catalog, JS syntax, pip and Compose config; no tests.
- [ ] Obtain one fresh-context static review, fix important findings once, repeat compilation if changed.
- [ ] Commit locally without push, preserve user changes.
