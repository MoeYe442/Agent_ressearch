# V4 Evaluation and Showcase Implementation Plan

> Use superpowers:executing-plans inline, one final fresh-context static reviewer. AGENT.md/user override: compile only, no tests or evaluation runs.

**Goal:** 固定公开仓库/commit的30题评测协议、同配置三次重复的可复现运行器、人工评分与诚实汇总、演示/部署/简历素材。
**Spec:** docs/RepoLens-Design-v1.md §11/12。上一轮V3.2已完成并推送，按原方案顺序进入V4。
**Architecture:** 锁定题集、仓库commit、关键证据与人工规则；显式CLI才连接现有API并产生费用。清单计划固定所有case/config/repeat组合，逐题持久化、稳定幂等键，失败/丢失仍保留分母。评分导入绑定run/row/report hash，结构/流程与语义分开；报告从原始记录和人工裁决重算，不接受预填summary。

## Constraints
- 不运行测试、评测、服务、容器或模型；只编译与静态配置检查。公开源码只读查证用于题目标注，不运行上游代码。
- 不伪造真实指标、效果提升、费用或质量分。未运行/未标注均明确null，失败保留固定分母。
- SQLite/PostgreSQL和现有API兼容，不引入数据库/模型执行行为变更。
- 保留用户 .gitignore/AGENT.md；复用当前目录新分支；不推送/合并。
- 主比较single keyword vs collaborative keyword，共同模型/快照/预算；可选已有hybrid/rerank。未实现直接回答/压缩基线必须明确为不支持，不能伪装为已跑。

## Tasks
- [x] 1. 三个公开Python仓库固定commit、每库10题，标记一个未用于调参分区；关键文件/符号/证据窗口/可接受结论/不足场景规则与来源hash。
- [x] 2. 评测协议schema、固定运行矩阵/幂等运行器，结果与人工评分绑定原始证据，失败/中断/缺失不丢行。
- [x] 3. 汇总/CSV/Markdown报告、质量未知/未运行/估算/费用未知、配对差异/延迟与token披露，CLI帮助及操作说明。
- [x] 4. 演示录像分镜、项目架构/部署入口、简历与面试素材（仅已实现能力，实测指标留空）。
- [x] 5. 编译与静态检查、一次最终静态审查、修复、归档与本地提交。

## Review Focus
1. 固定分母、重复/缺失/失败/中断、不完整输出与旧run混用；不能筛掉失败或补零用量。
2. 固定snapshot/commit/模型/预算/config与重复次数，稳定幂等提交、超时取消和恢复runner不产生重复收费。
3. 人工评分绑定run/row/result hash及事实/引用、旧/重复/篡改评分拒绝；结构匹配不能冒充语义正确。
4. 空集/单题/待人工/估算/不同样本/混合模型/合成记录下的summary、P95/百分比/配对差异含义与可比较性。
5. 外部源码/URL与输入文件均按非可信数据处理，结果包转义/路径/密钥安全；部署、演示、简历不宣称未运行效果或不支持基线。
