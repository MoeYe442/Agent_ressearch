# V1 验证记录

日期：2026-11-10（Asia/Shanghai）。环境：Windows、Python 3.12.6；版本锁定于 `requirements.lock`。

## 已运行

- 各任务先运行缺失模块/功能的失败测试，再完成实现并运行对应测试。
- 首轮全量 50 passed；独立审查修复后的交付前完整检查：**64 passed，48.82s**（含 10 项浏览器测试）。存在一条 Starlette 对新版 AnyIO 别名的 DeprecationWarning，不影响结果。完整输出见 `test-results/pytest-full.txt`。
- `python -m compileall src`：退出码 0，见 `test-results/compileall.txt`。
- `pip install --no-build-isolation --no-deps -e .` 安装成功。
- `pip check`：No broken requirements found。
- 浏览器：Playwright 1.51.0，先用现有 Chromium 1234 完成 8 项验收，完整测试使用匹配的 Chromium 1161；下载的 matching headless shell 也已到位。四种宽度 320/390/736/1024 检查无页面横向溢出，桌面 1440px 和手机 390px 截图人工查看通过。
- 浏览器路径：提交本地 fixture → 工具循环 → 报告 → 点击引用打开 app.py:9–11；刷新 URL 恢复；模型故障明确显示；首次 SSE 请求人为中断后自动重连，无重复事件。
- 五题集成回归：5/5 执行产出报告，结果明确 `synthetic: true`。最终评测 fixture 对五个问题使用各自的真实源码/文档窗口，逐题结构检查 5/5，并保留错误解释的负向测试。脚本模型不具备真实答题能力，质量评分全部待人工，不把执行/结构完成率当成质量完成率。见 `test-results/synthetic-eval.json`。
- HTTP 模型适配器通过边界测试验证工具响应结构、缺失 usage 和不泄露服务错误正文；实际供应商模型调用未运行。
- 正式本地服务已启动于 `http://127.0.0.1:8000`，`test_environment=false`，工作目录 `D:\code`。实际浏览器启动检查确认表单可见、显示“未配置模型”、无页面 JavaScript 异常。见 `test-results/startup-check.json` 和 `workspace-unconfigured.png`。服务仅在本机回环地址运行；关闭应用或重启电脑后按 README 启动。

## 验收边界

未配置真实模型，未进行真实模型的五题回归、语义质量评分或成本对比。测试 Token 由脚本模型提供，只用于检查统计链路；不代表真实服务消耗。V1 不支持 GitHub 导入、多 Agent、跨进程断点恢复和网页采集。

独立最终审查、所有发现及修复对照见 `docs/implementation-decisions.md`。最终 ZIP 排除密钥、`.env`、虚拟环境、运行数据库与被分析仓库缓存，包含源码、两份设计/计划、测试、评测、使用说明和验收输出。

## V2.0 协作增量（2026-11-12）

完整测试：221 passed，213.76s（含 29 项浏览器回归）；compileall src 和 pip check 通过。新增共享原子预算、受限文档范围、真实 StateGraph 并行/评审循环、mode/API/SQLite 原子终态、工作台与同预算比较。旧 165 项回归保留。详细范围、测试替身比较结果和限制见 docs/collaborative-research.md。正式 0.3.0 服务启动与页面检查通过；真实模型未配置，两种模式均明确 model_not_configured，没有真实效果评测。最终独立审查结果另记。

最终独立审查修复后：**235 passed，201.17s**（含 30 项浏览器测试）；compileall 与 pip check 再次通过。八项重要审查问题及一项重新分级问题均 RED→GREEN，最终整套回归通过；一项分工卡片等待标签问题暂缓。审查范围、执行取舍与逐项回归见 docs/collaborative-research.md、docs/collaborative-execution.md。正式服务已重启并再次通过页面/默认模式检查。

## V2.1 可配置检索（2026-11-12）

首轮全量 280 passed，277.88s，含36项浏览器测试；compileall和pip check通过。15条离线三配置比较已导出，quality保持null。正式0.4.0服务默认keyword启动与页面检查通过，混合检索未配置时明确409；未启动Docker或调用真实Embedding/Rerank。详细方案和边界见 docs/hybrid-retrieval.md。最终独立审查待完成。

V2.1 最终独立审查修复后：**292 passed，273.96s**，含36项浏览器测试；compileall和pip check通过。七类重要问题（含重新分级的上传计数）均RED→GREEN并完成整套回归。两项轻微诊断问题暂缓；真实服务待配置后验收。执行与取舍见 docs/hybrid-execution.md。正式默认keyword服务已重启验证，未配置hybrid拒绝也带正确零调用账本。

## V3 本地持久恢复增量（2026-11-15）

最终独立审查修复后：**339 passed，371.57s**，含42项浏览器测试；compileall和pip check通过。三项重要问题（msgpack构造器限制、hybrid失效代与累计用量、完整执行指纹）均RED→GREEN。四种真实进程退出和四种无新调用拒绝场景均通过；评测明确synthetic，质量为null，不代表真实费用或答案质量。源码包附最终全量输出、启动检查、桌面/移动端截图及SHA256清单。

正式0.5.0服务已重启，未配置模型时零调用明确失败、恢复拒绝409，默认single/keyword页面无JavaScript异常。保留一项轻微页面取消入口问题，API取消可用；本轮仍为SQLite单worker调查恢复，未实现生产分布式工程化或导入/建库恢复。详见 docs/durable-recovery.md、docs/durable-execution.md、docs/results/recovery-synthetic.json。

## V3.1 独立 worker 工程化（2026-11-15）

版本0.6.0提供PostgreSQL/官方PG检查点、独立API/worker、数据库持久派发与Redis唤醒、Compose及只读源库历史迁移。一次静态全分支审查的三项重要问题已修正。遵守用户AGENT.md，本轮**只编译，不运行测试**：Python字节码/Jinja模板编译、JavaScript语法、pip check与Compose静态配置检查；没有Docker build/up、数据库迁移或模型调用，没有重启原服务，不复用上一版本339项通过结论。部署运行验收仍待进行，见 docs/infrastructure.md 和 docs/results/infrastructure-compile.json。

## V3.2 网页资料与只读 MCP（2026-11-15）

版本0.7.0提供明确允许站点的公网HTTPS采集、固定段落证据、任务附件/恢复校验、可选断网Playwright侧车，以及复用相同工具校验的MCP stdio。一次静态全分支审查的两项重要问题已修复，一项标题显示轻微问题暂缓。仍按用户要求只编译：Python/Jinja、node语法、pipcheck和Compose browser/migration配置；没有运行测试、网页采集、MCP会话、浏览器/容器或真实模型。实际运行效果未验收，详见docs/web-documents-mcp.md、docs/web-mcp-execution.md和docs/results/web-mcp-compile.json。
