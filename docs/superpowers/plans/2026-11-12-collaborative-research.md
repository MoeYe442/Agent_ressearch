# RepoLens Collaborative Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有单 Agent 基线上增加可选 LangGraph 协同调查，对同一仓库快照进行代码/文档分工、证据汇总、有限评审补查，并提供相同预算下的可复现比较。

**Architecture:** 保留旧 AgentRunner 作为默认 single 模式。collaborative 模式通过 LangGraph 执行 Planner → 并行 CodeReader / RepositoryResearcher → 合并 → Reviewer → 有限补查 → 确定性报告；所有节点使用同一份线程安全预算和固定 snapshot 权限。继续由现有单 worker 承接任务，SQLite 保存公开计划、子任务结果与事件，不实现跨进程图恢复。

**Tech Stack:** Python 3.12、现有 FastAPI/Pydantic/SQLite/HTTP 模型适配器，加 LangGraph StateGraph / Send / reducer。安装前先在临时依赖环境验证兼容组合，之后锁定精确版本及传递依赖，不默默升级现有核心包。

**Spec:** [总体设计](../../RepoLens-Design-v1.md) 第 3、5、6、8、11、12 节；[后续顺序](../../RepoLens-V1-Implementation-Plan.md)。本轮是“LangGraph 协同调研与文档证据”的第一个独立增量；Milvus 与其他后续组件依原顺序另立计划。

## Current State

- 起点：feature/github-import，提交 `f660040`，已推送；main 尚未合并该阶段。
- 已有 165 项测试、19 项浏览器测试，以及本地/GitHub 固定快照、受限工具、证据、持久任务和 SSE。
- AgentRunner 的 usage/预算目前是单次 run 内部变量，不能直接给并行子 Agent 各复制一份。
- HTTPChatModel.deadline 目前是实例可变属性，不能在并发角色之间反复覆盖。
- 仓库内文档已可全文检索，但证据尚未显式区分代码与文档；工具也没有角色检索范围。
- 当前环境未配置模型，GitHub 真实导入受非公网 DNS 结果阻塞。此轮仍可用本地固定 fixture 验收完整协同链路；不据此宣称真实模型收益。

## Scope Decisions for Review

1. 默认继续 single。用户在表单或 API 明确选择 collaborative；不让所有旧请求自动增加 Planner/Reviewer 调用成本。
2. 文档范围先限于同一不可变快照中**已纳入**的 Markdown、RST、TXT 与 README/LICENSE 等文本。原有排除项不自动回源补入旧快照，缺文档明确说明。
3. RepositoryResearcher 使用仓库内检索工具，不获得 fetch_document、任意网络、shell 或动态工具权限。外部官方网页、Issue/PR、MCP/动态网页属于后续资料接入增量。
4. Reporter 使用确定性模板汇总已验证引用的 claims、模型评审标签和局限，不增加一次自由写作调用，也不新增代码事实。
5. 模型 Reviewer 的“支持/矛盾/不足”是模型判断，不能覆盖程序引用校验或人工语义评分。冲突保留两侧有效证据，未解决则 partial。
6. 六个逻辑职责不等于六个模型。Executor 和 Reporter 不调用模型；最多两个调查角色同时请求模型，所有请求含 Planner/Reviewer/修正/重试均计入总预算。
7. 沿用此前方式：同一实现者依次实现，最终一次独立审查。确认后从 f660040 建立 feature/collaborative-research，本轮不自动合并 main 或发布远程。

## Global Constraints

