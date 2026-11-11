import io
import stat
from pathlib import Path
from uuid import uuid4
import zipfile
import httpx
import pytest
from repolens.config import Settings
from repolens.github_client import GitHubClient, GitHubSource
from repolens.github_import import import_github_snapshot
from tests.github_fixtures import COMMIT, GitHubFixture, archive, blob, public_dns


def prepare(tmp_path, files=None, **updates):
    settings = Settings(workspace_root=tmp_path / "workspace", data_dir=tmp_path / "data", **updates)
    fixture = GitHubFixture(files)
    adapter = GitHubClient(settings, transport=httpx.MockTransport(fixture), resolve_host=public_dns)
    resolved = adapter.resolve(GitHubSource.parse("https://github.com/example/demo", "main"))
    path = tmp_path / "source.zip"
    path.write_bytes(archive(fixture.files))
    return settings, resolved, path, fixture


def test_imports_python_and_documentation_with_commit_evidence(tmp_path):
    from repolens.storage import Database
    from repolens.indexing import build_index
    from repolens.evidence import EvidenceStore
    settings, resolved, path, fixture = prepare(tmp_path)
    snapshot = import_github_snapshot(resolved, path, settings, uuid4().hex)
    assert snapshot.commit_sha == COMMIT and snapshot.source_type == "github"
    assert snapshot.requested_ref == "main" and snapshot.archive_hash
    assert (snapshot.root / "app.py").read_bytes() == fixture.files["app.py"]
    db = Database(settings.data_dir / "test.sqlite")
    db.put_snapshot(snapshot)
    build_index(snapshot, db)
    assert EvidenceStore(db).read_evidence(snapshot.id, "app.py", 9, 11).commit_sha == COMMIT


def test_changed_branch_does_not_change_resolved_snapshot(tmp_path):
    settings, resolved, path, fixture = prepare(tmp_path)
    fixture.sha = "c" * 40
    assert import_github_snapshot(resolved, path, settings, uuid4().hex).commit_sha == COMMIT


@pytest.mark.parametrize("member", ["root/../escape.py", "/root/app.py", "root/C:/escape.py", "root/..\\escape.py", "root//app.py", "root/app.py:stream", "root/CON.py", "root/pkg./file.py", "root/file.py ", "root/aux/file.py", "root/COM1.txt", "root/hello\n.py"])
def test_rejects_archive_path_escape(tmp_path, member):
    settings, resolved, path, _ = prepare(tmp_path)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(member, "outside")
    with pytest.raises(ValueError, match="github_archive_path"):
        import_github_snapshot(resolved, path, settings, uuid4().hex)
    assert not (tmp_path / "escape.py").exists()


@pytest.mark.parametrize("names", [("root/a.py", "root/A.py"), ("root/a.py", "root/a.py"), ("root/a.py", "root/a.py/child.py"), ("root/a.py", "other/b.py"), ("root/e\u0301.py", "root/é.py")])
def test_rejects_windows_aliases_and_duplicate_paths(tmp_path, names):
    settings, resolved, path, _ = prepare(tmp_path)
    with zipfile.ZipFile(path, "w") as z:
        for name in names:
            z.writestr(name, "pass")
    with pytest.raises(ValueError, match="github_archive_path|github_archive_duplicate"):
        import_github_snapshot(resolved, path, settings, uuid4().hex)


def test_skips_links_special_files_and_secrets(tmp_path):
    files = {"app.py": b"value = 42\n", ".env": b"secret", "node_modules/x.py": b"skip"}
    settings, resolved, path, _ = prepare(tmp_path, files)
    with zipfile.ZipFile(path, "a") as z:
        for name, mode in [("link.py", stat.S_IFLNK), ("device.py", stat.S_IFCHR)]:
            info = zipfile.ZipInfo("demo-commit/" + name)
            info.create_system = 3
            info.external_attr = (mode | 0o644) << 16
            z.writestr(info, "../../outside")
    snapshot = import_github_snapshot(resolved, path, settings, uuid4().hex)
    assert set(snapshot.manifest) == {"app.py"}
    assert any("link.py" in x for x in snapshot.excluded_files)
    assert not (snapshot.root / ".env").exists()


@pytest.mark.parametrize("setting,value", [("github_max_members", 1), ("github_max_unpacked_bytes", 5)])
def test_archive_member_count_and_unpacked_limit(tmp_path, setting, value):
    settings, resolved, path, _ = prepare(tmp_path, {"a.py": b"x=42\n", "b.py": b"y=1\n"})
    settings = settings.model_copy(update={setting: value})
    with pytest.raises(ValueError, match="github_member_limit|github_unpacked_limit"):
        import_github_snapshot(resolved, path, settings, uuid4().hex)


def test_archive_file_and_text_limits(tmp_path):
    settings, resolved, path, _ = prepare(tmp_path, {"a.py": b"x=1\n", "large.py": b"x" * 30}, max_file_bytes=10)
    snapshot = import_github_snapshot(resolved, path, settings, uuid4().hex)
    assert set(snapshot.manifest) == {"a.py"}
    for field in ["max_text_bytes", "max_snapshot_bytes"]:
        with pytest.raises(ValueError, match="snapshot_total_limit"):
            import_github_snapshot(resolved, path, settings.model_copy(update={field: 2}), uuid4().hex)


def test_mismatched_blob_rejected(tmp_path):
    settings, resolved, path, _ = prepare(tmp_path, {"app.py": b"original=1\n"})
    path.write_bytes(archive({"app.py": b"changed=2\n"}))
    with pytest.raises(ValueError, match="github_blob_mismatch"):
        import_github_snapshot(resolved, path, settings, uuid4().hex)


def test_missing_archive_source_is_recorded(tmp_path):
    settings, resolved, path, _ = prepare(tmp_path, {"a.py": b"x=1\n", "hidden.py": b"y=2\n"})
    path.write_bytes(archive({"a.py": b"x=1\n"}))
    snapshot = import_github_snapshot(resolved, path, settings, uuid4().hex)
    assert any("hidden.py: archive_omitted" in x for x in snapshot.excluded_files)


def test_failed_import_cleans_only_its_own_files(tmp_path):
    settings, resolved, path, _ = prepare(tmp_path)
    keep = settings.data_dir / "snapshots" / "existing"
    keep.mkdir(parents=True)
    (keep / "keep.py").write_text("keep")
    path.write_bytes(b"invalid zip")
    snapshot_id = uuid4().hex
    with pytest.raises(ValueError, match="github_invalid_archive"):
        import_github_snapshot(resolved, path, settings, snapshot_id)
    assert (keep / "keep.py").read_text() == "keep"
    assert not (settings.data_dir / "snapshots" / snapshot_id).exists()
