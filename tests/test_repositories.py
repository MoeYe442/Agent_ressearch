from pathlib import Path
import pytest
from repolens.config import Settings
from repolens.repositories import create_snapshot
from repolens.storage import Database


@pytest.fixture
def setup_repo(tmp_path):
    workspace = tmp_path / "workspace"
    repo = workspace / "sample"
    repo.mkdir(parents=True)
    (repo / "app.py").write_text("def hello():\n    return 42\n", encoding="utf-8")
    return repo, Settings(workspace_root=workspace, data_dir=tmp_path / "data")


def test_snapshot_is_immutable(setup_repo):
    repo, settings = setup_repo
    snapshot = create_snapshot(repo, settings)
    before = (snapshot.root / "app.py").read_bytes()
    (repo / "app.py").write_text("changed", encoding="utf-8")
    assert (snapshot.root / "app.py").read_bytes() == before
    assert create_snapshot(repo, settings).manifest_hash != snapshot.manifest_hash
    db = Database(settings.data_dir / "test.sqlite")
    db.put_snapshot(snapshot)
    assert db.get_snapshot(snapshot.id) == snapshot


def test_rejects_path_outside_workspace(setup_repo, tmp_path):
    _, settings = setup_repo
    with pytest.raises(ValueError, match="outside_workspace"):
        create_snapshot(tmp_path, settings)


def test_skips_symlink_and_secrets(setup_repo, tmp_path):
    repo, settings = setup_repo
    (repo / ".env").write_text("API_KEY=secret")
    (repo / "private.pem").write_text("secret")
    (repo / ".git").mkdir()
    try:
        (repo / "external.py").symlink_to(tmp_path / "secret.py")
    except OSError:
        pass  # Windows without symlink privilege; separate reparse guard is still tested.
    snapshot = create_snapshot(repo, settings)
    assert not (snapshot.root / ".env").exists()
    assert not (snapshot.root / "private.pem").exists()
    assert any(".env" in x for x in snapshot.excluded_files)
    assert not (snapshot.root / "external.py").exists()


def test_snapshot_limits(setup_repo):
    repo, settings = setup_repo
    (repo / "large.py").write_text("x" * 101)
    snapshot = create_snapshot(repo, settings.model_copy(update={"max_file_bytes": 100}))
    assert any("large.py" in x for x in snapshot.excluded_files)
    for field in ("max_text_bytes", "max_snapshot_bytes"):
        with pytest.raises(ValueError, match="limit"):
            create_snapshot(repo, settings.model_copy(update={field: 10}))


def test_snapshot_manifest_is_stable(setup_repo):
    repo, settings = setup_repo
    assert create_snapshot(repo, settings).manifest_hash == create_snapshot(repo, settings).manifest_hash
