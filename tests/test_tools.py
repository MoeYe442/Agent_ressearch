def test_missing_tool_returns_structured_error(indexed):
    from repolens.models import ToolContext
    _, _, snapshot, _, _, registry = indexed
    result = registry.invoke("shell", {"cmd": "anything"}, ToolContext(snapshot_id=snapshot.id, task_id="test"))
    assert result.status == "error" and result.error_code == "unknown_tool"
    assert result.invocation_id and result.elapsed_ms >= 0


def test_tool_scope_and_argument_validation(indexed):
    from repolens.models import ToolContext
    _, _, snapshot, _, store, registry = indexed
    context = ToolContext(snapshot_id=snapshot.id, task_id="test")
    assert registry.invoke("read_file", {"path": "../app.py"}, context).status == "error"
    assert registry.invoke("list_tree", {"snapshot_id": "other"}, context).error_code == "invalid_arguments"
    result = registry.invoke("get_symbol", {"query": "Processor.run"}, context)
    assert result.status == "ok" and result.evidence_ids
    assert all(store.validate_evidence(e, snapshot.id) for e in result.evidence_ids)
