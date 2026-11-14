# V3 独立 worker 与 PostgreSQL Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. 用户 AGENT.md 优先：完成后编译，不运行测试。

**Goal:** 交付可配置 PostgreSQL、独立 API/worker、Redis 唤醒和 Docker Compose，保留 SQLite 内嵌模式。

**Architecture:** 数据库是唯一事实源；持久派发表与提交同事务保存，Redis 仅唤醒，丢通知时轮询数据库。单活 worker 的递增租约继续隔离旧进程。PostgreSQL 使用事务 advisory lock 序列化短状态事务、官方 PostgresSaver 保存原生检查点。

**Tech Stack:** Python/FastAPI/LangGraph、psycopg、Redis、PostgreSQL、Docker Compose。

**Spec:** docs/RepoLens-Design-v1.md §9/10/12；本次用户选择“独立 worker、Redis、PostgreSQL、Docker Compose”。

## Global Constraints

- 不运行测试，不调用真实模型。只进行编译、依赖一致性和静态配置检查；不能声称运行验收通过。
- 保留 SQLite 默认模式、既有任务与证据接口；保持一台 worker 单活，不实现横向并行 worker。
- API 负责提交、取消、恢复，不能取得 worker 租约或中断在途任务。
- 不复位预算、不自动恢复已中断调查；保留未知费用和原截止时间。
- 原有用户改动 .gitignore、AGENT.md 保留，不纳入本轮提交。
- 不推送、不合并，不引入网页采集/MCP。

## Tasks

- [ ] 1. PostgreSQL 存储与全文索引，复用事务/领域接口。
- [ ] 2. 官方 PostgresSaver + 同事务 fencing；配置与运行角色。
- [ ] 3. 持久派发表/Redis 唤醒、API-worker 分离、并发请求原子性。
- [ ] 4. Docker/Compose、历史数据迁移 CLI 与操作说明。
- [ ] 5. 编译、依赖检查、一次只读全分支审查、修复、提交。

## Review Focus

1. API/worker 并发取消、恢复和幂等提交的读改写原子性；事件序号与报告一致。
2. 提交后 Redis 丢通知/重复通知/不可用/worker 崩溃时，派发表不能丢任务或自动重启中断调查。
3. PostgreSQL 普通事务与官方 saver 的租约检查、写锁、精度和旧 worker 拒写。
4. SQLite 兼容、PostgreSQL 全文查询/占位符/UPSERT、迁移拒绝未完成任务且不覆盖旧库。
5. 容器共享路径、模型密钥、环回发布、可信客户端网段和严格反序列化；部署说明不得冒充实测。
