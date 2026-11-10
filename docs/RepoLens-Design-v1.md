# RepoLens：多 Agent 开源项目研读与技术调研平台

版本：设计草案 v1.0｜日期：2026-11-10｜状态：待用户确认，尚未实现

## 1. 项目定位与成功标准

面向开发者理解陌生大型开源项目时，代码阅读成本高、技术资料分散、人工调研效率低的问题，提供从仓库和问题输入，到协同调查、证据核验和报告输出的完整流程。

用户已明确：使用 Python；采用多 Agent 协同分析；希望作品能写入简历并经得起技术追问；参考能力包括仓库解析、RAG、工具调用、网页采集、上下文管理、恢复与审计。技术栈参考 Python、FastAPI、LangGraph、RAG、MCP、Playwright、Redis、Milvus、Docker、LLM Tool Calling。

本文中的首版分析语言、并发和预算等是建议默认值，并非用户逐项指定；均允许调整。目标不是保证对任意大型仓库完全理解，而是对明确版本和问题给出可复查、有边界的结论。

最终成功标准：

- 对陌生仓库完成架构梳理、功能实现追踪和源码与文档对照三类任务。
- 关键事实可定位到指定 commit 的代码行或保存的网页片段。
- 多 Agent 带来的收益可通过相同预算下的实验验证；没有收益时允许使用单 Agent。
- 任务可取消、可恢复，有完整工具轨迹和真实成本记录。
- 提供一套可复现的本地部署、演示案例和评测记录。

## 2. 范围与边界

首版支持公开 Python GitHub 仓库和本地 Python 仓库的固定快照；单个任务分析一个仓库。Python 解析通过 ast 提取函数、类、方法、装饰器、导入及潜在调用位置。动态分派、反射和运行时注入无法可靠静态解析时，明确标为候选关系，不能声称完整调用图。

完整阶段增加用户指定的技术资料和相关 Issue/PR；GitHub 来源默认通过 API/仓库文件读取；网页先静态获取，确有 JS 渲染需求再使用 Playwright。首版不做全网自主搜索，后期搜索服务通过可替换适配器接入。公共 GitHub API 无凭据时遇限流需等待或降级，不把配额故障包装为分析结果。

首版不包含自动代码修复、执行被分析仓库代码、跨仓库全局分析、私有仓库 OAuth 接入、生产级多租户和付费系统。只读也需要限制路径访问与网络目的地。Executor 仅执行允许的检索与读取工具，不提供任意 shell。

资源默认：单仓库快照最多 500 MB、纳入索引的文本总量最多 100 MB、单文本文件最多 1 MB；排除 .git、依赖目录、构建产物、二进制、生成文件和明显密钥文件。超过限制需说明被排除内容，支持用户选择子目录后分析。具体上限以本机资源验证后调整。

## 3. 架构选择与取舍

| 方案 | 优点 | 代价 | 本项目安排 |
|---|---|---|---|
| 单 Agent＋检索工具 | 易实现、成本低、适合窄问题 | 广泛调研容易遗漏，难显式分工 | V1 与评测基线 |
| LangGraph 协调器＋专职 Agent | 任务依赖明确，可并行和补充调查，轨迹可追溯 | 状态、预算、证据合并更复杂 | 推荐主架构 |
| 多角色自由对话 | 快速搭建概念演示 | 容易循环、重复调查，难控制停止条件 | 不作为默认执行方式 |

按此前约定先跑通最小流程，再扩展完整协作平台；六个角色是逻辑职责，不意味着每次必须六次模型调用。简单问题走快速路径，复杂任务才展开图。证据不足时的结论是“不足以确认”，不能靠追加角色制造确定性。

## 4. 系统分层与部署

| 层 | 组件 | 职责 |
|---|---|---|
| 交互层 | 简单 Web 页面 | 输入仓库与问题、展示任务事件、查看报告与引用、确认补充调查 |
| API 层 | FastAPI＋Pydantic | 输入校验、任务接口、SSE 事件订阅、报告下载 |
| 编排层 | LangGraph | 路由、任务拆解、并行分析、验证、有限循环、检查点 |
| 工具层 | Python 工具注册表；后期 MCP 适配 | 仓库读取、符号检索、文档获取、证据查询 |
| 索引层 | ast＋关键词检索＋Milvus | 代码结构索引、BM25 与向量检索、重排 |
| 持久层 | V1 SQLite；V3 PostgreSQL | 任务、报告、证据、事件、工具结果及持久检查点 |
| 临时层 | V3 Redis | 消息队列、缓存、限流；不能作为唯一业务事实来源 |
| 运行层 | API 进程＋独立 worker；Docker Compose | 长任务与 HTTP 请求分离；声明依赖健康检查和持久卷 |

