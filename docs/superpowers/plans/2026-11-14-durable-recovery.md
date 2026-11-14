# Durable Task Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, test-first, one fresh-context final whole-branch review.

**Goal:** 交付 V3 的本地持久恢复增量：进程中断后显式恢复同一调查，复用已保存调用/工具/节点结果，保留预算与审计，旧 worker 不能覆盖新执行状态。

**Architecture:** SQLite 继续为任务权威；官方 LangGraph SqliteSaver 保存实际图 checkpoint/pending writes。数据库租约与执行代号隔离旧 worker；模型和工具 journal 在图重放时复用结果；预算独立持久化，不把锁、客户端、密钥写入图。服务停止与用户取消分开处理，恢复必须由用户显式触发。

**Tech Stack:** Existing Python3.12/FastAPI/SQLite/LangGraph1.2.20 plus langgraph-checkpoint-sqlite3.1.3, verified with unchanged locked dependencies in an isolated environment.

**Spec:** docs/RepoLens-Design-v1.md §9/10/12；用户本轮选择“进入 V3：任务持久化与中断恢复”。这是 V3 的独立端到端增量，不宣称 Redis/PostgreSQL/多进程队列/网页采集已交付。

## Global Constraints and design

- 基线296778b，分支codex/durable-recovery；沿用干净checkout。本地提交，不自动合并/推送，不启动Docker或调用真实模型。
- 新调查支持single与collaborative持久执行；旧无checkpoint任务沿用interrupted失败语义，不伪造可恢复状态。已取消、已成功、预算耗尽、配置不匹配或损坏的任务不能恢复。
- 只恢复中断、具有有效checkpoint的partial任务；同一task/snapshot/模型与工具配置，attempt/执行代号递增，预算不增加。waiting_input/修改问题后续再做。
- 保留总30模型/30工具/60,000tokens/900s、子任务8工具上限和两路并发。900s采用首次执行开始的绝对截止时间，停机/等待恢复也占用，不通过重启延长。过期只能新建独立调查，不能继续原任务。
- LLM/Embedding/Rerank计入同一持久预算。响应与结算同事务保存；未结算请求保留预留和estimated，恢复可能重复供应商费用但不会忘记旧用量。不会声称外部请求exactly-once。
- 复用成功保存的model/tool结果，重放不增加用量；工具结果重新核验快照/证据。未保存只读工具可至少一次执行，次数继续累计。
- 使用官方SqliteSaver数据结构，sync durability；fenced cursor在同一SQLite事务中检查租约。thread_id由服务端task ID生成，不开放任意checkpoint上传、反序列化、metadata过滤或时间旅行接口；禁用pickle fallback。
- 单worker全局租约、心跳、递增epoch；另一服务实例租约有效时不能接管，过期后可接管。所有任务/图/报告/预算/journal/checkpoint权威写入均检查当前租约和执行epoch。证据内容仍由不可变快照/hash验证。
- API密钥与服务客户端不持久化；只保存去密配置指纹，配置变更拒绝恢复。终态/报告/图/usage继续原子提交；SSE序号连续不重置。
- API/页面不会把重放、估算、部分结果或脚本模型标为真实质量成功。恢复次数与事件公开，页面刷新或双击恢复不重复排队。

## Review Focus

1. 崩溃位于provider前/返回后/结算前/工具后/Send分支间/终态事务前时，已保存结果不重复收费，未知请求保留旧预留，节点与报告不丢失。Task2/3/5。
2. 新服务接管后旧worker的迟到响应、心跳、事件、预算、checkpoint、终态不能覆盖当前epoch。Task1/3。
3. resume重复提交、取消竞争、过期/已耗预算/配置或snapshot改变不得重置预算或创建新事实。Task1/2/4。
4. 旧JSON、无checkpoint、损坏journal和恢复中服务故障明确失败；不读任意路径、秘密配置或不可信反序列化对象。Task1/3/4。
5. single、协作并行、hybrid辅助模型共享同一恢复账本；重放工具证据复核、调用顺序和SSE不能伪称重新执行。Task2/3/4。

## Files and contracts

| File | Responsibility |
|---|---|
| execution_store.py | 全局worker租约、执行epoch检查、budget/model/tool journal与配置指纹 |
| checkpoints.py | 官方SqliteSaver的fenced事务入口、只读检查与checkpoint生命周期 |
| budget.py/model_gateway.py | 恢复持久用量/绝对deadline、缓存调用、未知费用和两路并发 |
| agent.py/tools.py/retrieval.py | 稳定tool key、已保存结果重放、辅助调用的稳定payload key |
| orchestration.py/single_graph.py | 实际checkpointer与sync stream，None恢复/最终结果恢复 |
| storage.py/tasks.py/api.py/models.py | fenced权威事务、启动恢复标记、显式幂等resume与状态 |
| static/workspace.js/templates/workspace.html | 可恢复提示、按钮与恢复事件/轮次、重试与移动端 |

