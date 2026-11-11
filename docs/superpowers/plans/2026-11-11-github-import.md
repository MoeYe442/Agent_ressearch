# RepoLens Public GitHub Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户输入公开 Python GitHub 仓库 HTTPS 地址及可选 ref，获得固定 commit、可验证源码快照，并复用现有索引、任务、报告及证据工作台。

**Architecture:** 在现有单体中增加受限 GitHub HTTP 适配器与归档导入器。先取得公开仓库信息、commit 和对应 Git tree，再下载固定 SHA 的源码归档；只把经过路径、类型、体积和 blob hash 校验的允许文本写入快照。后台导入、SQLite 原子 ready 发布及分析工具链沿用 V1。

**Tech Stack:** 现有 Python 3.12、httpx、FastAPI、Pydantic、SQLite、pytest、Playwright；归档使用标准库 zipfile。保持现有锁定依赖，无 Git clone、shell、解压程序或被分析代码执行。

**Spec:** [已确认项目设计](../../RepoLens-Design-v1.md)，尤其第 2、5、7、8、10、12 节；[V1 计划的后续顺序](../../RepoLens-V1-Implementation-Plan.md)。本计划落实其中独立的“公开 GitHub 导入”增量，不把后续 LangGraph 等阶段提前纳入。

## Current State

- 基线 main / origin/main：`9d26ea6`；工作区检查时干净。
- V1 已有本地导入、过滤快照、AST/FTS5、受限工具、证据校验、模型循环、单 worker、持久任务/SSE、幂等和浏览器工作台。
- 最近已验证 64 项测试；模型未配置，尚无真实模型质量结果。
- `RepositorySnapshot` 以 Pydantic JSON 存 SQLite；新增字段提供默认值，旧数据可读，不重建数据库。
- 当前 `/repositories` 只接受 path；新接口保持旧请求兼容。

## Scope and Implementation Decisions

采用 GitHub REST API + 固定 SHA 归档下载。单纯 shallow clone 会引入额外 Git 配置、传输与工作树安全边界；逐文件 Contents API 会显著增加大仓库请求数。本轮选择归档批量获取、Git tree 对照纳入文本，保留现有只读模型。

仅接受 `https://github.com/OWNER/REPO`，允许结尾 `.git` 或 `/`；不接受 SSH URL、Enterprise、自定义主机、凭据、查询串、片段或含 tree/blob 的页面地址。ref 用单独字段传入，可为空（默认分支）、分支、标签或完整 commit SHA。解析成功后后续下载和证据均绑定解析出的 commit。

不支持私有仓库、OAuth、子模块递归、LFS 拉取、任意网址下载或完整 Git 历史。仓库元数据标记 private 时明确拒绝。可选 GitHub token 仅用于公开仓库读取及额度；不在聊天、数据库、事件、报告或归档请求中暴露。

GitHub 归档可能受 export-ignore / export-subst / LFS 设置影响，不能仅凭 URL 中的 SHA 就把任何下载内容标成 commit 原文。纳入文件逐一计算 Git blob hash，与该 commit 的 Git tree 对照；不匹配明确失败。被归档省略、子模块与 LFS 等边界写入排除项或限制。tree 被截断时明确拒绝本轮导入，不静默当作完整树。

## Global Constraints

- 保持 V1 本地导入和现有数据库兼容；64 项基线测试必须继续通过。
- 只读分析，不执行被分析项目代码；Executor 不提供任意 shell。
- 快照最多 500 MB，纳入索引文本总量最多 100 MB，单文本文件最多 1 MB；初始排除规则沿用 V1。
- 新增下载压缩包上限默认 100 MiB、归档全部成员声明解压总量上限 500 MiB、归档成员数上限 50,000。限额可在 Settings 中调小以测试，不允许凭响应头跳过实际流量计数。
- GitHub 元数据响应最多 16 MiB，单次导入所有 HTTP 操作共用 180 秒 wall-clock 限制；不能用不断滴流绕过超时。单请求最多 30 秒，网络瞬态错误最多额外重试两次，重试消耗同一总时限。
- 固定 HTTPS 网络目的地为 api.github.com 和 codeload.github.com，严格校验跳转目的地、TLS 和 URL；不接受 API 返回的任意 URL 直接请求。禁用环境代理继承，不把认证头发送到归档主机。私有/回环/链路本地解析地址拒绝；不宣称 DNS 预检可以替代 TLS 与实际连接安全。
- 403/429 限流、404 仓库或 ref 不存在、网络/超时、压缩包非法和 hash 不匹配分别给稳定 error_code；限流不长期阻塞 worker 等待，不伪装成功。
- 不调用 extractall；逐个检查成员路径后受控写入，只允许普通文件和目录。拒绝绝对路径、`..`、反斜杠、驱动器/ADS、Windows 保留名、尾随点/空格、规范化或大小写冲突与重复文件。
- 符号链接、硬链接语义和特殊文件不落地；子模块不跟随。归档仅接受一个顶层包装目录。失败清理只针对本次生成 ID 对应的下载和快照，不触碰其他任务数据。
- 导入完成前保持 importing；索引、摘要和 ready 原子发布，重启中断与 V1 的明确失败语义一致。
- 页面不把测试模型、fixture 或示例数据标为真实调查。真实 GitHub 导入验收不等于真实模型分析验收。