前端先采用 FastAPI 模板与少量 JavaScript，降低与核心能力无关的工作量；之后可替换。数据库从 SQLite 迁移至 PostgreSQL 时提供结构迁移与数据导入，并以恢复场景重新验收。文件快照与网页正文保存在持久卷，数据库记录位置和内容 hash。Milvus 索引可重建，不作为原始证据的唯一存储。

模型调用经统一适配器，配置模型名称、API 地址和凭据；不承诺任意本地模型均支持工具调用。启动时检查所选模型的结构化工具调用能力；不支持时明确报错。Embedding 和 reranker 单独配置，索引记录模型版本。

## 5. 用户流程与示例

用户导入仓库并选择 ref，系统解析为 commit SHA，生成不可变快照与索引。用户提出“分析任务恢复机制，说明状态在哪里保存、失败后如何继续，并对照官方文档”。

平台展示任务计划；CodeReader 检索状态存储与恢复实现，Researcher 查询同版本文档和必要 Issue；Reviewer 核对证据，发现版本不一致则发起针对性补充调查；Reporter 输出结论、关键代码、流程说明、局限与来源。用户点引用能跳到快照对应位置，追问沿用同一版本；要分析最新版本，创建新的快照与索引。

界面重点：输入页、仓库索引状态、任务时间线、报告与证据侧栏。只展示工具操作、发现摘要和证据，不要求保存或公开模型隐藏推理。

## 6. Agent 职责与执行规则

| 角色 | 输入 | 产物 | 约束 |
|---|---|---|---|
| Planner | 问题、仓库概要、预算 | 有依赖的子任务、验收条件、搜索范围 | 最多 4 个首轮子任务，避免重复目标 |
| Researcher | 文档子问题、限定来源 | 文档结论与证据 ID | 区分来源版本和日期，网页视为不可信数据 |
| CodeReader | 代码子问题、符号索引 | 实现位置、候选调用路径、代码证据 | 以快照为准，不把函数名猜测当作实现事实 |
| Executor | 结构化工具请求 | 工具结果、错误、耗时与元数据 | 确定性运行组件，默认不需独立 LLM |
| Reviewer | claims 与 evidence 集合 | 支持/矛盾/不足、缺失项、补查建议 | 文件行号检查可程序化，语义核验仍可能出错 |
| Reporter | 经验证的结论 | Markdown 报告与局限 | 不新增未经验证的事实 |

默认流程：路由 → 计划 → 并行代码/资料调查 → 证据合并 → 验证 → 必要补查 → 报告。并发上限 2 个模型任务；每个子任务最多 8 次工具调用，全局最多 30 次、30 次模型请求、累计 60,000 输入/输出 token、15 分钟。触发任一上限后停止继续调查，以已有证据形成部分结果；每次调用也设置 max_tokens，不能只在调用结束后计费。重试同样计入预算。

Reviewer 最多触发 2 轮针对性补查。无新增证据、目标已满足、预算耗尽、取消或达到轮次上限时结束。以上数值是开发默认配置，后续依据评测调整并记录配置。

共享状态：task_id、snapshot_id、question、plan、subtasks、claims、evidence_ids、findings、unresolved、budget_usage、errors、checkpoint_version。并发 Agent 输出独立结果，由 reducer 依照子任务 ID 和内容 hash 合并，不依靠共享列表任意覆盖。

## 7. 仓库解析与 RAG

索引阶段：文件筛选 → 编码识别 → ast/Markdown 结构解析 → 语义单元切块 → 元数据 → BM25/向量索引。长函数按语句或行窗口细分，记录父符号和少量重叠，不能在压缩时丢失原始行号。

块元数据至少包括 snapshot_id、commit_sha、path、start_line、end_line、symbol、language、content_hash、chunker_version、embedding_model。网页块另记 URL、标题、采集时间、正文 hash、段落位置、声明版本及与仓库版本的匹配状态。

查询阶段：符号精确查找/关键词匹配与向量召回并行 → 排名融合 → 可配置重排 → 去重 → 按预算读取上下文。首版可先精确检索＋关键词，向量检索上线前后用相同任务比较。初始候选取各 20 条，融合后取 20 条重排，最终按 token 预算选 6—10 条，属于待评测参数。

代码事实优先验证代码；文档解释设计意图；Issue/PR 可提供背景但不能代替当前实现。旧文档无法验证时保留版本差异，不强行合并。索引必须按快照过滤，不能混用不同 commit。

## 8. 工具协议与证据

统一工具接口：name、description、input_schema、output_schema、timeout、retry_policy、permission。结果包含 invocation_id、status、data、evidence_ids、error_code、retryable、elapsed_ms。

首版工具：list_tree、search_symbols、search_text、read_file、get_symbol、retrieve_evidence。扩展工具：fetch_document、search_project_issues、render_page、hybrid_search。函数位置来自结构索引；调用关系属于静态候选，需要代码佐证。