### Task 1: Fenced persistence primitives and official checkpointer

- [ ] 写tests/test_execution_store.py、tests/test_checkpoints.py，先观察缺模块RED；验证有效租约拒绝第二worker、过期接管、epoch拒绝旧写入、配置指纹不含秘密、checkpoint与pending writes真实恢复。
- [ ] 在隔离环境验证官方3.1.3与现锁兼容，pip check；安装相同锁到项目。SqliteSaver原表结构不另造checkpoint格式。
- [ ] 实现WorkerLease、ExecutionSession、FencedSqliteSaver；BEGIN IMMEDIATE内校验租约/epoch并写入，损坏或不匹配不恢复。
- [ ] 对应测试通过后提交。

### Task 2: Durable budgets and provider/tool replay

- [ ] 写tests/test_recovery_budget.py、tests/test_recovery_gateway.py，先RED；覆盖实际/未知请求、恢复不重置总量/子任务计数/stop_reason/deadline，成功和失败响应缓存、辅助模型缓存，已缓存重放不增量。
- [ ] BudgetManager接受可选session，原直接调用兼容；模型cache key来自固定role/subtask/payload/retry/config，响应与结算原子保存。未完成请求在恢复时转unknown但保留计数/预留。
- [ ] Agent工具cache使用固定model tool-call ID/参数/角色，返回前复核证据；重放事件与新执行事件区分，保存的工具结果不再次计数。
- [ ] 新测试与原预算/gateway/Agent/检索回归通过后提交。

### Task 3: Real graph recovery and fenced worker lifecycle

- [ ] 写tests/test_task_recovery.py、tests/test_graph_recovery.py，先RED。覆盖single中途与graph分支间中断、模型响应已保存但节点未完成、graph结束但任务终态未提交，以及service stop与用户cancel的差异。
- [ ] 为single提供实际StateGraph外壳；协作图使用同一session/checkpointer，sync durability，恢复传None，已完成checkpoint不重新规划。读取保存的完整结果完成崩溃终态窗口。
- [ ] 服务取得租约后分类旧running；有有效持久执行的中断变partial+resume_available，旧无checkpoint维持failed/interrupted。只显式resume排队，不自动产生新费用。
- [ ] heartbeat失去租约后停止，旧响应只能被拒绝；原子终态与预算保持一致。API请求、进程停止都排空已发调用或保留未知预留。
- [ ] 新图/任务/旧兼容回归通过后提交。

### Task 4: API and recovery workbench

- [ ] 写tests/test_recovery_api.py、tests/browser/test_recovery_workspace.py，先RED；重复resume、旧key重试、状态冲突、cancel竞争、过期/配置变更拒绝、刷新/SSE补发和320/390/736/1024无溢出。
- [ ] POST/tasks/{id}/resume只恢复有效partial，同任务预算/快照/策略、attempt递增。相同resume意图幂等，不重复worker执行；旧无checkpoint可返回404，状态冲突409。
- [ ] 新任务字段默认兼容：attempt、execution_epoch、resume_available、recovery_error；页面仅对可恢复partial展示恢复，明确剩余额度/绝对时限和未知请求可能重复费用。
- [ ] 全API/浏览器回归通过后提交。

### Task 5: Process crash injection, audit and delivery

- [ ] tests/test_recovery_process.py使用真实子进程在固定边界退出/接管，统计脚本供应商调用，验证已保存结果不重复、pending writes、预算/fencing/取消/终态和事件。无真实供应商调用。
- [ ] 记录故障位置、恢复与重复调用/估算结果，不将恢复率当质量。保留失败分母，包含过期与版本不匹配负向用例。
- [ ] 更新README、配置/锁、版本、恢复边界与验收说明；真实模型仍未配置，不宣称实测费用或exactly-once。
- [ ] pytest全量、compileall src、pip check；原292项回归保留。一次fresh-context全分支审查，重要修复RED→GREEN后再全量验证。
- [ ] 正式默认服务启动/兼容检查、源码ZIP与hash校验、本地提交保留分支；不自动推送，不改网络/容器配置。

## Official references

- https://docs.langchain.com/oss/python/langgraph/persistence
- https://reference.langchain.com/python/langgraph/checkpoints/
- https://reference.langchain.com/python/langgraph.checkpoint.sqlite
- https://pypi.org/project/langgraph-checkpoint-sqlite/
