import json
from pathlib import Path
from eval.run import run_suite
from tests.server import running_app
from tests.scripted_model import EvaluationModel


def test_five_question_synthetic_regression(indexed):
    tasks = [json.loads(x) for x in Path("eval/tasks.jsonl").read_text(encoding="utf-8").splitlines()]
    for task in tasks:
        task["repository"] = indexed[2].source
    settings = indexed[0].model_copy(update={"test_environment": True})
    with running_app(settings, EvaluationModel()) as url:
        result = run_suite(url, tasks)
    assert result["synthetic"]
    assert len(result["results"]) == 5
    assert all(x["status"] == "succeeded" for x in result["results"]), [(x["id"], x["status"], x.get("error_code")) for x in result["results"]]
    assert all(x["quality_pass"] is None for x in result["results"])
    assert all(x["structure_pass"] for x in result["results"])
    assert result["summary"]["quality_completion_rate"] is None
    output = Path("test-results/synthetic-eval.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
