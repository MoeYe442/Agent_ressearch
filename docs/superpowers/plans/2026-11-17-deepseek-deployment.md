# DeepSeek Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline work and one final fresh static review.

**Goal:** Configure DeepSeek's supported non-thinking tool mode and deploy isolated baseline services without paid calls until a local key exists.
**Architecture:** Add an explicit provider thinking toggle (default unchanged); pass disabled only when configured. Mirror the setting in native/Compose configuration and preflight. Deploy PostgreSQL/Redis/API/worker using a newly named local Compose project, generated local DB password, unused loopback port/subnet, no existing data reuse.
**Tech Stack:** Existing Chat Completions HTTP adapter, Settings, Docker Compose.
**Spec:** User selected DeepSeek and maximum10CNY for this run; main plan and official docs https://api-docs.deepseek.com/guides/tool_calls/ and https://api-docs.deepseek.com/guides/thinking_mode/ (read2026-11-17). Official current model deepseek-flash, base https://api.deepseek.com, thinking disabled for existing tool history representation.

## Global Constraints
- AGENT.md: compile, no tests; now also commit code to GitHub after completion.
- Actual deployment/read-only health inspection is requested operational work, not a test suite. No paid calls while key absent; total user-approved model spend ceiling10CNY, never a full benchmark.
- Never print/store local secrets in git; .env exclusive creation only, no old data/containers/volumes removal.
- No Milvus/browser/rerank startup in this baseline resource-limited deployment.

## Review Focus
- Other providers retain identical payload by default; explicit disabled is fingerprinted and sent identically across native/container.
- DeepSeek required non-thinking configuration is clear before paid tool calls.
- Local secrets never reach stdout, docs, git or image context.
- Operational status separates service health from model acceptance and documents missing key.
- Isolated project/port/subnet and shared state paths do not affect existing services/data.

### Task 1: DeepSeek configuration
Files: config.py, model_client.py, preflight.py, compose.yaml, .env.example; docs/deepseek-deployment.md.
- [ ] Add provider_default/disabled model_thinking flag, environment loading and optional request field.
- [ ] Guard official DeepSeek configuration with preflight compatibility diagnostic, preserve other-provider defaults and existing fingerprint coverage.
- [ ] Compile and document current official endpoint/model/date and local-key setup.

### Task 2: Local deployment and delivery
Files: ignored .env/operational receipts, compile receipt, execution ledger.
- [ ] Start installed Docker Desktop hidden, create isolated local config with generated PostgreSQL secret and empty model key.
- [ ] Build/start baseline services, inspect statuses and read-only health/preflight only; no tests or task submissions.
- [ ] One fresh static review; fix Important issues once; compile.
- [ ] Commit and push current branch per updated AGENT.md, verify remote SHA; report precise runtime/credential limitations.
