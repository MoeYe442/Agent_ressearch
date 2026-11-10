# RepoLens V1 Implementation Plan

> 此副本保留原计划内容与原始复选框，避免把计划原文误当作实测记录。实际实现、独立审查修复和最终测试结果见 [validation.md](./validation.md) 与 [implementation-decisions.md](./implementation-decisions.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立本地 Python 仓库研读工作台，完成仓库登记、版本固定、源码检索、工具调用、带引用报告与证据查看。

**Architecture:** Python 单体，FastAPI 提供页面与 API，独立任务执行器运行模型工具循环，SQLite 保存快照、事件、工具结果、报告与证据。前端采用服务端模板与 JavaScript，实现已确认的导航、报告/调查过程/证据切换及证据侧栏；V1 先使用单 Agent，作为后续多 Agent 评测基线。

**Tech Stack:** Python、FastAPI、Pydantic、Jinja2、SQLite、Python ast、HTTP 模型适配、pytest；兼容版本在实现时锁定。Redis、Milvus、LangGraph、MCP、Playwright 网页采集属于后续版本；浏览器验收可使用 Playwright，与产品是否具备网页采集功能无关。

**Spec:** [RepoLens-Design-v1.md](./RepoLens-Design-v1.md)，已获用户同意；交互布局已获同意。此计划为待审阅的实施计划，不表示代码已实现。

## Global Constraints

- 首版支持公开 Python GitHub 仓库和本地 Python 仓库的固定快照；单个任务分析一个仓库。V1 本轮先交付本地仓库路径，公开 GitHub 导入单列后续增量，不将其宣称为已支持。
- 只读分析，不执行被分析项目代码；Executor 不提供任意 shell。
- 快照最多 500 MB，纳入索引文本总量最多 100 MB，单文本文件最多 1 MB。初始排除 .git、依赖目录、构建产物、二进制、生成文件和明显密钥文件。
- 首轮最多 4 个子任务；V1 单 Agent 无子任务展开。V1 每次模型返回最多执行 8 个工具请求，全局最多 30 次工具调用、30 次模型请求、60,000 输入/输出 token、15 分钟，全部作为上限而非目标。
- 任务恢复不能通过重置已用预算绕过限额；V1 未实现跨进程恢复，不伪称支持。
- 关键引用包含快照标识、commit（若存在）、文件路径、行号与内容 hash。非 Git 目录生成内容清单 hash 作为版本标识。
- 单用户、本地运行，仅接受配置工作目录中已登记的仓库；不向未认证公网暴露路径读取接口。
- 页面不得把示例数据、占位调用或假模型回答标为真实调查结果。
- 内部 succeeded 表示流程完成；答案质量由独立评测判断。

## Review Focus

1. 仓库或文件含符号链接、../、敏感文件时不得读取允许根目录外内容；由任务 1、2 的路径约束测试覆盖。
2. 分析期间原仓库变化时，引用仍对应导入快照；由任务 1、2 的快照与 hash 测试覆盖。
3. 模型请求越权工具、生成无效 JSON、引用不存在的证据时，不执行非法操作、不产出伪引用；由任务 3 覆盖。
4. 浏览器刷新、SSE 断线、重复提交与取消时，不丢事件或重复创建任务；由任务 4、5 覆盖。
5. 模型不可用、预算耗尽、进程退出时，不把失败隐藏成成功；由任务 3、4、6 覆盖。

## File Structure

计划在一个新项目根目录实现；当前只有设计文件，不假定已有代码或 Git 远程仓库。若使用 Git，在任务完成且检查通过后提交；无 Git 时保留本地版本并最终打包交付。

| 文件 | 职责 |
|---|---|
| pyproject.toml、.env.example、.gitignore | 依赖、启动入口、配置示例、排除凭据与运行数据 |
| src/repolens/config.py | 受控工作目录、数据目录、预算与模型配置 |
| src/repolens/models.py | 跨模块 Pydantic 契约，不放业务逻辑 |
| src/repolens/storage.py | SQLite 连接、事务和实体读写 |
| src/repolens/repositories.py | 仓库登记、过滤与不可变快照 |
| src/repolens/indexing.py | ast/Markdown 结构解析、符号与文本索引 |
| src/repolens/evidence.py | 快照内受控读取、证据生成及引用验证 |
| src/repolens/tools.py | 工具声明、参数校验与结果封装 |
| src/repolens/model_client.py | 模型适配协议与一个可配置真实服务适配器 |
| src/repolens/agent.py | 工具循环、预算、报告生成 |
| src/repolens/tasks.py | 队列、执行器、状态转换与取消 |
| src/repolens/api.py、main.py | HTTP/SSE 接口与应用生命周期 |
| src/repolens/templates/workspace.html | 工作台结构，所有功能调用真实 API |
| src/repolens/static/workspace.js、workspace.css | 页面状态、证据切换、响应式样式 |
| tests/fixtures/sample_repo/ | 小型人工构造 Python 仓库及预期证据 |
| tests/test_*.py、tests/browser/ | 契约、异常流程与浏览器验收 |
| eval/tasks.jsonl、eval/run.py | 五题回归任务与结果导出 |
| README.md、docs/demo.md | Windows 本地启动、配置、限制及演示步骤 |

## Task 1: 可重复导入的本地仓库快照

**Files:** config.py、models.py、storage.py、repositories.py、pyproject.toml；tests/test_repositories.py。

**Interfaces:**
- Produces: `Settings(workspace_root: Path, data_dir: Path, ...)`。
- Produces: `create_snapshot(repo_path: Path, settings: Settings) -> RepositorySnapshot`。
- Produces: `RepositorySnapshot(id: str, source: str, commit_sha: str | None, manifest_hash: str, root: Path, status: str, excluded_files: list[str])`。
- Produces: `Database(path: Path)`；`put_snapshot(snapshot)`、`get_snapshot(snapshot_id)`。

- [ ] 编写测试：`test_snapshot_is_immutable`，导入后修改原文件，快照字节保持不变；`test_rejects_path_outside_workspace`、`test_skips_symlink_and_secrets`，拒绝越界目录并记录被排除项。
- [ ] 编写测试：`test_snapshot_limits`，通过可调小限额验证单文件、总文本量及总快照大小限制；不创建超大测试文件。
- [ ] 运行 `pytest tests/test_repositories.py -q`，确认因缺少实现而失败。
- [ ] 实现导入与内容清单：普通目录也生成稳定版本；Git 目录使用受控 Git 调用读取 commit，并校验工作区状态，存在未提交变更时以内容清单标识实际快照，不冒充纯 commit 内容。
- [ ] 运行上述测试，通过后记录本任务变更；若有 Git 则提交。

## Task 2: 检索工具与可验证证据

**Files:** indexing.py、evidence.py、tools.py、models.py；tests/test_indexing.py、tests/test_evidence.py、tests/test_tools.py。

**Interfaces:**
- Consumes: `RepositorySnapshot`、`Database`。
- Produces: `build_index(snapshot: RepositorySnapshot, db: Database) -> IndexSummary`。
- Produces: `search_symbols(snapshot_id: str, query: str, limit: int = 10) -> list[SearchHit]`、`search_text(snapshot_id: str, query: str, limit: int = 10) -> list[SearchHit]`。
- Produces: `read_evidence(snapshot_id: str, path: str, start_line: int, end_line: int) -> Evidence`、`validate_evidence(evidence_id: str, snapshot_id: str) -> bool`。
- Produces: `ToolRegistry.invoke(name: str, arguments: dict, context: ToolContext) -> ToolResult`；`ToolContext(snapshot_id, task_id)` 固定访问范围。
- 契约：SearchHit 包含 path、symbol、start_line、end_line、score；Evidence 包含 id、snapshot_id、path、start_line、end_line、excerpt、content_hash、commit_sha；ToolResult 包含 invocation_id、status、data、evidence_ids、error_code、retryable、elapsed_ms。

- [ ] 编写测试：`test_ast_finds_class_method_and_import`、`test_syntax_error_keeps_text_search`，语法错误文件仍可文本检索并记录解析错误。
- [ ] 编写测试：`test_evidence_matches_exact_lines`、`test_rejects_parent_traversal_and_absolute_path`、`test_rejects_snapshot_mismatch`、`test_missing_tool_returns_structured_error`。
- [ ] 运行 `pytest tests/test_indexing.py tests/test_evidence.py tests/test_tools.py -q`，确认失败。
- [ ] 实现精确符号检索和 SQLite FTS5 关键词检索；关键词内容使用参数化查询，FTS 特殊字符需转义。运行环境不支持 FTS5 时启动报明确依赖错误，不静默改变排序。
- [ ] 实现白名单工具 list_tree、search_symbols、search_text、read_file、get_symbol、retrieve_evidence；get_symbol 复用 read_evidence，不绕开行数、路径与快照约束。命中原文时生成稳定证据 ID。
- [ ] 运行本任务测试，通过后记录或提交。

## Task 3: 带预算限制的真实模型工具循环

**Files:** model_client.py、agent.py、models.py、tools.py；tests/test_agent.py。

**Interfaces:**
- Consumes: ToolRegistry、ToolContext、Evidence。
- Produces: `ChatModel.complete(messages: list[Message], tools: list[ToolDefinition], max_output_tokens: int) -> ModelTurn`；ModelTurn 包含 tool_calls、content、usage。
- Produces: `AgentRunner.run(question: str, context: ToolContext, emit: Callable[[TaskEvent], None], cancelled: Callable[[], bool]) -> AnalysisResult`。
- Produces: `AnalysisResult(status, claims, limitations, markdown, usage)`；Claim 包含 text、evidence_ids、verification_status。

- [ ] 编写脚本化测试模型：首轮搜索、次轮读取、第三轮提交结构化结论；断言工具结果真实来自 fixture，报告引用通过快照校验。
- [ ] 编写测试：`test_unknown_tool_not_executed`、`test_invalid_arguments_are_tool_error`、`test_hallucinated_evidence_blocks_final_claim`、`test_budget_exhaustion_returns_partial`、`test_provider_failure_is_explicit`。
- [ ] 运行 `pytest tests/test_agent.py -q`，确认失败。
- [ ] 实现模型配置与一个真实适配器；输出 JSON 解析失败最多一次修正并计预算。未知工具不执行；没有证据的代码事实删去或标为待验证。
- [ ] 实现调用前预算预留、调用后实际 usage 结算；若服务不返回 usage，采用保守估算并在报告标记 estimated。保留输入与输出计量，不用字符数冒充精确 token。
- [ ] 对网络错误按可重试类型最多重试两次，均计入预算；工具/模型调用前后检查取消。原始网页和代码不得覆盖系统工具权限。
- [ ] 运行本任务测试，通过后记录或提交。测试替身只用于测试；UI 演示若未配置真实模型，必须显示“未配置模型”。

## Task 4: 持久任务、异步执行与事件 API

**Files:** tasks.py、api.py、main.py、storage.py、models.py；tests/test_api.py、tests/test_tasks.py。

**Interfaces:**
- Consumes: AgentRunner、Database。
- Produces: `TaskService.submit(snapshot_id: str, question: str, idempotency_key: str | None) -> AnalysisTask`、`get(task_id)`、`cancel(task_id)`、`events(task_id, after_sequence: int)`。
- Produces: `create_app(settings: Settings, model: ChatModel | None = None) -> FastAPI`。
- HTTP：POST /repositories；GET /repositories/{id}；POST /tasks；GET /tasks/{id}；GET /tasks/{id}/events；POST /tasks/{id}/cancel；GET /tasks/{id}/report；GET /evidence/{id}。POST 接口返回 202 与任务/导入 ID；错误返回稳定 error_code。
- 状态：queued、running、succeeded、partial、failed、cancelled；V1 不暴露尚未实现的 resume 接口。

- [ ] 编写测试：`test_submit_returns_before_model_finishes`、`test_idempotency_conflict`、`test_events_resume_after_sequence`、`test_cancel_before_next_tool`、`test_restart_marks_interrupted_task_failed`。
- [ ] 运行 `pytest tests/test_api.py tests/test_tasks.py -q`，确认失败。
- [ ] 实现进程内单 worker 队列，任务与事件持久存库；模型阻塞操作不占用 HTTP 主事件循环；任务状态更新通过事务。
- [ ] 启动时将旧 running 任务标为 failed/interrupted，旧 queued 任务重新排队；V1 不宣称能从节点断点恢复。
- [ ] SSE 使用数据库 sequence，支持 Last-Event-ID，终态后发送结束事件。浏览器断开连接不取消任务。
- [ ] 运行本任务测试，通过后记录或提交。

## Task 5: 已确认的工作台前端

**Files:** templates/workspace.html、static/workspace.js、static/workspace.css；tests/browser/test_workspace.py。

**Interfaces:**
- Consumes: 任务 4 的 API 和 SSE；引用按钮携带 evidence_id，通过证据接口获取代码片段。
- Produces: 新建分析表单、分析工作台、报告/调查过程/资料与证据视图、可响应布局的证据侧栏。

- [ ] 编写浏览器测试：`test_submit_and_open_citation`，提交 fixture 仓库后从报告引用打开正确源码；`test_refresh_restores_task`，页面刷新后从 URL task_id 恢复；`test_mobile_view_has_no_horizontal_overflow`，320/390/736/1024px 检查溢出。
- [ ] 编写浏览器测试：`test_provider_error_is_visible`、`test_sse_disconnect_recovers_without_duplicate_events`；测试服务使用脚本化模型，页面明确显示测试环境，不混入生产示例数据。
- [ ] 运行 `pytest tests/browser -q`，确认页面尚不存在导致失败。
- [ ] 实现布局：桌面左导航、中间报告、右证据；窄屏证据改为下方独立区块。键盘能操作标签与引用，状态变化有 aria-live 提示。
- [ ] 实现任务状态和错误态；模型未配置时显示配置提示。报告渲染必须防脚本注入；V1 可先使用文本与结构化段落，代码通过 textContent 写入，不直接插入未经清洗的 HTML。
- [ ] 实现同任务追问新建分析请求，保留 snapshot_id，不覆盖旧报告。取消操作与后端状态一致；Token/耗时来自真实记录，无数据时显示“暂无”。
- [ ] 运行浏览器验收，截图检查桌面/手机；无法启动浏览器时记录具体阻塞，不能仅凭静态检查宣称视觉验收通过。
- [ ] 通过后记录或提交。

## Task 6: 五题回归与可复现交付

**Files:** eval/tasks.jsonl、eval/run.py、README.md、docs/demo.md；tests/test_eval.py。

**Interfaces:**
- Consumes: V1 API 与固定 fixture 快照。
- Produces: `python -m eval.run --base-url URL --tasks eval/tasks.jsonl --output PATH`，输出逐题结果、耗时、usage、质量完成率与执行完成率。
- 五题覆盖入口定位、状态保存、恢复流程、文档与实现差异、仓库中不存在的功能。每题记录 required_symbols、accepted_evidence、expected_limitations；答案语义由人工按规则核验，结构存在性由程序检查。

- [ ] 编写测试：`test_failed_tasks_remain_in_denominator`、`test_execution_success_not_quality_success`、`test_missing_usage_is_not_zero_cost`。
- [ ] 运行 `pytest tests/test_eval.py -q`，确认失败。
- [ ] 实现回归执行与导出；无真实模型凭据时只完成替身集成测试，回归结果标为 synthetic，不产生实测提升结论。
- [ ] 编写 Windows PowerShell 启动说明、配置变量、工作目录限制、清理数据方法和 V1 能力边界。不要求用户提供聊天中的 API key。
- [ ] 运行 `pytest -q` 与 `python -m compileall src`；真实模型可用时额外跑一次五题回归，不反复运行昂贵模型测试。
- [ ] 打包源码、设计、启动说明与测试结果；排除 .env、密钥、被分析仓库缓存、虚拟环境和运行数据库。交付文件保存并提供链接。

## 阶段验收与后续顺序

V1 验收：用户可按说明在本机启动；导入一个受控本地 Python 仓库；提交问题；看到真实工具事件；得到带可点击引用的报告；遇到模型、路径、预算错误时得到明确状态。未配置真实模型时只能验收仓库、工具、接口和测试，不能宣称真实 Agent 完成。

V1 之后依次制定独立计划：公开 GitHub 导入 → LangGraph 协同调研与文档证据 → Milvus 混合检索和上下文压缩 → Redis/持久 worker/检查点恢复 → MCP/动态网页采集 → 多仓库评测。以每阶段的效果与成本决定是否引入组件。

## 计划自查

- 此计划覆盖设计文档 V1 核心流程；GitHub 导入明确延期为单独增量，没有默默删除原始需求。
- 模型、索引、证据、任务服务和前端接口均在对应任务先定义后使用。
- Review Focus 五类异常均分配了具体测试。
- 尚无代码或真实模型结果；任务复选框全部保持未完成。
- 默认由同一实现者按顺序推进，减少跨模块接口反复；复杂协作与恢复机制不混入 V1。
