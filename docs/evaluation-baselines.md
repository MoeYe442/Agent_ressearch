# V4.1 评测基线（0.9.0）

这轮交付代码和编译检查，没有运行测试、服务、模型或评测。没有已测得的节省比例、质量提升或部署验收结论。

## 可选配置

| CLI 配置 | 行为 |
|---|---|
| `direct` | 只给模型仓库来源、commit 和问题，无源码、网页、工具或检索结果 |
| `single_keyword` | 原单 Agent 关键词调查 |
| `single_keyword_compressed` | 同上，启用历史工具片段压缩 |
| `collaborative_keyword` / `collaborative_keyword_compressed` | 协作关键词调查，压缩关闭 / 开启 |
| `collaborative_hybrid` / `collaborative_hybrid_compressed` | 协作混合检索，压缩关闭 / 开启 |
| `collaborative_hybrid_rerank` / `collaborative_hybrid_rerank_compressed` | 协作混合检索与重排，压缩关闭 / 开启 |

默认计划仍只有原来的两项关键词配置，避免无意增加收费任务。混合检索与重排需要配置真实服务。

```powershell
# 仅冻结计划，不运行模型；示例取一个开发问题，每配置一次。
# 将 CASE_ID 换成 eval/benchmark-v1.json 中 development 仓库的一道题 ID。
.\.venv\Scripts\python -m repolens.evaluate plan --suite eval/benchmark-v1.json --directory .data/evaluations/baselines --case-id CASE_ID --repeats 1 --configurations direct single_keyword single_keyword_compressed collaborative_keyword collaborative_keyword_compressed
```

随后按 [evaluation.md](evaluation.md) 执行、评分与导出。当前标注仍为草案，开发运行需显式 `--allow-draft`；正式质量率仍为 null。完整30题×9配置×3次为810个调查任务，可能每任务多次模型请求，不能直接当作810次调用。不要在未确认实际预算时直接运行完整矩阵。

## 无检索直接回答

API `POST /tasks` 增加 `mode: "direct"`。为兼容现有检索字段，其 `retrieval_mode` 只能为 `keyword`，但该模式不会使用关键词工具；`rerank`、`context_compression` 必须为 false，`document_ids` 必须为空。不兼容请求在提交前拒绝。普通用户也可从分析模式下拉框选取；页面明确显示“未经源码核验”。

同一模型、原有30次调用/60000 token/900秒上限、原有持久预算与模型响应缓存。没有工具定义，模型请求工具只会触发结构化输出纠正，绝不执行工具。直接回答必须没有引用，claim 状态只能为 unverified。`succeeded` 仅表示生成合法结构化回答；无法对照固定 commit 的内容保证正确，也不能获得证据支持的质量通过。

仓库仍导入为固定快照，供所有配置共用和核对标注文件；导入/建库在调查计时之外。直接模式的模型仅获得来源和 commit 身份，不获得这些文件内容。模型已有知识可能包含公开仓库内容，不能把该基线视作完全未知仓库实验。

## 压缩规则

任务字段 `context_compression: true` 默认关闭，纳入幂等请求与恢复签名。算法 `tool_history_rule_v1` 仅作用于单 Agent / 协作中代码和文档调查的工具历史，planner、reviewer 的输入不变。

当消息序列 UTF-8 JSON 大于32 KiB，尝试缩减较早的工具响应，完整保留最新两个工具响应、system/user 问题、assistant 工具调用及对应 tool 消息。保留每条响应全部顶层 evidence_ids、状态、错误、调用 ID；data 的字符串最多240字符、列表最多8项、对象最多20键、嵌套最多4层，优先位置字段。只有实际变短才替换，同一响应只压缩一次。完整工具结果仍由原有持久工具日志/缓存保存，可用证据 ID 和读取工具再次取原文。

这是会丢片段的规则压缩，不是语义摘要或长期记忆。没有适合压缩的历史时开关不会产生变化，也不保证请求总大小始终低于32 KiB；最近结果和问题仍完整保留。证据 ID 保留并不代表相关事实仍在模型上下文里。需要用事实覆盖变化评估这种代价。

报告 `context_stats` 保存模型循环轮数、消息字节 before/after 累计值、缩减响应数，协作任务按子任务合并。它不含工具 schema 字节、planner/reviewer、模型内部重试，不是供应商 Token 用量或“无压缩时总费用”的反事实估计。模型与工具重放仍走原有缓存；进程中断后的单节点重建会重新计算该节点统计，不把事件次数累加成收益。

## 人工裁决与比较

每个事实现在分为 `content_correct`（答案是否正确覆盖该事实）和 `passed`（是否有本任务返回的有效位置证据支持），均由独立人工填写。直接回答的 `passed` 固定 false、evidence_ids 为空，`content_correct` 仍需人工判断。每条结论另设 `content_correct`，所有模式均表示对照固定源码后的事实正确性；`supported` 只判断本任务证据支持，直接模式固定 false。检索模式还需逐项判断引用支持程度。请重新生成评分模板，旧模板缺少事实/结论 content_correct 将被拒绝；不修改原始结果和计划。

`answer_correctness_rate` 要求全部事实内容和额外公开结论正确；`answer_fact_coverage_rate` 只统计正确覆盖的事实。`fact_coverage_rate` 统计有来源证据支持的事实，`quality_completion_rate` 同时要求内容、结论、引用通过；直接回答的后两项不能通过。失败且明确无回答的槽位计不通过；未审、导出不全、未执行或坏工件不能悄悄删除，正式率保留 null。

报告 JSON 的 `comparisons` 自动列出 direct→single、single→协作、关键词→混合、无重排→有重排，以及各配置压缩关闭→开启。所有对比使用同一冻结计划的相同 case/repeat，公开 planned/observed/unavailable pairs。质量与覆盖差为百分点；用量完整时才给 input/total token saving fraction，基线为0则 null，负值表示变多。estimated 用量原样披露；`known_usage_contains_estimates` 明确只指已知小计，完整总量仍需全部槽位已知。共享建库单列，不重复计到每道题，也不编造金额。

Markdown/HTML 展示核心对比，JSON 保留全部字段与缺失情况。中位数/P95是完整同题矩阵的描述性分布差，不能解释为每题改善或统计显著性。压缩与不压缩可能生成不同后续工具路径，实际 Token 差包含该行为变化；不会从压缩字节数推导 Token 收益。

修改源码会改变执行指纹，旧运行不能在新版上继续提交；使用新空目录冻结新计划，保留原始运行档案。当前交付仍需后续真实接入、独立标注审查及实际运行验收。
