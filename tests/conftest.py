from pathlib import Path
import shutil
import pytest
from repolens.config import Settings
from repolens.repositories import create_snapshot
from repolens.storage import Database


@pytest.fixture
def indexed(tmp_path):
    from repolens.indexing import build_index
    from repolens.evidence import EvidenceStore
    from repolens.tools import ToolRegistry
    workspace = tmp_path / "workspace"
    repo = workspace / "sample"
    shutil.copytree(Path(__file__).parent / "fixtures" / "sample_repo", repo)
    settings = Settings(workspace_root=workspace, data_dir=tmp_path / "data")
    snapshot = create_snapshot(repo, settings)
    db = Database(settings.data_dir / "repolens.sqlite")
    db.put_snapshot(snapshot)
    index = build_index(snapshot, db)
    evidence = EvidenceStore(db)
    tools = ToolRegistry(db)
    return settings, db, snapshot, index, evidence, tools
