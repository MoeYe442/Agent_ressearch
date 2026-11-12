# Configurable Hybrid Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, test-first, with one fresh-context whole-branch review.

**Goal:** 补齐 V2 可配置 Milvus 向量召回、关键词/符号融合和可选重排，提供离线 HTTP 契约回归及可重跑检索比较；真实服务配置后另行验收。

**Architecture:** SQLite 继续保存权威快照、原文块和索引状态；Milvus 仅保存可重建向量及块 ID。显式向量索引任务在现有单 worker 内运行；查询按固定 snapshot/index generation/scope 过滤，融合符号、FTS5、向量候选，按需远端重排，再从本地快照验证原文。默认 keyword 不调用新增模型。

**Tech Stack:** Python 3.12/FastAPI/SQLite/httpx；Milvus 2.6 REST v2，float Embeddings 与 index/relevance_score Rerank HTTP 协议，不新增大型 SDK 或本地模型依赖。

**Spec:** docs/RepoLens-Design-v1.md §6/7/11/12。用户在本轮明确选择“先实现可配置接入与离线回归，真实服务配置后验收”。

## Scope and design decisions

- 两条可行路线为立即启动本机服务，或先实现可配置接入与离线回归。用户选择后者。Docker daemon 当前未运行，空闲物理内存约 3 GB，无 Embedding 配置；本轮不启动 Docker、不下载模型、不发真实供应商请求。
- 沿用干净 checkout，在 codex/hybrid-retrieval 分支执行；基线 0a32cf4。本地提交，不自动合并或推送。
- 默认 keyword；hybrid 与 rerank 均显式选择，追问继承。未配置或索引未就绪返回明确错误，不静默冒充向量检索。
- 新 HTTP 端点只来自本机配置，模型和请求正文不能指定服务 URL/密钥；HTTP 禁止 redirect、禁用环境代理，远端 HTTPS 或本机回环 HTTP，响应有大小/超时上限，错误不含上游正文。
- 查询 Embedding/Rerank 与 LLM 共用 30 次模型调用、60,000 输入/输出 token、900s 和两路并发上限；角色用量拆分记录。向量建库拥有独立但同上限的显式预算，失败/未知用量保守估计，不自动重试付费请求。
- 语义块以 Python AST 位置、Markdown 标题和有重叠行窗口产生，单块不超过 120 行或 8,000 UTF-8 字节；超长单行明确报错，不截断后冒充完整证据。保存 chunker_version、原文 hash、父符号、source_scope。旧 FTS 和 evidence ID 不迁移、不改写。
- 每通道最多20候选，RRF(k=60)融合并去重，重排最多20份原文；返回条数受工具原上限20约束。所有候选最终在本地验证，Milvus 返回的 path/line 不作为权威。
- 索引只有全部上传成功才发布 ready；失败 generation 不可检索。幂等重试不重新付费，失败后需新的显式 attempt；重启 queued/building 标记 interrupted，不伪称恢复。
- 不接外部网页、持久图恢复或新消息队列。本轮不宣称真实检索质量提升。

## Review Focus

1. 不同快照、generation、模型/维度和代码/文档 scope 不得混检；供应商伪造块 ID 不能越界。Task 1/3。
2. 失败建库、重复提交、重启、服务不可达不能留下看似 ready 的索引或自动重发付费调用。Task 2/3/4。
3. 查询辅助模型不得绕过共享预算、并发和取消；缺 usage、超预留、超时仍如实结算。Task 2/3。
4. Embedding 索引缺失/重复/越界或无法唯一对应、NaN、错误维度、重复/越界重排位置、超大响应和 redirect 必须拒绝；合法乱序按唯一 index 还原输入顺序，错误不泄露 key/body。Task 2。此处按最终审查共识修正了“物理错序一律拒绝”的过严条款。
5. 旧 task/intent/idempotency 默认 keyword；刷新和重试保留检索选项；降级/未知质量不得包装为 hybrid 成功。Task 4/5。

## Interfaces and files

| File | Responsibility |
|---|---|
| retrieval_chunks.py | 只从受控 EvidenceStore 读取的带版本、行号/hash 语义块 |
| retrieval_http.py | 有界 HTTP、Embedding/Rerank、Milvus REST 合同 |
| retrieval.py | generation 构建/状态/持久块、RRF、检索与引用复核 |
| budget.py/model_gateway.py | 零输出辅助模型预留，共享信号量、结算与角色统计 |
| models.py/config.py/tasks.py/api.py/tools.py/agent.py | 检索配置、幂等 worker、工具和 API 连接 |
| static/workspace.js/templates/workspace.html | 检索模式、索引状态、重排选项与持久 intent |
| eval/retrieval.py/eval/retrieval_tasks.jsonl | 同快照关键词/混合/重排比较与 Recall@K，质量待人工 |

### Task 1: Immutable semantic chunks and deterministic fusion