- 兼容 165 项基线测试、旧快照、旧任务/报告与原 POST /tasks 请求；不删除用户数据。
- 单任务分析一个固定 snapshot，不能混用 commit；文档原文同样保留路径、行号和 hash。
- 首轮最多 4 个子任务；调查角色并发最多 2；每个子任务最多 8 次工具调用。
- 全局最多 30 次工具调用、30 次模型请求、60,000 输入/输出 token、15 分钟。这些是整张图共同上限，不按角色、分支、重试或补查重置。
- 每个模型响应最多执行 8 个工具请求；网络重试最多额外两次，结构化输出修正最多一次，全部扣同一预算。
- 模型调用前原子预留输入/输出额度，调用后按 usage 结算；缺失或失败的用量保守估算并保留 estimated，不能当零成本。实际 usage 异常超出预留时停止新调用并如实记录，不裁剪真实统计。
- Reviewer 最多触发 2 轮补查，每轮最多 2 项；无新证据、取消、预算耗尽、达到轮次或目标已满足时停止。
- LangGraph 的步数限制作为第二道保护，不能替代业务预算或补查轮数。max_concurrency 放在调用配置顶层，同时用模型网关信号量独立限制在途请求，测试必须测真实峰值。
- 状态 reducer 按子任务 ID 和结果内容 hash 合并，重复结果幂等；不同内容不能静默覆盖。并发分支不写共享可变 findings 列表。
- 仓库文本是数据，不得改变图节点、工具注册表、系统提示词或网络权限。不存储/展示模型私有推理链。
- 不引入 Redis、Milvus、额外 worker、长期记忆或 checkpointer。进程退出仍是 failed/interrupted；不新增 resume 接口、不冒称 LangGraph 接入即具备持久恢复。
- 保留 HTTPS、路径、secret 排除、ZIP、证据 hash 等既有约束；本轮不放宽 DNS 保护或修改用户网络。
- 没有真实凭据时只交付明确 synthetic 的功能比较，人工质量值待审；不编造多 Agent 提升比例、金额或性能结论。

## Review Focus

1. 两个并发分支同时预留最后一点额度、失败重试或取消时，不得绕过总预算，也不得遗漏已发请求的用量；Task 1、3 覆盖。
2. 伪造子任务 ID、依赖循环、跨 scope/快照引用及 README 中的工具指令不得改变实际权限；Task 2、3 覆盖。
3. 重复/乱序节点结果和 Reviewer 再补查不得覆盖有效结果、无限循环或制造未经观察的引用；Task 3 覆盖。
4. 旧 Markdown 引用 ID、旧 JSON、模式不同但幂等键相同，以及刷新/SSE 重连必须兼容且不重复付费任务；Task 2、4、5 覆盖。
5. 文档缺失、代码与文档冲突、部分分支失败、模型未配置或图异常时，不把不完整结论包装成质量成功；Task 3、4、6 覆盖。

## File Structure and Contracts

| 文件 | 职责 |
|---|---|
| src/repolens/budget.py | 全局原子预算、预留/结算、子任务工具额度、截止时间与用量快照 |
| src/repolens/model_gateway.py | 带角色上下文的预算化模型入口、并发信号量、重试与 deadline 传播 |
| src/repolens/model_client.py、agent.py | 无并发 deadline 覆盖；旧 single 与子任务循环共用预算入口 |
| src/repolens/document_scope.py | 文档类型分类及固定的 all/code/docs 范围规则 |
| src/repolens/models.py、tools.py、indexing.py、evidence.py | 范围检索、证据类型、旧引用兼容与结构契约 |
| src/repolens/orchestration.py | LangGraph 组装、路由、并行派发、reducer、有限补查和终态 |
| src/repolens/review.py | 程序引用复核、模型评审结构校验、冲突/缺口归并 |
| src/repolens/tasks.py、api.py、storage.py | mode、计划/子任务/评审持久化、图详情接口与事件 |
| templates/workspace.html、static/workspace.js、workspace.css | 分析模式、分工/补查/引用视图与状态恢复 |
| tests/test_budget.py、test_model_gateway.py、test_document_scope.py、test_orchestration.py、test_collaborative_api.py | 并发、安全、兼容、图边界与失败回归 |
| tests/browser/test_collaborative_workspace.py | 协同表单、任务分工、冲突证据、刷新/取消与窄屏 |
| eval/compare.py、eval/collaborative_tasks.jsonl、docs/collaborative-research.md | 同预算比较、人工标准、实测边界与启动配置 |

### Task 1: 全局预算与并发安全模型入口

