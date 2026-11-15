"""Read-only stdio adapter over ToolRegistry, scoped by the operator at startup."""
import argparse
import asyncio
import json
import sys
from uuid import uuid4
import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from repolens.config import Settings
from repolens.storage import open_database
from repolens.tools import ToolRegistry
from repolens.documents import DocumentStore
from repolens.models import ToolContext,ToolResult
from repolens.budget import BudgetManager,BudgetExceeded


async def serve(snapshot_id,document_ids,scope):
    settings=Settings.from_env();db=open_database(settings)
    if db.get_snapshot(snapshot_id).status!='ready':raise ValueError('snapshot_not_ready')
    document_ids=sorted(set(document_ids))
    if scope=='code' and document_ids:raise ValueError('tool_scope_denied')
    DocumentStore(db).summaries(document_ids,snapshot_id)
    context=ToolContext(snapshot_id=snapshot_id,task_id='mcp:'+uuid4().hex,source_scope=scope,document_ids=document_ids)
    registry=ToolRegistry(db);budget=BudgetManager(settings)
    server=Server('repolens-readonly')

    @server.list_tools()
    async def list_tools():
        return [types.Tool(name=item['function']['name'],description=item['function']['description'],inputSchema=item['function']['parameters'],outputSchema=ToolResult.model_json_schema(),annotations=types.ToolAnnotations(readOnlyHint=True,destructiveHint=False,idempotentHint=False,openWorldHint=False)) for item in registry.definitions()]

    @server.call_tool(validate_input=False)
    async def call_tool(name,arguments):
        def invoke():
            try:
                budget.reserve_tool()
                if len(json.dumps(arguments).encode())>16000:raise ValueError('invalid_arguments')
                return registry.invoke(name,arguments,context)
            except (BudgetExceeded,ValueError) as exc:return ToolResult(invocation_id=uuid4().hex,status='error',error_code=str(exc))
            except Exception:return ToolResult(invocation_id=uuid4().hex,status='error',error_code='mcp_tool_failed')
        result=await anyio.to_thread.run_sync(invoke)
        return types.CallToolResult(content=[types.TextContent(type='text',text=result.model_dump_json())],structuredContent=result.model_dump(mode='json'),isError=result.status!='ok')

    async with stdio_server() as (reader,writer):
        await server.run(reader,writer,server.create_initialization_options())


def main():
    parser=argparse.ArgumentParser(description='Expose only registered snapshot reads over MCP stdio; never imports, collects, executes shell or calls models.')
    parser.add_argument('--snapshot',required=True)
    parser.add_argument('--document',action='append',default=[])
    parser.add_argument('--scope',choices=['all','code','docs'],default='all')
    args=parser.parse_args()
    try:asyncio.run(serve(args.snapshot,args.document,args.scope))
    except KeyboardInterrupt:pass
    except Exception:
        print('repolens_mcp_startup_failed',file=sys.stderr);raise SystemExit(1) from None


if __name__=='__main__':main()
