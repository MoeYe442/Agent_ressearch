# V4 可复现评测（0.9.0）

本轮交付评测协议、运行器、人工评分和报告导出，**没有运行测试、评测、模型、服务或容器**。题目和可接受结论属于源码静态核对后的标注草案，仍需独立人工复核。没有真实质量/速度/费用提升数据，不能把编译或旧版synthetic记录当作当前效果。

## 固定语料与题集

题集为`eval/benchmark-v1.json`，每库10题，共30题、60条关键事实。每条事实列出固定commit中的文件/符号/证据范围；source表记录实际文件SHA256、Git blob及行数。原始源码只读查询，没有执行上游代码。

| 仓库 | 固定commit | 分区 |
|---|---|---|
| [Flask](https://github.com/pallets/flask/commit/2c1b30d0503cfb064f1cb252e6614a06915a362a) | `2c1b30d0503cfb064f1cb252e6614a06915a362a` | development |
| [HTTPX](https://github.com/encode/httpx/commit/26d48e0634e6ee9cdc0533996db289ce4b430177) | `26d48e0634e6ee9cdc0533996db289ce4b430177` | development |
| [Click](https://github.com/pallets/click/commit/fd183b2ced1cb5857784fe7fb22f4982f671f098) | `fd183b2ced1cb5857784fe7fb22f4982f671f098` | reserved |

覆盖架构、实现追踪、docstring/代码对照及证据不足。证据不足题考查有限静态证据能说明什么，不能据函数名字证明全仓库不存在某能力。Click是预留调参外分区，作者为标注已读过源码，不是作者盲测；未来实跑必须先冻结模型/提示词/工具/预算，再启用它。

当前`annotation_status=draft_needs_independent_review`。人工核对全部规则后，可另存一份题集，将状态改为`human_approved`并填写`annotation_reviewer`。必须在正式运行计划创建前完成；旧计划内的草案不会因外部题集改动自动升级。程序记录人工声明，不能自行证明复核人身份或独立性。

## 先冻结计划，再显式执行

原生或Compose启动见README与docs/infrastructure.md。API必须与当前源码同版、真实模型已配置，运行器只连接环回地址，不读取模型密钥，不启动服务。共享工作目录、GitHub网络配额与模型预算由运行者在本地准备；实验期间不修改源码、更新环境、切模型或重建索引。

```powershell
# 只创建计划，不联网、不调用模型；新目录必须为空。
.\.venv\Scripts\python -m repolens.evaluate plan --suite eval/benchmark-v1.json --directory .data/evaluations/dev-one --case-id flask-wsgi --repeats 1 --configurations single_keyword

# 以下命令会提交调查并可能产生真实模型费用；本轮没有执行。
.\.venv\Scripts\python -m repolens.evaluate run --directory .data/evaluations/dev-one --execute --allow-draft
```

草案开发运行需要显式`--allow-draft`，不产生正式质量完成率。默认计划只含20道development题，single_keyword与collaborative_keyword各重复3次，即120个调查；全部30题两配置三次重复为180个调查，不是180次模型调用，每个调查仍可使用自身30次模型调用预算。先用单题开发计划检查真实环境。

正式全题示例使用人工批准后的题集文件，包含reserved必须填写`--protocol-id`作为设置已冻结的操作声明：

```powershell
.\.venv\Scripts\python -m repolens.evaluate plan --suite D:/evaluation/benchmark-approved.json --directory .data/evaluations/final --partition all --protocol-id frozen-protocol-v1 --repeats 3 --configurations single_keyword collaborative_keyword
.\.venv\Scripts\python -m repolens.evaluate run --directory .data/evaluations/final --execute
```

新增 `direct`、`single_keyword_compressed` 和全部协作配置的 `_compressed` 变体；混合/重排需真实服务。默认仍为两项关键词配置，完整配置表、人工内容/来源双裁决与比较口径见[evaluation-baselines.md](evaluation-baselines.md)。实现基线不代表已完成实际消融实验。

## 运行记录与中断

`plan.json`冻结题集内容/hash、案例、配置、重复次数、API地址和timeout；默认每题960秒观察窗口，不随runner重启延长。`context.json`记录API公开的模型标签、预算与执行指纹；指纹包含去密设置、源码、工具schema和依赖版本。每题前重新核对，变化则停止，不能混用不同配置。

每仓库导入复用同一固定commit快照，并核对题集源文件SHA256；每次重复沿用该manifest。索引只构建一次，单独列共享建库用量，不每题重复相加。导入/建库耗时不混入题目观察耗时。

固定每个case/config/repeat槽位，任务提交使用run ID与槽位派生的稳定幂等键；POST响应丢失时查询`GET /evaluation/tasks/{key}`，不换key重建任务。提交结果未知、取消未完成或配置变更时停止后续提交，重新运行同一条run命令观察原任务。Ctrl+C停止runner不代表取消服务器任务；仍受原任务预算限制。

超时先请求取消；在途请求不保证立即中止。取消尚未完成时保留intent并退出，后续继续观察，不增加任务轮次。不自动调用任务resume接口，也不重做已封存终态，避免选择性挑最好结果。若原任务已中断partial，就如实计入本轮partial。

终态报告/引用导出另有120秒只读窗口，不使用已过期的任务观察deadline，也不会延长模型执行。导出失败仍保留已知终态、用量与观察耗时，但不允许不完整材料质量通过。再次run时，只对带导出错误的原终态执行GET重新收集，核对原status/attempt/epoch/usage未改变，不提交、恢复或取消调查。重收集计数与时间保留，观察耗时包含等待恢复的时间；新工件hash会使旧评分失效。若材料始终无法完整导出，正式质量率保持null，不自动收费重做题目。

计划、intent与结果采用校验封套、临时文件/fsync后原子发布；同一目录用OS文件锁限制一个runner，崩溃后由OS释放。支持普通本地NTFS/POSIX文件系统，不宣称网络文件系统或断电后全盘数据无损。校验和用于一致性，不是数字签名，不能抵抗操作者重写全部工件。

## 人工评分

```powershell
.\.venv\Scripts\python -m repolens.evaluate review-template --directory .data/evaluations/final --output .data/evaluations/final/review-1.json
```

评分包包含问题、仓库/commit、关键事实、实际公开结论、引用与正文。仅修改`reviewer`、`independent_attested`、`overall_note`及事实/结论/引用的裁决、支持ID和原因，不修改原始问题/正文/键。每项裁决为true/false/null；null表示未审。给定裁决须填写reason；事实的 `content_correct` 判断内容是否正确覆盖，`passed` 判断是否有实际返回且落在预定范围内的证据支持；直接模式的 `passed` 固定 false，但仍人工判断内容。旧评分模板需重新生成，原始结果与计划保留。

每条公开结论使用 content_correct 判断内容、supported 判断本任务证据支持；直接模式 supported 固定 false。每个“结论—引用”关系再分别判断支持程度，防止只满足少数gold事实却忽略额外错误。结果hash、run、槽位、问题、正文均绑定；旧记录、重复评分槽位、错题或改写源文本会拒绝。评分不是LLM自评；独立性为人工声明，系统不能认证真实身份。

## 导出与指标含义

```powershell
# 只读本地工件，不联网；output使用新的空目录。
.\.venv\Scripts\python -m repolens.evaluate report --directory .data/evaluations/final --reviews .data/evaluations/final/review-1.json --output .data/evaluations/final/report-1
```

输出JSON、CSV、Markdown及无脚本HTML。可以多次传`--reviews`合并互不重复的分批评分文件；重复槽位拒绝。保留原始rows/preparations及评分包，第三方可重算，不读取旧summary充当本次结果。

- 固定分母来自计划；缺失、坏工件、超时、取消、失败都不会悄悄删除。未执行或不完整运行的完成率为null，并单列进度与错误数。
- 结构命中只表示引用窗口覆盖标注位置，不代表答案真实正确。正式质量率需批准的题集、完整运行、真实环境及完整人工裁决；草案/合成运行的正式质量值始终null。
- 无报告且明确失败的完整槽位不能质量通过；有报告但未审的质量仍未知。导出不完整则保留已知用量，质量无法通过；runner不自动收费重做已封存任务。
- 引用准确率以人工已审的结论—引用关系为样本，同时披露已审/全部引用数，不把样本当全体。
- 中位数/P95使用已观察到的终态槽位，包含失败，披露样本数；P95用nearest-rank。client观察耗时含队列、轮询、导出及runner停机时间，不是纯模型推理耗时。
- 未知用量不填0；已知小计与完整总量分开，缺一槽位就不发布完整总量。estimated明确保留，Embedding/Rerank已在任务预算中，建库用量另外列一次。
- 没有核验过的供应商价格，不填金额。单/协作质量差为百分点，只有完整同计划且人工评分齐备时计算；三次重复不是三个独立仓库，不宣称统计显著或泛化结论。

旧`eval.run/compare/retrieval/recovery`保留作为历史开发工具；它们的格式与新V4封套不同，不自动转成正式结果。当前源码仅完成编译和静态审查，真实指标均待运行后生成。

静态审查的重要问题已修复：不完整导出不再丢已知终态/用量，晚于deadline重启可单独读取原终态，题目首尾空白在冻结前按API行为规范化。暂缓两项轻微问题：校验和有效但嵌套类型错误的工件可能使整份报告退出；summary的estimated字段只汇总已知用量，需结合unknown槽位及null完整总量解读；0.9另提供明确命名的known_usage_contains_estimates，兼容保留estimated。执行记录见[v4-execution.md](v4-execution.md)。

0.9.1 已处理前述嵌套类型容错待办：先校验结果、共享配置与人工评分结构，再按单题无效或共享输入错误处理；见[evaluation-hardening.md](evaluation-hardening.md)。此前记录为历史交付状态。
