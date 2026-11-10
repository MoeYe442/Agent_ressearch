import hashlib
import io
import json
import os
import shutil
import stat
import tokenize
from pathlib import Path
from uuid import uuid4
from repolens.config import Settings
from repolens.models import RepositorySnapshot
from repolens.secure_io import secure_read
from repolens.git_provenance import verified_commit

EXCLUDED_DIRS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".pytest_cache", "dist", "build", ".data", ".superpowers", ".mypy_cache", ".tox", "site-packages"}
SECRET_NAMES = {"credentials", "credentials.json", "secrets.json", "secrets.yaml", "secrets.yml", "id_rsa", "id_ed25519", ".npmrc", ".pypirc", ".netrc"}
TEXT_SUFFIXES = {".py", ".pyi", ".md", ".rst", ".txt", ".toml", ".json", ".yaml", ".yml", ".ini", ".cfg", ".html", ".css", ".js", ".sql"}


def is_link(path: Path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def decode_text(raw: bytes, suffix: str):
    if b"\0" in raw:
        raise UnicodeError("binary")
    encoding = tokenize.detect_encoding(io.BytesIO(raw).readline)[0] if suffix == ".py" else "utf-8-sig"
    return raw.decode(encoding)


def checked_repo(repo_path: Path, settings: Settings):
    workspace = settings.workspace_root.resolve(strict=True)
    raw = Path(os.path.abspath(repo_path))
    if not raw.is_relative_to(workspace):
        raise ValueError("outside_workspace")
    if not raw.exists():
        raise ValueError("repository_not_found")
    cursor = raw
    while cursor != workspace:
        if is_link(cursor):
            raise ValueError("symlink_path")
        cursor = cursor.parent
    repo = raw.resolve(strict=True)
    if not repo.is_relative_to(workspace) or not repo.is_dir():
        raise ValueError("outside_workspace")
    if repo.is_relative_to(settings.data_dir.resolve()):
        raise ValueError("data_directory_not_repository")
    return repo


def create_snapshot(repo_path: Path, settings: Settings, snapshot_id: str | None = None):
    repo = checked_repo(repo_path, settings)
    snapshot_id = snapshot_id or uuid4().hex
    root = settings.data_dir.resolve() / "snapshots" / snapshot_id
    root.mkdir(parents=True, exist_ok=False)
    excluded, manifest, blob_ids = [], {}, {}
    total = 0
    commit, dirty = None, False
    try:
        for directory, dirs, files in os.walk(repo, followlinks=False):
            current = Path(directory)
            for name in list(dirs):
                item = current / name
                if name.lower() in EXCLUDED_DIRS or is_link(item) or item.resolve() == settings.data_dir.resolve():
                    excluded.append(f"{item.relative_to(repo).as_posix()}: excluded_directory")
                    dirs.remove(name)
            for name in sorted(files):
                item = current / name
                relative = item.relative_to(repo).as_posix()
                lower = name.lower()
                reason = None
                if is_link(item) or not item.is_file() or not item.resolve().is_relative_to(repo):
                    reason = "symlink_or_special"
                elif lower.startswith(".env") or lower in SECRET_NAMES or item.suffix.lower() in {".pem", ".key", ".p12", ".pfx"} or lower.endswith((".min.js", ".min.css", ".lock")):
                    reason = "secret_or_generated"
                elif item.suffix.lower() not in TEXT_SUFFIXES and lower not in {"license", "dockerfile", "makefile"}:
                    reason = "unsupported_or_binary"
                elif item.stat().st_size > settings.max_file_bytes:
                    reason = "file_limit"
                if reason:
                    excluded.append(f"{relative}: {reason}")
                    continue
                # Bounded read; a source file growing during import cannot bypass limits.
                raw = secure_read(repo, relative, settings.max_file_bytes)
                if len(raw) > settings.max_file_bytes:
                    excluded.append(f"{relative}: file_limit")
                    continue
                try:
                    decode_text(raw, item.suffix.lower())
                except (UnicodeError, SyntaxError):
                    excluded.append(f"{relative}: non_text_encoding")
                    continue
                total += len(raw)
                if total > settings.max_text_bytes or total > settings.max_snapshot_bytes:
                    raise ValueError("snapshot_total_limit")
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                manifest[relative] = hashlib.sha256(raw).hexdigest()
                blob_ids[relative] = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        commit = verified_commit(repo, blob_ids)
        dirty = False if commit is not None else None  # Unknown is not evidence of a dirty Git working tree.
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return RepositorySnapshot(id=snapshot_id, source=str(repo), commit_sha=commit, manifest_hash=digest, root=root, status="ready", manifest=manifest, excluded_files=excluded, dirty=dirty)
    except BaseException:
        shutil.rmtree(root)
        raise