MCP 在工具接口稳定后作为传输适配，不承担 Agent 之间的调度；内部调用和 MCP 调用复用相同校验。Playwright 在隔离浏览器环境运行，限定目标与跳转；禁止访问内网地址及本地文件；普通 HTTP 同样检查重定向目的地与内容大小。

核心结构：Claim(claim_id, text, evidence_ids, verification_status, limitations)；Evidence(evidence_id, source_type, snapshot_id, locator, excerpt, content_hash, collected_at)。报告中的技术事实引用 claim_id 与 evidence_id，引用存在性、行范围和 hash 可自动检查；“支持程度”需人工抽查或评审，不能把 LLM 的自评当作真值。

## 9. 压缩、记忆与恢复

| 机制 | 保存什么 | 生命周期与校验 |
|---|---|---|
| 上下文压缩 | 子任务摘要、已验证结论、证据 ID、失败原因、下一步 | 超过上下文预算时触发；完整工具结果仍存库，可回读 |
| 长期记忆 | 仓库概要、被确认的技术知识、已验证调查结果 | 绑定 snapshot/commit；新版本只作线索，重新验证后使用 |
| checkpoint | 图状态、已完成节点、待执行子任务、预算与工具结果引用 | 恢复同一任务快照；保存模型、提示词及工具 schema 版本 |

数据库是任务权威状态；Redis 只传递 task_id，worker 获取带过期时间的租约、心跳与递增执行代号。重复投递时按 task_id 和节点执行键检查已完成结果。旧 worker 失去租约后不得继续提交状态；取消标记在工具调用前后和图节点间检查。

checkpoint 不代表任意外部调用都只执行一次。只读抓取允许至少一次执行并按 hash 去重；已保存的工具结果优先复用；模型请求在进程崩溃边界可能产生重复费用，要记录并尽可能计入预算。用户主动重试创建新 attempt，保留旧轨迹。

人工介入用于确认范围、补充资料或继续部分任务；恢复状态后仍重新校验预算。摘要缺失关键事实时通过 evidence_id 回读原文，不能仅依赖摘要继续推断。

## 10. 数据模型与 API

| 实体 | 关键字段 |
|---|---|
| RepositorySnapshot | id、source、ref、commit_sha、path、status、manifest_hash、excluded_files |
| AnalysisTask | id、snapshot_id、question、status、attempt、lease_epoch、budget、usage、config_version |
| Subtask | id、task_id、role、goal、depends_on、status、result_ref |
| ToolInvocation | id、task_id、node_key、tool_name、redacted_args、status、result_ref、cost、timing |
| Evidence / Claim | 见证据协议；Claim 与 Evidence 多对多关联 |
| TaskEvent | task_id、sequence、type、payload_ref、timestamp |
| Report | id、task_id、version、markdown、claim_ids、limitations、created_at |
| Memory | id、scope、snapshot_id、verified_claims、source_refs、expires_at |
| Checkpoint | 使用所选 LangGraph 持久 checkpointer 的存储结构，不另造不兼容格式 |

任务状态：queued → running → succeeded / partial / failed / cancelled；running 可进入 waiting_input，用户补充后回到 queued。依赖服务不可用为 failed 或等待重试，不能伪装 succeeded。报告 succeeded 表示流程满足内部验收，不等价于客观结论全部正确；评测另算质量。

| API | 语义 |
|---|---|
| POST /repositories | 提交公开 GitHub URL/ref 或受控工作目录中的仓库 ID；异步返回导入任务 |
| GET /repositories/{id} | 查询导入、索引状态和排除项 |
| POST /tasks | 创建分析任务；支持客户端幂等键，相同键不同请求体返回冲突 |
| GET /tasks/{id} | 查询状态、预算、子任务及错误 |
| GET /tasks/{id}/events | SSE；sequence 为事件 ID，支持断线后补发 |
| POST /tasks/{id}/cancel | 请求取消，重复调用保持幂等 |
| POST /tasks/{id}/resume | 仅恢复 waiting_input 或可恢复的 partial 任务；保留已用预算 |
| GET /tasks/{id}/report | 查询报告及引用 |
| GET /evidence/{id} | 返回来源、定位信息和证据片段 |

V1 单用户本地使用，本地路径只能引用已登记的工作目录；对外部署前启用认证、资源归属与请求限流，不能直接开放任意本机路径。API 密钥放环境配置，日志脱敏；仓库和网页中的指令只作为数据，不能修改系统策略或工具权限。

## 11. 评测设计

建立 3 个公开 Python 仓库固定 commit、每库 10 个问题的初始任务集，覆盖架构、实现追踪、文档对照及证据不足场景；规模用于初步验证，不代表对所有大型项目的泛化表现。至少一个仓库保留为未用于调参的测试仓库。每道题人工记录可接受结论、关键文件/符号、证据和判断规则。

