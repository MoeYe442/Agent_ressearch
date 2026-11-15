"""Non-secret API-side attestation of the execution configuration used for comparison."""
import hashlib
import importlib.metadata
from pathlib import Path
from repolens import __version__
from repolens.benchmark.protocol import digest


def public_configuration(settings,service):
    excluded={'workspace_root','data_dir','execution_mode','client_networks','redis_queue','renderer_socket'}
    values={}
    for key,value in settings.model_dump(mode='json').items():
        if key in excluded or hasattr(getattr(settings,key),'get_secret_value'):continue
        values[key]=digest(value) if key.endswith('_url') else value
    sources={path.relative_to(Path(__file__).parents[1]).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(Path(__file__).parents[1].rglob('*.py'))}
    dependencies={name:importlib.metadata.version(name) for name in ['fastapi','pydantic','httpx','httpcore','langgraph','langgraph-checkpoint-sqlite','langgraph-checkpoint-postgres','mcp']}
    config={'settings':values,'sources':sources,'dependencies':dependencies,'tools':service.registry.definitions(),'storage':service.db.backend}
    return {'server_version':__version__,'execution_fingerprint':digest(config),'model_identifier':('synthetic:'+type(service.model).__name__) if settings.test_environment else settings.model_name or None,'budget_limits':{key:getattr(settings,key) for key in ['max_model_calls','max_tool_calls','max_tokens','max_seconds','max_output_tokens']},'synthetic':settings.test_environment,'model_configured':service.model is not None}
