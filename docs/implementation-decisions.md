# 实施决策与审查修复

用户授权：2026-11-10，按提供的 V1 实施方案执行。本文汇总过程记录中所有 Ruling。

1. 在当前空目录 `D:\code\Agent` 建立项目；没有 Git，按方案允许的方式保留本地源码并 ZIP 交付，不初始化远程或创建分支。代价：没有 Git 提交历史；实施记录、源码与测试输出一并交付。
2. 以本次实施计划界定 V1，较大设计文档中的 GitHub 导入、多 Agent 和跨进程恢复维持后续阶段。代价：V1 范围小于最终平台愿景，与计划一致。
3. 导入返回持久化 ID，在单 worker 后台复制/索引；整个索引完成后原子发布 ready。代价：导入和分析共用串行队列；这是 V1 的单 worker 边界。
4. Git/Bash 专属进度脚本不适用于没有 Git 的 Windows 空目录，使用本地 ledger 和测试输出记录进度。代价：记录不能从 Git log 恢复，因此将 ledger 复制到交付文档保存。
5. **安全性优先于计划原拟的 Git 状态调用。** 独立审查复现了 `git status` 触发仓库 fsmonitor 程序，故产品完全不调用 Git 命令。只安全读取和校验 loose SHA-1 commit/tree 元数据；未能核验则清单版本。代价：packed Git / gitfile / SHA-256 Git 的 commit 展示延期，仓库研读和引用继续可用，不误标纯 commit。
6. 依据审查，把缺失本地路径的 500 错误提升为需要修复的可用性问题，改成稳定的 repository_not_found。代价：无功能缩减。
7. 模型能力在首次真实请求验证，启动不进行收费网络探测；协议不支持时明确失败。代价：模型兼容性错误在首次分析呈现，README 明示适配范围。

## 一次独立审查及修复

独立 reviewer 只读检查全部工程并复现以下问题；实现者补回归测试、观察失败后修复。最终通过测试确认，不把作者测试称为第二次独立审查。

| 问题 | 修复 | 回归证据 |
|---|---|---|
| Git fsmonitor 任意程序触发 | 不调用 Git；受限纯数据解析 | test_snapshot_never_runs_repository_fsmonitor |
| NTFS junction 在检查与打开间替换目录 | Windows 已打开句柄最终路径验证、拒绝 reparse；POSIX 逐层 no-follow descriptor | test_rejects_parent_junction_swap_before_file_open |
| ignored 文件及字节变化被误标 commit | 每个纳入文件的 Git blob hash 与 commit tree 对照；不能核验回退 manifest | test_ignored_source_does_not_claim_clean_commit、test_clean_git_snapshot_retains_verified_commit、test_packed_git_falls_back_without_claiming_dirty |
| ready 与索引完成写入分离 | 索引摘要、ready 在同一事务，旧不完整导入明确 interrupted | test_ready_without_index_is_not_stuck_importing |
| report 与任务终态写入分离 | report、终态和最后事件同事务；读取再检查一致性 | test_final_state_report_event_are_atomic |
| 持续滴流绕过 HTTP inactivity 超时 | asyncio.timeout 限定整个网络请求，流式限制响应总量 | test_provider_stream_obeys_total_deadline |
| 丢响应后重试创建额外任务 | sessionStorage 保存 intent、快照与幂等键；导入/任务均幂等 | test_lost_submission_response_reuses_intent_after_refresh、test_repository_import_retry_is_idempotent |
| 旧异步请求覆盖新任务 | 每处异步提交校验 generation/任务 ID，证据额外校验请求 ID/快照 | test_stale_evidence_response_cannot_overwrite_new_task |
| form-feed 等导致 AST 行号错位 | 共用仅按 CR/LF/CRLF 切分的 physical_lines | test_physical_lines_match_python_ast |
| Markdown 正文伪造证据 marker | 转义模型自由文本，仅从已验证 ID 生成引用标记 | test_export_cannot_forge_evidence_markers |
| 五题 synthetic 只测执行、结构全失败 | 独立 question-aware 正向 fixture，逐题结构必须通过，保留错误答案负向测试 | test_five_question_synthetic_regression、test_structure_check_cannot_grant_semantic_quality |
| 不存在路径返回 500 | repository_not_found 明确错误 | test_missing_path_is_explicit_validation_error |

没有遗留 Critical / Important 审查项，也没有推迟的 Minor 项。Windows 当前环境已验证；POSIX 安全读取分支未在本轮 Windows 会话运行，不能声称跨平台验收。

审查不判断：真实模型质量/费用（未配置供应商）；已明确延期的 GitHub、多 Agent、跨进程恢复；这些均是既定验收边界，不作为通过测试的事实。

## 实现参考

打开后验证句柄使用 [Microsoft CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew) 和 [GetFinalPathNameByHandleW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew)。Git 数据解析依据 [Git Objects](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects) 的对象头、树和 blob 格式；运行时不执行文档示例命令。