| 指标 | 定义 |
|---|---|
| 质量完成率 | 满足预先制定的答案要点和证据标准的任务数 / 全部任务数；超时失败仍计分母 |
| 执行完成率 | 正常产生报告的任务数 / 全部任务数；与质量完成率分开 |
| 证据准确率 | 抽查中确实支持对应结论的引用数 / 全部抽查引用数 |
| 关键证据 Recall@K | 进入前 K 个候选的人工标注关键证据数 / 标注关键证据总数 |
| 关键事实覆盖率 | 有正确引用的关键事实数 / 标注要求的关键事实总数 |
| 效率与费用 | 单任务端到端耗时、中位数与 P95、输入/输出 token、Embedding/重排等成本；模型价格未知则报告调用量而非编造金额 |
| 恢复效果 | 在预设中断位置恢复完成的任务数 / 注入中断的任务数；同时统计重复调用 |
| 采集效果 | 正文提取通过人工标准的页面数 / 全部选定页面数；单报静态与动态网页 |

基线 A：单 Agent，同模型、同工具与同预算。基线 B：无检索的直接回答，作为能力下限参考，不作为多 Agent 优势的唯一依据。主系统 C：协调式多 Agent。分别评测关键词 vs 混合检索、有/无重排、有/无压缩。压缩既看 token 节省，也看事实遗漏。

固定语料快照、提示词版本、工具集和预算上限；保存逐题结果。最终里程碑完整任务集每配置重复 3 次；开发中只跑少量回归问题。报告提升时区分百分点与相对百分比，披露样本量、失败和成本。图片中的 35%、40%、25%、30%、85%+、90%+ 均不是本项目已取得的数据或硬性保证。

## 12. 分阶段交付与验收

| 阶段 | 交付 | 验收 |
|---|---|---|
| V1 代码研读 | 仓库快照、ast 索引、关键词工具、单 Agent、FastAPI、最小页面、SQLite | 同一小型仓库 5 个问题，能定位代码并验证引用；缺资料不编造；工具失败有可读错误 |
| V2 协同调研 | LangGraph 调度、文档 Agent、Reviewer、报告、Milvus 混合检索与重排开关 | 同一批问题完成单/多 Agent 对比；记录补查、冲突和停止条件；所有引用可打开 |
| V3 工程化 | worker、Redis、PostgreSQL、持久检查点、SSE 补发、缓存、Playwright、MCP、Docker Compose | worker 中途终止能恢复；重复消息不重复产报告；取消和超时有效；动态资料抓取失败有降级说明 |
| V4 评测与展示 | 固定任务集、对比报告、演示录像脚本、部署说明、简历素材 | 第三方可按步骤重跑；仅填写实测成果；能解释失败案例与技术取舍 |

每阶段先完成端到端流程再扩展组件。首次模型接入需要用户在本地设置凭据，不在聊天中提交；没有模型时工具单元与接口可以验证，但不声称 Agent 已完成真实调研。若资源不足，先缩减索引范围或关闭可选重排，记录降级，不先扩机器堆服务。

建议演示顺序：输入陌生仓库问题 → 展示任务分工 → 查看代码与文档证据 → 展示一次有依据的补查 → 打开报告引用 → 展示预录或现场中断恢复 → 展示与单 Agent 的实测对比。

## 13. 关键风险与实现者可自行决定的部分

风险包括代码动态特性导致静态分析不全、文档版本错配、重复检索推高成本、压缩丢失细节、网页结构变化和模型自评失真。对应措施是标注不确定性、固定版本、限制预算、保留原始证据、采集分级降级与人工评测。

实现者可自行选择兼容版本、ORM、具体队列消费者实现、Embedding/reranker 型号、CSS 样式、目录组织和缓存淘汰策略，但必须记录版本并保持数据及接口契约。API 密钥、可用模型预算及机器资源在进入真实运行前配置确认；不把这些未知量写成已经可用。

本稿经确认后再编写具体实施计划和代码。设计文档的存在不代表平台已搭建、指标已达成或技术栈已在用户电脑验证。

## 14. 官方技术参考

下列资料用于校验组件职责，具体 API 与版本以实现时锁定依赖为准：

- LangGraph：https://github.com/langchain-ai/langgraph
- LangGraph persistence：https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/persistence.mdx
- Milvus 全文检索：https://milvus.io/docs/full-text-search.md
- Milvus 混合检索：https://milvus.io/docs/multi-vector-search.md
- Playwright Python：https://playwright.dev/python/docs/intro
- Agent 工具与评测：https://www.anthropic.com/research/writing-tools-for-agents
- Agent 评测：https://www.anthropic.com/research/demystifying-evals-for-ai-agents
