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
