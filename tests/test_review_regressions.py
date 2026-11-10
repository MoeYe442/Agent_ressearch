import os
from pathlib import Path
import shutil
import subprocess
import pytest
from repolens.repositories import create_snapshot
from repolens.tasks import TaskService
from tests.scripted_model import ScriptedModel
from tests.test_repositories import setup_repo


def test_physical_lines_match_python_ast(indexed):
    from repolens.indexing import build_index
    from repolens.models import ToolContext
    import hashlib
    _, db, snapshot, _, _, registry = indexed
    content = '# first page\f second page\ndef answer(): return 42\n'.encode()
    (snapshot.root / "physical.py").write_bytes(content)
    snapshot.manifest["physical.py"] = hashlib.sha256(content).hexdigest()
    db.put_snapshot(snapshot)
    build_index(snapshot, db)
    result = registry.invoke("get_symbol", {"query":"answer"}, ToolContext(snapshot_id=snapshot.id, task_id="physical"))
    assert result.status == "ok"
    assert result.data[0]["evidence"]["excerpt"] == 'def answer(): return 42\n'


def test_final_state_report_event_are_atomic(indexed, monkeypatch):
    from tests.test_tasks import wait_task
    settings, db, snapshot, _, _, _ = indexed
    original = db.save_task_event
    def crash_on_terminal(task, event, **kwargs):
        if event.type == "task_finished" and task.status == "succeeded":
            raise RuntimeError("simulated process boundary")
        return original(task, event, **kwargs)
    monkeypatch.setattr(db, "save_task_event", crash_on_terminal)
    service = TaskService(settings, db, ScriptedModel())
    service.start()
    try:
        task = service.submit(snapshot.id, "Question", None)
        task = wait_task(service, task.id)
        assert task.status == "failed"
        try:
            report = db.get("reports", task.id)
        except KeyError:
            return
        assert report["status"] == task.status
    finally:
        service.stop()


def git_repo(setup_repo):
    repo, settings = setup_repo
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()
    git("init")
    git("config", "core.autocrlf", "false")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    return repo, settings, git


def test_snapshot_never_runs_repository_fsmonitor(setup_repo):
    repo, settings, git = git_repo(setup_repo)
    (repo / ".git" / "watch").write_text('#!/bin/sh\nprintf invoked > "$PWD/UNSAFE_MARKER"\n', encoding="utf-8")
    git("config", "core.fsmonitor", ".git/watch")
    create_snapshot(repo, settings)
    assert not (repo / "UNSAFE_MARKER").exists()


def test_ignored_source_does_not_claim_clean_commit(setup_repo):
    repo, settings, git = git_repo(setup_repo)
    (repo / ".git" / "info" / "exclude").write_text("ignored.py\n")
    (repo / "ignored.py").write_text("value = 1\n")
    snapshot = create_snapshot(repo, settings)
    assert "ignored.py" in snapshot.manifest
    assert snapshot.commit_sha is None


def test_clean_git_snapshot_retains_verified_commit(setup_repo):
    repo, settings, git = git_repo(setup_repo)
    assert create_snapshot(repo, settings).commit_sha == git("rev-parse", "HEAD")


def test_packed_git_falls_back_without_claiming_dirty(setup_repo):
    repo, settings, git = git_repo(setup_repo)
    git("gc", "--prune=now")
    snapshot = create_snapshot(repo, settings)
    assert snapshot.commit_sha is None
    assert snapshot.dirty is None
    assert snapshot.manifest_hash


def test_rejects_parent_junction_swap_before_file_open(setup_repo, tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows junction race")
    repo, settings = setup_repo
    directory = repo / "pkg"
    directory.mkdir()
    (directory / "module.py").write_text("safe = True\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "module.py").write_text("OUTSIDE_SECRET = True\n")
    from repolens import secure_io
    original = secure_io._windows_open
    swapped = False
    # A junction does not require Windows developer-mode symlink privileges.
    def racing_open_junction(path, *args, **kwargs):
        nonlocal swapped
        if path == directory / "module.py" and not swapped:
            swapped = True
            directory.rename(repo / "parked")
            import ctypes
            # Windows API CreateSymbolicLink may lack privileges; use native junction creation in test only.
            subprocess.run(["cmd", "/c", "mklink", "/J", str(directory), str(outside)], capture_output=True, check=True)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(secure_io, "_windows_open", racing_open_junction)
    try:
        snapshot = create_snapshot(repo, settings)
    except (ValueError, OSError):
        return
    copied = "\n".join((snapshot.root / path).read_text(encoding="utf-8") for path in snapshot.manifest)
    assert "OUTSIDE_SECRET" not in copied


def test_ready_without_index_is_not_stuck_importing(indexed):
    settings, db, snapshot, _, _, _ = indexed
    with db.connect() as conn:
        conn.execute("DELETE FROM entities WHERE kind='indexes' AND id=?", (snapshot.id,))
    service = TaskService(settings, db, None)
    service.start()
    try:
        saved = db.get_snapshot(snapshot.id)
        assert saved.status == "failed" and saved.error_code == "interrupted_import"
    finally:
        service.stop()


def test_missing_path_is_explicit_validation_error(setup_repo):
    repo, settings = setup_repo
    with pytest.raises(ValueError, match="repository_not_found"):
        create_snapshot(repo / "absent", settings)