**Interfaces:** `BudgetManager(settings, deadline)`；`reserve_model(input_bound, output_limit, role, subtask_id) -> Reservation`、`settle_model(reservation_id, usage_or_none, failed=False)`、`reserve_tool(subtask_id)`、`snapshot() -> Usage`。`ModelGateway.complete(messages, tools, role, subtask_id, cancelled) -> ModelTurn` 使用同一个 BudgetManager；不能新建角色级总额度。AgentRunner.run 增加可选的共享预算/角色参数，原调用签名仍可用。

- [ ] 在隔离的 `.superpowers/dependency-check` 环境验证 LangGraph 与当前 Python、Pydantic、HTTP 客户端兼容后，锁定实际通过的精确依赖版本。安装依赖不进行收费模型探测，不复制/打印凭据。
- [ ] 写 `test_parallel_reservations_cannot_overspend`、`test_retry_and_json_repair_share_global_budget`、`test_subtask_tool_cap_survives_reentry`、`test_usage_without_provider_counts_is_estimated`、`test_actual_usage_is_not_clamped_to_limit`，用 barrier 和小额度核对拒绝的调用没有进入 provider。
- [ ] 写 `test_peak_model_concurrency_is_two`、`test_cancelled_waiter_never_enters_provider`、`test_parallel_deadlines_do_not_overwrite_each_other`、`test_inflight_usage_settles_before_cancelled_terminal`，观测实际峰值和终态用量。
- [ ] 先运行 `python -m pytest tests/test_budget.py tests/test_model_gateway.py -q` 确认缺失实现失败，再实现锁和预留；发事件/HTTP/工具执行期间不持有预算锁，避免与任务服务锁形成死锁。
- [ ] HTTP 适配器使用每次 run/调用的独立 deadline 上下文，不能给共享实例反复改 deadline。重试不在图层再叠加一套未计量的 provider 重试。
- [ ] 同命令及 `python -m pytest tests/test_agent.py tests/test_model_client.py tests/test_deadline.py -q` 全部通过后提交。

### Task 2: 同快照文档证据和角色检索范围

**Interfaces:** `ToolContext.source_scope: Literal['all','code','docs']='all'`，由服务端设定；模型工具参数不能覆盖它。Evidence 增加默认兼容的 `source_type`，新引用标记 repository_file / repository_document，旧 ID 不改变。RepositoryIndex 搜索接口增加可选 scope，必须在排序/LIMIT 前筛选。

- [ ] 写 `test_repository_documents_are_snapshot_bound`、`test_old_markdown_evidence_id_remains_valid`、`test_legacy_evidence_json_is_normalized`、`test_source_directory_changes_do_not_change_document_evidence`。
- [ ] 写 `test_docs_search_filters_before_limit`、`test_code_role_cannot_read_document_scope`、`test_docs_role_cannot_retrieve_code_evidence`、`test_model_cannot_override_scope_or_snapshot`、`test_missing_documents_are_explicit`。
- [ ] 先运行 `python -m pytest tests/test_document_scope.py -q` 确认失败，再实现分类、参数校验和查询范围。可使用静态、参数化的路径类型谓词；不能先取 20 条再丢掉另一类型的结果。
- [ ] 旧 Evidence JSON 的缺省来源类型在加载时归一化，并重新校验实际行号/hash；不因增加字段导致旧 Markdown 报告打不开。原有未纳入文件继续是排除项，不能偷偷读取原目录补证据。
- [ ] 新旧证据、工具、索引及 GitHub 引用回归全部通过后提交。

### Task 3: LangGraph 协同图与有限评审

**Interfaces:** `CollaborativeRunner.run(question, context, emit, cancelled) -> AnalysisResult`，与 AgentRunner 的服务调用一致；`ResearchPlan` 含最多 4 个无环、只引用本任务的子任务；`SubtaskResult` 含服务端 ID、角色、claims、已观察 evidence_ids、limitations、status 和结果 hash；`ReviewDecision` 含对已有 claim_id 的模型判断及最多 2 个补查请求。

