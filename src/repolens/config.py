import os
import ipaddress
import re
from urllib.parse import urlsplit
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, SecretStr, field_validator


class Settings(BaseModel):
    workspace_root: Path
    data_dir: Path
    execution_mode: Literal['embedded','api','worker'] = 'embedded'
    database_url: SecretStr = SecretStr('')
    redis_url: SecretStr = SecretStr('')
    redis_queue: str = Field(default='repolens:wake',pattern=r'^[A-Za-z0-9:_-]{1,100}$')
    client_networks: list[str] = ['127.0.0.0/8','::1/128']
    document_hosts: list[str] = Field(default_factory=list,max_length=20)
    document_timeout: float = Field(default=30,gt=0,le=30)
    document_max_bytes: int = Field(default=2*1024*1024,gt=0,le=2*1024*1024)
    renderer_socket: Path | None = None

    @field_validator('document_hosts')
    @classmethod
    def validate_document_hosts(cls,values):
        result=[]
        for value in values:
            host=value.encode('idna').decode().lower()
            if len(host)>253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',host) or '..' in host or '.' not in host:raise ValueError('invalid_document_host')
            result.append(host)
        return sorted(set(result))

    @field_validator('client_networks')
    @classmethod
    def validate_networks(cls,value):
        for network in value:
            parsed=ipaddress.ip_network(network,strict=True)
            if parsed.prefixlen==0:raise ValueError('unrestricted_client_network')
        return value
    max_file_bytes: int = Field(default=1024 * 1024, gt=0)
    max_text_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    max_snapshot_bytes: int = Field(default=500 * 1024 * 1024, gt=0)
    max_tool_calls: int = Field(default=30, ge=0, le=30)
    max_model_calls: int = Field(default=30, ge=0, le=30)
    max_tokens: int = Field(default=60000, gt=0, le=60000)
    max_seconds: float = Field(default=900, gt=0, le=900)
    max_output_tokens: int = Field(default=2048, gt=0)
    model_url: str = "https://api.openai.com/v1"
    model_name: str = ""
    model_key: SecretStr = SecretStr("")
    provider_timeout: float = Field(default=45, gt=0, le=120)
    test_environment: bool = False
    github_token: SecretStr = SecretStr("")
    github_max_download_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    github_max_metadata_bytes: int = Field(default=16 * 1024 * 1024, gt=0)
    github_max_members: int = Field(default=50000, gt=0)
    github_max_unpacked_bytes: int = Field(default=500 * 1024 * 1024, gt=0)
    github_import_timeout: float = Field(default=180, gt=0, le=180)
    github_request_timeout: float = Field(default=30, gt=0, le=30)
    graph_recursion_limit: int = Field(default=32, ge=1, le=64)
    milvus_url: str = ""
    milvus_token: SecretStr = SecretStr("")
    milvus_collection: str = Field(default="repolens_chunks_v1", pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
    embedding_url: str = ""
    embedding_model: str = ""
    embedding_key: SecretStr = SecretStr("")
    embedding_dimensions: int = Field(default=768, ge=1, le=4096)
    rerank_url: str = ""
    rerank_model: str = ""
    rerank_key: SecretStr = SecretStr("")

    @field_validator("milvus_url", "embedding_url", "rerank_url")
    @classmethod
    def validate_service_url(cls, value):
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            raise ValueError("invalid_retrieval_service_url")
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname.lower() == "localhost"
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError("retrieval_service_requires_https_or_loopback")
        if parsed.port is not None and parsed.port < 1:
            raise ValueError("invalid_retrieval_service_port")
        return value.rstrip("/")

    @classmethod
    def from_env(cls):
        return cls(
            workspace_root=Path(os.getenv("REPOLENS_WORKSPACE", str(Path.cwd()))).resolve(),
            data_dir=Path(os.getenv("REPOLENS_DATA", str(Path.cwd() / ".data"))).resolve(),
            execution_mode=os.getenv('REPOLENS_EXECUTION_MODE','embedded'),
            database_url=SecretStr(os.getenv('REPOLENS_DATABASE_URL','')),
            redis_url=SecretStr(os.getenv('REPOLENS_REDIS_URL','')),
            redis_queue=os.getenv('REPOLENS_REDIS_QUEUE','repolens:wake'),
            client_networks=[part.strip() for part in os.getenv('REPOLENS_CLIENT_NETWORKS','127.0.0.0/8,::1/128').split(',') if part.strip()],
            document_hosts=[part.strip() for part in os.getenv('REPOLENS_DOCUMENT_HOSTS','').split(',') if part.strip()],
            renderer_socket=Path(os.environ['REPOLENS_RENDERER_SOCKET']) if os.getenv('REPOLENS_RENDERER_SOCKET') else None,
            model_url=os.getenv("REPOLENS_MODEL_URL", "https://api.openai.com/v1"),
            model_name=os.getenv("REPOLENS_MODEL", ""),
            model_key=SecretStr(os.getenv("REPOLENS_API_KEY", "")),
            github_token=SecretStr(os.getenv("REPOLENS_GITHUB_TOKEN", "")),
            milvus_url=os.getenv("REPOLENS_MILVUS_URL", ""),
            milvus_token=SecretStr(os.getenv("REPOLENS_MILVUS_TOKEN", "")),
            milvus_collection=os.getenv("REPOLENS_MILVUS_COLLECTION", "repolens_chunks_v1"),
            embedding_url=os.getenv("REPOLENS_EMBEDDING_URL", ""),
            embedding_model=os.getenv("REPOLENS_EMBEDDING_MODEL", ""),
            embedding_key=SecretStr(os.getenv("REPOLENS_EMBEDDING_KEY", "")),
            embedding_dimensions=int(os.getenv("REPOLENS_EMBEDDING_DIMENSIONS", "768")),
            rerank_url=os.getenv("REPOLENS_RERANK_URL", ""),
            rerank_model=os.getenv("REPOLENS_RERANK_MODEL", ""),
            rerank_key=SecretStr(os.getenv("REPOLENS_RERANK_KEY", "")),
        )
