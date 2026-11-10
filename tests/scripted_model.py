import json
from repolens.models import ModelTurn, ModelUsage, ToolCall


class ScriptedModel:
    """Only for isolated tests; never imported by production modules."""
    def complete(self, messages, tools, max_output_tokens):
        round_number = 1 + sum(message["role"] == "assistant" for message in messages)
        if round_number == 1:
            return ModelTurn(tool_calls=[ToolCall(id="search", name="search_symbols", arguments={"query": "Processor.run"})], usage=ModelUsage(input_tokens=100, output_tokens=20))
        if round_number == 2:
            return ModelTurn(tool_calls=[ToolCall(id="read", name="read_file", arguments={"path": "app.py", "start_line": 9, "end_line": 11})], usage=ModelUsage(input_tokens=150, output_tokens=20))
        data = json.loads(messages[-1]["content"])
        return ModelTurn(content=json.dumps({"claims": [{"text": "Processor.run saves running status using StateStore.", "evidence_ids": data["evidence_ids"]}], "limitations": ["Static evidence only; execution behavior not verified."]}), usage=ModelUsage(input_tokens=200, output_tokens=40))


class EvaluationModel:
    """Question-aware positive controls for five hand-authored fixture cases, not a real model."""
    def complete(self, messages, tools, max_output_tokens):
        question = messages[1]["content"]
        tool_messages = [m for m in messages if m["role"] == "tool"]
        if not tool_messages:
            if "入口" in question:
                paths = ["app.py"]
            elif "状态在哪里" in question:
                paths = ["storage.py"]
            elif "重启后" in question or "README" in question:
                paths = ["storage.py", "README.md"]
            else:
                paths = ["app.py", "README.md"]
            return ModelTurn(tool_calls=[ToolCall(id=f"read-{i}", name="read_file", arguments={"path": path}) for i, path in enumerate(paths)], usage=ModelUsage(input_tokens=100, output_tokens=40))
        evidence = [e for m in tool_messages for e in json.loads(m["content"])["evidence_ids"]]
        if "入口" in question:
            text = "app.main 构造 Processor(StateStore())，调用 run。"
        elif "状态在哪里" in question:
            text = "StateStore.save 把状态写入实例字典 states，没有写入磁盘。"
        elif "重启后" in question:
            text = "StateStore.load 仅查询内存，README 把进程重启恢复列为未来计划。"
        elif "README" in question:
            text = "README 的 Future 是未来计划，StateStore 目前只使用内存字典。"
        else:
            text = "在 app.py 的调用和 README 中未发现多 Agent 调度实现。"
        return ModelTurn(content=json.dumps({"claims": [{"text": text, "evidence_ids": evidence}], "limitations": ["仅基于 fixture 的静态检查；恢复未实现；有限检索不能穷尽证明不存在。"]}, ensure_ascii=False), usage=ModelUsage(input_tokens=220, output_tokens=80))