- [ ] 写脚本化角色模型与固定本地 fixture。Planner 拆分 code/docs；两个调查节点使用真实工具；Reviewer 发现 fixture 文档/代码差异并触发一次针对性补查；Reporter 只合并已引用事实。测试替身仅在 tests，页面标记测试环境。
- [ ] 写 `test_graph_runs_code_and_docs_with_shared_budget`、`test_plan_rejects_foreign_ids_cycles_and_too_many_subtasks`、`test_reducer_is_order_independent_and_idempotent`、`test_conflicting_duplicate_result_is_not_silently_overwritten`。
- [ ] 写 `test_review_cannot_invent_claim_or_evidence`、`test_followup_stops_after_two_rounds`、`test_no_new_evidence_stops_followup`、`test_prompt_injection_cannot_add_network_or_shell`、`test_graph_step_guard_returns_explicit_partial`、`test_one_failed_branch_preserves_other_branch_as_partial`。
- [ ] 先运行 `python -m pytest tests/test_orchestration.py -q` 确认失败，再用真正的 StateGraph / Send / reducer 实现，禁止用顺序调用冒充并行图。
- [ ] Planner 与 Reviewer JSON 各最多一次修正且计总预算；补查任务 ID 由服务端分配。所有最终引用须属于本图实际成功返回的工具证据并通过快照复核，不能仅凭数据库存在即接受。
- [ ] 角色模型输出的是待审 claims；模型评审标签单独存储，不能改成“事实已证明”。冲突两侧引用可查看，未解决缺口/失败/预算耗尽时 partial；没有有效引用不返回 succeeded。
- [ ] 配置顶层 `max_concurrency=2`、显式业务轮数和防失控步数；任何异常/取消都排空或结算在途调用后返回。如实际锁定 LangGraph 版本的配置语义不同，以峰值测试为准并记录。
- [ ] 新图、预算、single 基线回归通过后提交。

### Task 4: 持久图详情、模式和 API 兼容

**Interfaces:** POST /tasks 新增 `mode: Literal['single','collaborative']='single'`；AnalysisTask/AnalysisResult 的 mode 提供默认 single；`GET /tasks/{id}/graph` 返回公开计划、子任务状态、轮次与评审摘要。task/subtask/review 仍存 SQLite，复用统一 events sequence 和取消机制。

- [ ] 写 `test_old_task_request_defaults_to_single`、`test_legacy_task_list_and_report_load`、`test_idempotency_conflicts_across_modes`、`test_mode_persists_across_refresh`、`test_unknown_mode_is_validation_error`。
- [ ] 写 `test_graph_details_and_events_are_task_scoped`、`test_cancel_stops_new_subtasks`、`test_failure_and_budget_events_are_not_succeeded`、`test_restart_marks_graph_interrupted_without_resume`、`test_terminal_report_mode_and_usage_are_atomic`。
- [ ] 先运行 `python -m pytest tests/test_collaborative_api.py -q` 确认失败，再扩展服务。旧幂等记录缺 mode 视为 single；同键切模式返回 409，不创建额外模型任务。
- [ ] 单 worker 管理整张图，图内最多两路模型请求。并发节点事件由数据库事务分配序号；节点结果/评审持久化与用户可见状态一致，不增加第二个任务权威状态源。
- [ ] 图视图不返回秘密配置、隐藏推理或可执行代码；不新增 resume / waiting_input / checkpoint 的占位接口。
- [ ] 图接口和既有 API/task/SSE 回归全部通过后提交。

### Task 5: 工作台的模式、分工和冲突证据

**Interfaces:** 新建分析默认 single，可选 collaborative，说明共享预算；pending intent 包含 mode，追问继承当前任务的模式和 snapshot。报告、调查过程、资料/证据沿用现有布局；协同任务展示简短计划、子任务和评审状态，代码/文档引用可区分。

