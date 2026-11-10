import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx

TERMINAL = {"succeeded", "partial", "failed", "cancelled"}


def summarize(results):
    total = len(results)
    pending = sum(item.get("quality_pass") is None for item in results)
    unknown = sum(item.get("usage") is None for item in results)
    quality = sum(item.get("quality_pass") is True for item in results)
    return {
        "total": total,
        "execution_completion_rate": sum(item.get("status") == "succeeded" for item in results) / total if total else 0,
        "report_production_rate": sum(item.get("status") in {"succeeded", "partial"} and item.get("has_report", True) for item in results) / total if total else 0,
        "quality_completion_rate": None if pending else (quality / total if total else 0),
        "confirmed_quality_rate": quality / total if total else 0,
        "pending_manual_review": pending,
        "unknown_usage_tasks": unknown,
        "input_tokens": None if unknown else sum(item["usage"]["input_tokens"] for item in results),
        "output_tokens": None if unknown else sum(item["usage"]["output_tokens"] for item in results),
        "estimated": any(item.get("usage", {}).get("estimated", False) for item in results if item.get("usage")),
    }


def structural_check(task, report, evidence):
    excerpts = "\n".join(e.get("excerpt", "") for e in evidence)
    missing_symbols = [name for name in task.get("required_symbols", []) if name not in excerpts]
    missing_sources = [expected for expected in task.get("accepted_evidence", []) if not any(item.get("path") == expected["path"] and item.get("start_line", 0) <= expected["end_line"] and item.get("end_line", 0) >= expected["start_line"] for item in evidence)]
    limitations = "\n".join(report.get("limitations", []))
    missing_limitations = [word for word in task.get("expected_limitations", []) if word not in limitations]
    return {"structure_pass": not (missing_symbols or missing_sources or missing_limitations), "missing_symbols": missing_symbols, "missing_sources": missing_sources, "missing_limitation_markers": missing_limitations, "quality_pass": None, "review_rule": task.get("review_rule", "Human semantic review required.")}


def wait_for(client, route, status_field, pending, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(route)
        response.raise_for_status()
        item = response.json()
        if item[status_field] not in pending:
            return item
        time.sleep(.1)
    raise TimeoutError("evaluation_timeout")


def run_suite(base_url, tasks, root=None, synthetic=False, timeout=960):
    root = Path(root or Path.cwd()).resolve()
    snapshots, results = {}, []
    with httpx.Client(base_url=base_url, timeout=30) as client:
        health = client.get("/health").raise_for_status().json()
        synthetic = synthetic or health.get("test_environment", False)
        for task in tasks:
            started = time.monotonic()
            result = {"id": task["id"], "question": task["question"], "status": "failed", "usage": None, "quality_pass": None, "synthetic": synthetic}
            try:
                repository = str((root / task["repository"]).resolve())
                if repository not in snapshots:
                    response = client.post("/repositories", json={"path": repository})
                    response.raise_for_status()
                    snapshot = wait_for(client, "/repositories/" + response.json()["id"], "status", {"importing"}, timeout)
                    if snapshot["status"] != "ready":
                        raise ValueError(snapshot.get("error_code") or "import_failed")
                    snapshots[repository] = snapshot
                snapshot = snapshots[repository]
                response = client.post("/tasks", json={"snapshot_id": snapshot["id"], "question": task["question"]})
                response.raise_for_status()
                task_id = response.json()["id"]
                result.update({"task_id": task_id, "snapshot_id": snapshot["id"], "manifest_hash": snapshot["manifest_hash"]})
                completed = wait_for(client, "/tasks/" + task_id, "status", {"queued", "running"}, timeout)
                result.update({"status": completed["status"], "usage": completed.get("usage"), "error_code": completed.get("error_code")})
                response = client.get(f"/tasks/{task_id}/report")
                if response.status_code == 200:
                    report = response.json()
                    evidence_ids = sorted({e for c in report["claims"] for e in c["evidence_ids"]})
                    evidence = [client.get("/evidence/" + e).raise_for_status().json() for e in evidence_ids]
                    result.update({"has_report": True, "report": report, "evidence": evidence, **structural_check(task, report, evidence)})
                else:
                    result["has_report"] = False
            except Exception as exc:
                result["error_code"] = str(exc) if isinstance(exc, (TimeoutError, ValueError)) else type(exc).__name__
            result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
            results.append(result)
    return {"created_at": datetime.now(timezone.utc).isoformat(), "synthetic": synthetic, "quality_note": "Program checks structure only; quality_pass requires independent manual semantic review. Synthetic runs are not evidence of real model performance.", "summary": summarize(results), "results": results}


def main():
    parser = argparse.ArgumentParser(description="RepoLens five-question regression; semantic quality remains manual.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--tasks", type=Path, default=Path("eval/tasks.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()
    tasks = [json.loads(line) for line in args.tasks.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = run_suite(args.base_url, tasks, synthetic=args.synthetic)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
