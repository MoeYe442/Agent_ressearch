import os
from pathlib import Path
from pydantic import BaseModel, Field, SecretStr


class Settings(BaseModel):
    workspace_root: Path
    data_dir: Path
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

    @classmethod
    def from_env(cls):
        return cls(
            workspace_root=Path(os.getenv("REPOLENS_WORKSPACE", str(Path.cwd()))).resolve(),
            data_dir=Path(os.getenv("REPOLENS_DATA", str(Path.cwd() / ".data"))).resolve(),
            model_url=os.getenv("REPOLENS_MODEL_URL", "https://api.openai.com/v1"),
            model_name=os.getenv("REPOLENS_MODEL", ""),
            model_key=SecretStr(os.getenv("REPOLENS_API_KEY", "")),
        )
