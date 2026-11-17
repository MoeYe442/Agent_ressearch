# Deployment Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans, inline implementation and one fresh static final review.

**Goal:** Produce safe repeatable offline configuration diagnostics and concrete deployment acceptance steps.
**Architecture:** A standalone CLI imports Settings and diagnostic dependencies only; no app/database/worker construction. Pure report builder returns fixed-code redacted checks, CLI controls requirements and presentation.
**Tech Stack:** Python stdlib, existing Pydantic/psycopg/Redis parsers, no new dependencies.
**Spec:** docs/superpowers/specs/2026-11-17-deployment-preflight-design.md.

## Global Constraints
- Compile/static checks only; actual local configuration inventory is read-only and offline.
- No service/provider connections, secrets output, .env loading, database/business-data creation, tests, containers or benchmarks.
- Preserve original .gitignore and AGENT.md; no automatic push/merge.

## Review Focus
- Invalid settings/DSN/URL values must never appear in output or tracebacks.
- Optional versus required and implied feature statuses must not falsely claim deployment readiness.
- Native settings must not be confused with Compose .env/container settings.
- Read-only path/dependency/parser checks must never instantiate app/storage/clients.
- Missing/invalid configuration exits nonzero; reports always state runtime not verified.

### Task 1: Offline diagnostics
Files: new src/repolens/preflight.py.
Interfaces: inspect_configuration(settings,required)->dict with fixed safe checks; main()->exit code 0/1/2, JSON or readable text.
- [x] Implement dependency/path/model/storage/retrieval/document/renderer checks, optional requirements and implication rules.
- [x] Implement CLI with exception redaction, default model requirement and tools-only mode.
- [x] Compile and inspect call graph for no network/storage constructors.

### Task 2: Deployment preparation delivery
Files: docs/deployment-preflight.md, README.md, version files, compile/operational receipts and execution ledger.
- [x] Document native/Compose config distinction and concrete staged runtime acceptance, without running it.
- [x] Run offline inventory in the actual process environment; store only redacted operational result outside git.
- [x] Compile Python/Jinja/schema/catalog, check JS/dependencies/Compose configuration, no tests/services.
- [x] One fresh static review, fix Important findings once, compile, commit locally.