Interfaces: `chunk_snapshot(snapshot_id, store) -> list[dict]`; `fuse_rankings(rankings, limit=20) -> list[SearchHit]`. 块标识包含 index generation 时由建库层派生；此层身份为 snapshot/path/range/hash/chunker version。

- [ ] 写失败测试：AST 父符号、Markdown 标题、语法错误回退、UTF-8/行窗口上限、重叠、快照/原文 hash、稳定去重和通道乱序下确定性融合。
- [ ] 运行 tests/test_retrieval_chunks.py，观察缺模块 RED。
- [ ] 实现块生成与 RRF，不改变旧索引/证据；相关回归通过后提交。

### Task 2: Budgeted HTTP model and Milvus contracts

Interfaces: `EmbeddingClient.embed(texts, deadline) -> (vectors, ModelUsage|None)`；`RerankClient.rank(query, texts, deadline) -> (indices, usage)`；`MilvusStore.ensure/upsert/search`；`ModelGateway.external(call, input_bound, role, subtask_id)` 共用现有预算。

- [ ] 写 MockTransport 失败测试覆盖 Review Focus 3/4、授权不跨 redirect、错误脱敏、索引维度/字段及过滤条件。测试替身仅在 tests。
- [ ] 运行 tests/test_retrieval_http.py tests/test_retrieval_budget.py 观察 RED。
- [ ] 实现配置校验、响应流限制、协议严格校验、无自动付费重试的辅助调用。供应商实际异常用量锁存，未发送取消释放预留；峰值两路。
- [ ] 运行新测试与原预算/网关/模型回归，通过后提交。

### Task 3: Staged vector indexing and snapshot-scoped retrieval

Interfaces: `RetrievalService(settings, db, ...clients)`；`register/build/status/search`，search 收到服务端固定 ToolContext 和共享 ModelGateway。索引元数据含 manifest、Embedding 模型/维度、chunker_version 与 generation，SQLite 原子发布。

- [ ] 写失败测试：真实 fixture 的关键词/符号/向量融合、可选重排、跨快照/旧 generation/伪造块拒绝、scope 在服务端过滤、staged upload 失败不可 ready、幂等和 restart interruption。
- [ ] 运行 tests/test_retrieval.py 观察 RED。
- [ ] 实现建库与查询，所有命中从权威块和 EvidenceStore 读取并复核，不以 Milvus 元数据制造引用。任何辅助服务故障使本次工具显式失败，不丢现有任务轨迹。
- [ ] 原工具/文档/图回归和新测试通过后提交。

### Task 4: API, task policy and workbench

Interfaces: `POST /repositories/{id}/retrieval-index` 显式登记，`GET` 状态；`POST /repositories/{id}/search` 显式带预算试检索；POST /tasks 增加 `retrieval_mode='keyword'`、`rerank=false`，指纹包括二者。ToolContext 固定模式；检索设置持久化到 task，旧字段默认兼容。

- [ ] 写失败 API/浏览器测试：未配置/未就绪明确拒绝，索引重试不重复付费，旧请求 keyword、跨检索选项幂等冲突、协作与追问继承、模式锁定、失联重试、刷新、移动端无横向溢出。
- [ ] 运行新测试观察 RED，再接现有 worker/ToolRegistry/Gateway；不增加工具自行选择 URL/配置能力。
- [ ] 工作台只有用户显式选择 hybrid 才登记向量索引；展示建库会将源码发往配置的 Embedding 服务，健康检查仅报告配置布尔值。
- [ ] 全部 API/工具/预算/浏览器回归通过后提交。

### Task 5: Reproducible comparison and delivery

- [ ] 写 tests/test_retrieval_eval.py 并观察 RED。三种配置复用同一快照、固定任务与标注；记录检索列表、模型/块版本、失败、usage、延迟、Recall@K；所有失败保留分母，quality_pass=null，不用脚本向量制造语义提升。
- [ ] 实现 `python -m eval.retrieval --base-url URL --tasks eval/retrieval_tasks.jsonl --output PATH`；离线 HTTP 集成演示输出 synthetic=true，错误语义/伪引用负向用例保留。
- [ ] README、环境配置、Milvus 2.6 参考部署/验收说明、版本锁及本轮限制更新；不启动当前 Docker 或下载模型。
- [ ] 全量 pytest、compileall src、pip check；原235项全部保留。一次 fresh-context 独立全分支审查；重要修复 RED→GREEN，再全量验证。
- [ ] 本地提交、源码 ZIP/manifest/hash 验证，保留分支不自动推送；正式默认 keyword 启动验证，明确真实 Milvus/Embedding/Rerank 未配置验收。

## Official references

- https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Create.md
- https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Describe.md
- https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md
- https://milvus.io/docs/v2.6.x/upsert-entities.md
- https://milvus.io/docs/v2.6.x/prerequisite-docker.md
- https://github.com/siliconflow-inc/siliconflow-api/blob/main/openapi.yaml
