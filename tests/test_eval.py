from eval.run import summarize, structural_check


def test_failed_tasks_remain_in_denominator():
    summary = summarize([{"status": "succeeded", "quality_pass": True}, {"status": "failed", "quality_pass": False}])
    assert summary["total"] == 2
    assert summary["execution_completion_rate"] == .5
    assert summary["quality_completion_rate"] == .5


def test_execution_success_not_quality_success():
    summary = summarize([{"status": "succeeded", "structure_pass": True, "quality_pass": None}])
    assert summary["execution_completion_rate"] == 1
    assert summary["quality_completion_rate"] is None
    assert summary["pending_manual_review"] == 1


def test_missing_usage_is_not_zero_cost():
    summary = summarize([{"status": "failed", "usage": None}])
    assert summary["input_tokens"] is None and summary["output_tokens"] is None
    assert summary["unknown_usage_tasks"] == 1


def test_structure_check_cannot_grant_semantic_quality():
    task = {"required_symbols": ["save"], "accepted_evidence": [{"path": "storage.py", "start_line": 8, "end_line": 9}], "expected_limitations": []}
    report = {"claims": [{"text": "Unsupported interpretation", "evidence_ids": ["e1"]}], "limitations": []}
    evidence = [{"id": "e1", "path": "storage.py", "start_line": 8, "end_line": 9, "excerpt": "def save(self): pass"}]
    assert structural_check(task, report, evidence)["structure_pass"]
    assert structural_check(task, report, evidence)["quality_pass"] is None
