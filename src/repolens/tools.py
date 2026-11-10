import time
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from repolens.evidence import EvidenceStore
from repolens.indexing import RepositoryIndex
from repolens.models import ToolResult


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SearchArgs(EmptyArgs):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=20)


class ReadArgs(EmptyArgs):
    path: str = Field(min_length=1, max_length=500)
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class EvidenceArgs(EmptyArgs):
    evidence_id: str = Field(min_length=1, max_length=100)


ARGUMENTS = {"list_tree": EmptyArgs, "search_symbols": SearchArgs, "search_text": SearchArgs, "read_file": ReadArgs, "get_symbol": SearchArgs, "retrieve_evidence": EvidenceArgs}
DESCRIPTIONS = {
    "list_tree": "List snapshot files (up to 1000 paths); cannot access source workspace.",
    "search_symbols": "Find Python qualified functions, classes, imports, or Markdown headings. Returns evidence.",
    "search_text": "Keyword search within this snapshot. Returns up to 20 text windows with evidence.",
    "read_file": "Read exact lines from a snapshot file, maximum 160 lines. Returns evidence ID.",
    "get_symbol": "Locate a symbol and read its first 160 lines as evidence.",
    "retrieve_evidence": "Read a previously generated evidence ID within this snapshot.",
}


class ToolRegistry:
    def __init__(self, db):
        self.db, self.index, self.evidence = db, RepositoryIndex(db), EvidenceStore(db)

    def definitions(self):
        return [{"type": "function", "function": {"name": name, "description": DESCRIPTIONS[name], "parameters": schema.model_json_schema()}} for name, schema in ARGUMENTS.items()]

    def invoke(self, name, arguments, context):
        start = time.monotonic()
        result = ToolResult(invocation_id=uuid4().hex, status="error")
        try:
            if name not in ARGUMENTS:
                raise ValueError("unknown_tool")
            args = ARGUMENTS[name].model_validate(arguments)
            self.db.get_snapshot(context.snapshot_id)
            if name == "list_tree":
                paths = sorted(self.db.get_snapshot(context.snapshot_id).manifest)
                result.data = {"paths": paths[:1000], "total": len(paths), "truncated": len(paths) > 1000}
            elif name in {"search_text", "search_symbols", "get_symbol"}:
                method = self.index.search_text if name == "search_text" else self.index.search_symbols
                hits = method(context.snapshot_id, args.query, args.limit)
                records = []
                for hit in hits:
                    item = self.evidence.read_evidence(context.snapshot_id, hit.path, hit.start_line, min(hit.end_line, hit.start_line + 159))
                    result.evidence_ids.append(item.id)
                    records.append({**hit.model_dump(), "evidence": item.model_dump()})
                result.data = records
            else:
                if name == "read_file":
                    item = self.evidence.read_evidence(context.snapshot_id, **args.model_dump())
                else:
                    item = self.evidence.get(args.evidence_id, context.snapshot_id)
                result.evidence_ids = [item.id]
                result.data = item.model_dump()
            result.status = "ok"
        except ValidationError:
            result.error_code = "invalid_arguments"
        except (ValueError, KeyError, OSError) as exc:
            result.error_code = str(exc) if isinstance(exc, ValueError) else "not_found_or_unreadable"
        result.elapsed_ms = round((time.monotonic() - start) * 1000, 3)
        self.db.put("invocations", result.invocation_id, {"task_id": context.task_id, "snapshot_id": context.snapshot_id, "tool_name": name, "arguments": arguments, **result.model_dump()})
        return result