## Review Focus

1. 恶意 URL / redirect / 认证头传播不能导致访问任意目的地或泄露 token；Task 1 的网络适配器测试覆盖。
2. ZIP traversal、符号链接、Windows 特殊路径、重复项、解压炸弹不能写出快照根目录或绕过体积限制；Task 2 的归档测试覆盖。
3. 分支在导入期间移动、归档有 export-subst、tree 截断时，commit 与原文不能错配；Task 1、2 的 SHA 固定和 blob 对照测试覆盖。
4. 丢响应重试、进程退出、旧记录读取不能重复登记、错误 ready 或破坏本地导入；Task 3、4 的持久化及浏览器测试覆盖。
5. 断网、限流、慢速流和未配置真实模型时，状态和界面必须如实说明失败与验收边界；Task 1、3、4 覆盖。

## File Structure

| 文件 | 职责 |
|---|---|
| src/repolens/github_client.py | GitHub 地址/ref 解析、受限请求、公开元数据、固定 commit/tree 与受限归档下载 |
| src/repolens/github_import.py | 安全 ZIP 遍历、过滤、Git blob 校验、构造快照、失败清理 |
| src/repolens/repositories.py | 提取共享筛选和快照写入单元，保持本地入口安全约束 |
| src/repolens/config.py、models.py | 导入限额、可选 token、兼容的来源/ref/归档元数据 |
| src/repolens/tasks.py、api.py | 持久导入来源、校验互斥请求、幂等、后台执行及错误 |
| templates/workspace.html、static/workspace.js、workspace.css | 本地/GitHub 来源切换、ref、进度/错误、来源版本与幂等恢复 |
| tests/test_github_client.py、test_github_import.py、test_github_api.py | 网络、归档、数据与 API 回归 |
| tests/browser/test_github_workspace.py | GitHub 表单、证据、刷新重试及窄屏验收 |
| README.md、.env.example、docs/github-import.md | 使用范围、配置、限制与本轮实测记录 |

### Task 1: 固定版本的受限 GitHub 客户端

**Interfaces:** `GitHubSource(url: str, owner: str, repo: str, requested_ref: str | None)`；`ResolvedGitHubSource(source, commit_sha, tree_sha, entries)`；`GitHubClient.resolve(source) -> ResolvedGitHubSource`；`download_archive(resolved, destination: Path) -> archive_sha256`。客户端可注入 httpx transport 测试，不提供可配置任意 API 根地址的生产入口。

- [ ] 写 `test_accepts_only_public_github_url_forms`、`test_ref_with_slash_is_encoded_once`、`test_resolves_default_branch_tag_and_sha`。断言 URL 规范化、恶意输入拒绝、先解析 ref 后只用完整 SHA 下载。
- [ ] 写 `test_rejects_private_repo_and_truncated_tree`、`test_redirect_allowlist_and_token_isolation`、`test_rate_limit_and_not_found_are_explicit`。检查未向第三方主机或 codeload 发送认证头，body 与错误不泄露 token。
- [ ] 写 `test_download_counts_actual_bytes`、`test_metadata_size_limit`、`test_trickling_response_hits_total_deadline`、`test_retries_share_import_deadline`，用小限额和受控 HTTP 边界验证实际读入限制与整体超时。
- [ ] 运行 `python -m pytest tests/test_github_client.py -q`，先确认缺失实现导致失败，再实现 Settings 和客户端；同命令全部通过后提交。

### Task 2: 可验证的安全源码归档快照

**Interfaces:** `import_github_snapshot(resolved, archive_path: Path, settings: Settings, snapshot_id: str) -> RepositorySnapshot`。新增 snapshot 字段 `source_type="local"`、`requested_ref=None`、`archive_hash=None`；GitHub snapshot.source 是规范化 HTTPS 仓库 URL，commit_sha 是已校验的 SHA。共享过滤器只对输入文件元数据作决定，不绕过本地 checked_repo / secure_read。

- [ ] 用 Python 内存生成微型 ZIP，写 `test_imports_python_and_documentation_with_commit_evidence`、`test_changed_branch_does_not_change_resolved_snapshot`；核对 fixture 原文字节、manifest、Git blob hash 和 evidence.commit_sha。
- [ ] 写参数化 `test_rejects_archive_path_escape`、`test_rejects_windows_aliases_and_duplicate_paths`、`test_skips_links_special_files_and_secrets`；断言快照以外没有新增文件，错误项可定位且不含密钥内容。
- [ ] 写 `test_archive_member_count_and_unpacked_limit`、`test_archive_file_and_text_limits`、`test_mismatched_blob_rejected`、`test_missing_archive_source_is_recorded`、`test_failed_import_cleans_only_its_own_files`。
- [ ] 运行 `python -m pytest tests/test_github_import.py -q`，确认失败后实现；没有通用解压操作，没有链接落地或执行权限传播。
- [ ] 运行 `python -m pytest tests/test_github_import.py tests/test_repositories.py tests/test_review_regressions.py tests/test_evidence.py -q`，新测试和本地安全回归全部通过后提交。