- [ ] 写 `test_collaborative_submit_shows_plan_and_citations`、`test_conflict_opens_code_and_document_sources`、`test_refresh_and_sse_resume_keep_subtasks_without_duplicates`、`test_lost_response_retry_preserves_mode_and_one_task`、`test_cancel_does_not_launch_followup`、`test_single_task_remains_compatible`。
- [ ] 先运行 `python -m pytest tests/browser/test_collaborative_workspace.py -q` 确认缺失 UI 失败，再实现；请求中锁定 mode/source/question，旧异步响应不能覆盖新选择的任务。
- [ ] 320/390/736/1024px 验证表单、分工、冲突和证据无页面横向溢出；键盘可操作模式、标签及引用；状态变化有 aria-live。所有模型文本用安全文本节点，报告继续转义自由文本引用语法。
- [ ] 未配置模型保持明确错误；缺文档和分支失败展示真实状态。任务分工和模型评审摘要不冒充私有推理或人工结论。
- [ ] 运行全部浏览器回归并人工查看桌面/手机截图，通过后提交。

### Task 6: 同预算 single/collaborative 比较与交付

**Interfaces:** `python -m eval.compare --base-url URL --tasks eval/collaborative_tasks.jsonl --output PATH`；每题/每模式记录固定 snapshot/manifest、模型标识、提示词/配置版本、预算、执行状态、claims、证据、角色用量、延迟和待人工质量值。

- [ ] 建立 5 题固定本地回归：实现入口、状态保存、恢复缺口、文档与实现冲突、不存在功能。代码/文档正向证据都必须真实来自 fixture；至少保留一个错误语义/伪引用负向用例。
- [ ] 写 `test_comparison_reuses_snapshot_model_and_budget`、`test_all_failures_remain_in_both_denominators`、`test_execution_or_model_review_is_not_quality_score`、`test_unknown_usage_is_not_zero`、`test_synthetic_comparison_cannot_claim_improvement`。
- [ ] 先运行 `python -m pytest tests/test_comparison.py -q` 确认失败，再实现导出；single 和 collaborative 使用完全相同总额度，不能以角色数放大预算制造提升。
- [ ] 没有真实模型时只运行 synthetic 比较，保留 quality_pass=null 等待独立人工。真实配置可用时只额外跑一次小规模比较；不要求在聊天中提交 key，不反复调用昂贵模型，不保证协同优于基线。
- [ ] 更新 README、锁定依赖、模式/文档范围、比较说明、限制和运行记录。记录仍未支持的外部文档网页、Milvus、持久图恢复及当前网络阻塞，不静默删除总体设计目标。
- [ ] 运行 `python -m pytest -q`、`python -m compileall src`、`python -m pip check`；165 项旧回归必须通过。最终一次独立审查按五类 Review Focus 复核，重要修复先 RED 再 GREEN。
- [ ] 验证正式服务启动、模式/API/取消行为；没有真实模型时只声称启动/配置检查通过。打包源码、计划、测试/比较结果，排除凭据、运行 DB、快照/归档缓存和虚拟环境，校验 ZIP 完整性及源码 hash。
- [ ] 本地提交功能分支并报告实际结果；合并/推送按后续明确授权执行，不 force push。

## Self-Review and Handoff

- 这是既定路线中的独立协同增量，默认保留 single；文档限于同快照已纳入文本是本轮建议边界，待用户审阅，而非已确认的额外用户要求。
- 六个任务接口依次为：共享 Budget/Gateway → 受限文档证据 → 图结果 → 持久 API → UI → 同预算比较，未将预算锁、网络客户端或回调放进待序列化图状态。
- 五类 Review Focus 均有具体测试；旧引用、旧 JSON、跨模式幂等与已有安全回归不因引入框架而删除。
- 旧设计中的外部资料、Milvus 和持久恢复仍是后续目标。本轮不把接入 LangGraph 本身宣称为效果收益或断点恢复。
- 本文是待审阅计划；当前只新增此文档，没有安装依赖、修改产品代码、合并分支或开始收费模型调用。
- 延续此前 inline 执行方法，用户确认后再实施，不重复询问执行方式。

## Official References

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [LangGraph Send](https://reference.langchain.com/python/langgraph/types/Send)
- [LangGraph 官方 Graph API 源文档](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/graph-api.mdx)
- [LangGraph 官方并发配置问题记录](https://github.com/langchain-ai/langgraph/issues/8920)：不能只相信参数存在，必须测在途调用实际峰值。
