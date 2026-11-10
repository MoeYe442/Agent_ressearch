# RepoLens V1

Agent_ressearch：多 Agent 开源项目研读与技术调研平台的 V1 单 Agent 基线。

本地 Python 仓库研读工作台：固定快照 → AST / FTS5 检索 → 单 Agent 工具调用 → 结构化报告 → 可点击源码证据。Python 3.12+，FastAPI + SQLite + Jinja2 / 原生 JavaScript。

## Windows PowerShell 启动

在项目根目录运行（当前交付路径为 `D:\code\Agent`）：

```powershell
Set-Location D:\code\Agent
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock
.\.venv\Scripts\python -m pip install --no-build-isolation --no-deps -e .
$env:REPOLENS_WORKSPACE = 'D:\code'
$env:REPOLENS_DATA = 'D:\code\Agent\.data'
.\.venv\Scripts\python -m repolens.main
```

打开 <http://127.0.0.1:8000>。不用激活虚拟环境或修改 PowerShell 执行策略。已安装的交付环境可以直接设置工作目录并运行最后一条命令。

`REPOLENS_WORKSPACE` 是允许导入的根目录。页面输入其下的本地 Python 仓库绝对路径，例如 `D:\code\Agent\tests\fixtures\sample_repo`。导入会登记仓库、复制筛选后的文件、建立索引。每次主动导入创建新快照；同一次提交的网络重试复用登记 ID，后续追问复用原快照。非 Git 目录使用排序内容清单 SHA-256。为避免 Git 配置触发仓库程序，导入不执行任何 Git 命令：只在安全读取 loose SHA-1 commit/tree 元数据，并逐一核对纳入文件的实际字节时才附加 commit。packed objects/refs、gitfile 工作树、SHA-256 Git、内容转换导致的字节差异或无法安全核验时统一使用清单版本，`dirty: null` 表示未知，不把未知标为未提交修改。

## 配置真实模型

停止服务，在同一 PowerShell 窗口设置后重新启动：

```powershell
$env:REPOLENS_MODEL_URL = 'https://your-provider.example/v1'
$env:REPOLENS_MODEL = 'your-tool-calling-model'
$credential = Read-Host 'API key（仅在本机输入）' -AsSecureString
$env:REPOLENS_API_KEY = [System.Net.NetworkCredential]::new('', $credential).Password
.\.venv\Scripts\python -m repolens.main
```

适配器要求服务支持 Chat Completions 格式的 `tools`、`tool_calls`、`tool_choice` 和 `max_tokens`；基础地址追加 `/chat/completions`。不能保证所有兼容服务/模型均符合该协议，协议/鉴权错误会明确失败；不以虚假答案替代。模型只在首次分析时进行实际能力验证，启动本身不产生模型费用。密钥不写入数据库或报告，不在聊天中提交。`.env.example` 仅作变量说明，程序不会自动加载 `.env`。

未配置时页面显示 **未配置模型**，仍可导入索引并验证工具/API；提交模型调查得到 `failed/model_not_configured`。仓库源码和问题会发送给所配置模型服务，因此请只登记你愿意交给该服务研读的仓库。

## 实现范围与约束

- 本轮支持本地 Python 仓库，单用户、单进程、单 worker；仅绑定回环地址，限制 Host / 来源与客户端地址。不要使用多 worker、代理到公网或多个进程共享同一数据库。
- 不执行被分析项目代码，不提供 shell 工具。外部文本不能更改工具权限；工具参数严格校验并固定 snapshot 范围。
- 默认每文件最多 1 MiB、纳入文本最多 100 MiB、快照最多 500 MiB。超大单文件与敏感/二进制/依赖/生成文件记录为排除；总量超限明确失败。明显密钥文件筛选不等于通用秘密检测，先检查自己的仓库内容。
- 每次返回最多执行 8 个工具请求；任务最多 30 次工具、30 次模型、60,000 输入/输出 token 和 15 分钟；限制为上限。输入使用保守 UTF-8 字节上界加协议开销预留，服务返回 usage 时按实际结算；缺失和失败请求使用保守估算，页面用 ≈ 标记，不伪称精确成本。
- 每个读取窗口最多 160 行。索引包含 Python 符号/导入/装饰器行范围和 Markdown 标题，语法错误保留全文检索。FTS5 不可用则明确报依赖错误。
- 引用校验快照、路径、行号与 SHA-256，且模型只能引用本任务实际看到的证据。`references_valid` **不表示语义得到证明**；人工检查引用是否支持结论。内部 `succeeded` 仅表示流程产出合规报告。
- SSE 事件持久化，Last-Event-ID / after 支持补发；刷新通过 URL 的 task_id 恢复页面。未确认提交的快照与幂等键保存在当前标签页 sessionStorage，刷新/重试复用原请求。断开网页不会取消后台任务。取消会在当前模型请求返回或超时后的边界生效，不保证即时中止已发出的网络请求；HTTP 请求有整体 wall-clock 超时，并限制响应正文最多 2 MiB。
- 重启时 running 任务标记 failed/interrupted，旧 queued 重新排队；无跨进程断点恢复。GitHub 导入、多 Agent、LangGraph、Milvus、Redis、MCP 与网页采集均未实现。
- 数据放在 `REPOLENS_DATA`（默认当前目录 `.data`），包含快照、SQLite WAL、事件、工具结果与报告。**先停止服务**，确认数据目录后用 `Remove-Item -LiteralPath 'D:\code\Agent\.data' -Recurse` 清理；会删除所有本地历史。源码不受影响。

## 测试与评测

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m compileall src
```

浏览器测试需 `python -m playwright install chromium`；也可 `$env:REPOLENS_BROWSER_EXECUTABLE='已安装的 Chromium 可执行文件绝对路径'`。浏览器测试启动独立本地测试服务，页面显示测试环境，脚本化模型只存在于 tests 内。截图位于 `test-results`。

真实模型已配置后启动正式服务，运行一次五题回归：

```powershell
.\.venv\Scripts\python -m eval.run --base-url http://127.0.0.1:8000 --tasks eval/tasks.jsonl --output test-results/real-eval.json
```

五题与人工语义判定规则在 `eval/tasks.jsonl`。程序只查证据结构与必需符号，输出 `quality_pass: null` 等待独立人工核验；失败和超时保留分母，未知用量不记成零费用。`synthetic: true` 结果只证明集成可运行，不能证明真实模型质量或性能提升。执行完成率、报告产出率与人工质量完成率分别报告。无价格配置，不估算金额。

设计与实施方案见 `docs`，演示步骤见 `docs/demo.md`，实际测试与边界见 `docs/validation.md`。
