import hashlib
import io
import json
import os
import re
import shutil
import stat
import tokenize
from pathlib import Path, PurePosixPath
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


def file_exclusion(path: str, size: int, settings: Settings):
    parts = PurePosixPath(path).parts
    name = parts[-1].lower()
    suffix = PurePosixPath(name).suffix
    if any(part.lower() in EXCLUDED_DIRS for part in parts[:-1]):
        return "excluded_directory"
    if name.startswith(".env") or name in SECRET_NAMES or suffix in {".pem", ".key", ".p12", ".pfx"} or name.endswith((".min.js", ".min.css", ".lock")):
        return "secret_or_generated"
    if suffix not in TEXT_SUFFIXES and name not in {"license", "dockerfile", "makefile"}:
        return "unsupported_or_binary"
    if size > settings.max_file_bytes:
        return "file_limit"
    return None


class SnapshotWriter:
    """Write filtered bytes only; callers retain responsibility for source access checks."""
    def __init__(self, settings, snapshot_id):
        if not re.fullmatch(r"[0-9a-f]{32}", snapshot_id):
            raise ValueError("invalid_snapshot_id")
        self.settings, self.id = settings, snapshot_id
        self.base = settings.data_dir.resolve() / "snapshots"
        if self.base.exists() and (is_link(self.base) or not self.base.resolve().is_relative_to(settings.data_dir.resolve())):
            raise ValueError("snapshot_storage_path")
        self.root = self.base / snapshot_id
        self.root.mkdir(parents=True, exist_ok=False)
        self.manifest, self.excluded, self.total = {}, [], 0

    def add(self, relative, raw):
        path = PurePosixPath(relative)
        if not path.parts or path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative:
            raise ValueError("invalid_path")
        reason = file_exclusion(relative, len(raw), self.settings)
        if reason:
            self.excluded.append(f"{relative}: {reason}")
            return False
        try:
            decode_text(raw, path.suffix.lower())
        except (UnicodeError, SyntaxError):
            self.excluded.append(f"{relative}: non_text_encoding")
            return False
        self.total += len(raw)
        if self.total > min(self.settings.max_text_bytes, self.settings.max_snapshot_bytes):
            raise ValueError("snapshot_total_limit")
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as file:
            file.write(raw)
        self.manifest[relative] = hashlib.sha256(raw).hexdigest()
        return True

    def finish(self, source, **metadata):
        digest = hashlib.sha256(json.dumps(self.manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return RepositorySnapshot(id=self.id, source=source, root=self.root, manifest=self.manifest, manifest_hash=digest, status="ready", excluded_files=self.excluded, **metadata)

    def abort(self):
        # Only this generated directory; never delete a pre-existing snapshot or linked root.
        if self.root.exists() and not is_link(self.root) and self.root.resolve().is_relative_to(self.base.resolve()):
            shutil.rmtree(self.root)


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
    writer = SnapshotWriter(settings, snapshot_id)
    excluded, blob_ids = writer.excluded, {}
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
                reason = None
                if is_link(item) or not item.is_file() or not item.resolve().is_relative_to(repo):
                    reason = "symlink_or_special"
                else:
                    reason = file_exclusion(relative, item.stat().st_size, settings)
                if reason:
                    excluded.append(f"{relative}: {reason}")
                    continue
                # Bounded read; a source file growing during import cannot bypass limits.
                raw = secure_read(repo, relative, settings.max_file_bytes)
                if writer.add(relative, raw):
                    blob_ids[relative] = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        commit = verified_commit(repo, blob_ids)
        dirty = False if commit is not None else None  # Unknown is not evidence of a dirty Git working tree.
        return writer.finish(str(repo), commit_sha=commit, dirty=dirty)
    except BaseException:
        writer.abort()
        raise