### Task 3: 持久 API、幂等及后台导入

**Interfaces:** `POST /repositories` 接受旧 `{path, idempotency_key?}` 或新 `{github_url, ref?, idempotency_key?}`，来源必须且只能选一个；本地 path 请求不得携带 ref。返回 202 和既有 snapshot 形状。`TaskService.import_github_repository(url, ref, idempotency_key)` 持久化规范化来源及 ref；相同键不同来源或 ref 返回 409。GET 返回来源、请求 ref、解析 commit、状态与错误。

- [ ] 写 `test_local_import_request_remains_compatible`、`test_rejects_ambiguous_source_and_local_ref`、`test_github_import_returns_before_download_completes`。
- [ ] 写 `test_idempotency_covers_url_and_ref`、`test_import_error_is_persisted`、`test_restart_marks_network_import_interrupted`、`test_old_snapshot_json_loads_with_defaults`、`test_github_report_citation_preserves_commit`。
- [ ] 运行 `python -m pytest tests/test_github_api.py -q`，确认失败后实现 source 路由与持久数据；数据迁移使用字段默认值，不能删除旧数据或重置任务预算。
- [ ] 导入失败依然返回可查询 ID；下载/校验不占用 HTTP 主事件循环；ready 复用已有原子索引发布机制。
- [ ] 运行 `python -m pytest tests/test_github_api.py tests/test_api.py tests/test_tasks.py -q`，全部通过后提交。

### Task 4: 工作台、可复现验收和交付

**Interfaces:** 来源切换默认本地，保留既有 label 和本地浏览器用例；GitHub 模式提供 URL / 可选 ref，沿用问题输入。sessionStorage pending intent 包含来源类型、规范化请求、ref、导入/分析幂等键和已确认 snapshot ID；追问只用 snapshot_id。只对已登记来源构造 GitHub commit permalink，不能直接执行仓库文本里的链接。

- [ ] 写浏览器用例 `test_github_submit_opens_commit_bound_evidence`、`test_github_ref_survives_refresh_retry`、`test_github_provider_import_errors_are_visible`、`test_source_switch_clears_inapplicable_fields`，并在 320/390/736/1024px 检查 GitHub 表单/结果无页面横向溢出。
- [ ] 运行 `python -m pytest tests/browser/test_github_workspace.py -q`，确认缺失 UI 失败后实现最小表单扩展；测试服务标记测试环境，网络响应由测试 transport 提供，不与真实导入混淆。
- [ ] 更新 README、配置示例和 docs/github-import.md：列出 URL/ref 用法、匿名额度限制、可选公开读取 token、归档遗漏/LFS/子模块与 token 不进入聊天的要求。
- [ ] 运行 `python -m pytest -q`、`python -m compileall src`、`python -m pip check`；执行一次独立整体验证，重点审查上列五类输入，重要修复必须先复现再改。
- [ ] 对一个小型公开 Python 仓库做一次真实 GitHub 导入 smoke test，保存 URL、resolved SHA、文件量、归档 hash、耗时及引用校验；网络不允许或被限流则记录具体阻塞，不把 mock 当实测。不要求配置模型、不虚构真实分析成果。
- [ ] 截图检查桌面和手机；保留新旧测试记录。打包排除 .env / token / 运行数据库 / 下载归档 / 缓存 / 虚拟环境；核对 ZIP 源文件 hash。
- [ ] 本地提交本轮完成代码；远程推送在明确授权范围内执行，不 force push。最终说明新增能力、测试、实测和剩余边界。

## Self-Review and Execution Boundary

- 与原设计的公开仓库、固定版本、只读、资源限制、证据与安全边界对应；不扩大为任意 URL 抓取或私有仓库认证项目。
- 四个任务依赖顺序是：解析/下载 → 受限快照 → API 持久队列 → 页面与验收；每个消费者的来源/ref/SHA 类型在前置接口定义。
- Review Focus 五类条件均分配具体测试。本地 64 项基线与最新两类 UI 回归保留。
- 上述网络时限、下载上限和 ZIP 成员数是实现者建议的默认值，未冒充用户逐项指定；必要时在小规模 smoke test 后调整并记录。
- 本文是新增阶段的待审阅实施计划，不是实现完成记录。当前不修改产品代码、不声称 GitHub 导入已可用。
- 延续此前执行方式：同一实现者依次实施，最终一次独立审查，不逐任务派发多个实现者。

## Official References

- [GitHub：下载源码归档与固定 commit](https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives)
- [GitHub REST：commits](https://docs.github.com/en/rest/commits/commits)
- [GitHub REST：repository contents / archives](https://docs.github.com/en/rest/repos/contents)
- [GitHub REST：Git trees](https://docs.github.com/en/rest/git/trees)
