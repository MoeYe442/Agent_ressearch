"""Validate ZIP metadata and Git blob identity before writing allowed snapshot text."""
import hashlib
from pathlib import PurePosixPath
import re
import stat
import unicodedata
import zipfile

from repolens.github_client import GitHubError
from repolens.repositories import SnapshotWriter, file_exclusion

RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE)


def safe_parts(path):
    if not path or path.startswith("/") or "\\" in path or ":" in path or any(ord(c) < 32 or ord(c) == 127 for c in path):
        raise GitHubError("github_archive_path")
    parts = path.split("/")
    for part in parts:
        if not part or part in {".", ".."} or part.endswith((".", " ")) or RESERVED.match(part) or any(c in part for c in '<>"|?*'):
            raise GitHubError("github_archive_path")
    return parts


def alias_key(path):
    return unicodedata.normalize("NFC", path).casefold()


def validated_members(archive, settings):
    members = archive.infolist()
    if len(members) > settings.github_max_members:
        raise GitHubError("github_member_limit")
    if sum(member.file_size for member in members) > settings.github_max_unpacked_bytes:
        raise GitHubError("github_unpacked_limit")
    records, seen, files, parents, wrapper = [], set(), set(), set(), None
    for member in members:
        raw = member.orig_filename
        path = raw[:-1] if member.is_dir() else raw
        parts = safe_parts(path)
        if wrapper is None:
            wrapper = parts[0]
        if parts[0] != wrapper or (len(parts) == 1 and not member.is_dir()):
            raise GitHubError("github_archive_path")
        if len(parts) == 1:
            continue
        relative = "/".join(parts[1:])
        key = alias_key(relative)
        ancestor_keys = {alias_key("/".join(parts[1:i])) for i in range(2, len(parts))}
        if key in seen or ancestor_keys & files:
            raise GitHubError("github_archive_duplicate")
        if not member.is_dir() and key in parents:
            raise GitHubError("github_archive_duplicate")
        seen.add(key)
        parents.update(ancestor_keys)
        if not member.is_dir():
            files.add(key)
        if member.flag_bits & 1:
            raise GitHubError("github_encrypted_archive")
        records.append((relative, member))
    if not wrapper:
        raise GitHubError("github_invalid_archive")
    return records


def import_github_snapshot(resolved, archive_path, settings, snapshot_id):
    writer = SnapshotWriter(settings, snapshot_id)
    try:
        for path in resolved.entries:
            safe_parts(path)
        with archive_path.open("rb") as source:
            digest, compressed = hashlib.sha256(), 0
            while chunk := source.read(64 * 1024):
                compressed += len(chunk)
                if compressed > settings.github_max_download_bytes:
                    raise GitHubError("github_download_limit")
                digest.update(chunk)
            source.seek(0)
            with zipfile.ZipFile(source) as archive:
                records = validated_members(archive, settings)
                present = set()
                for relative, member in records:
                    if member.is_dir():
                        continue
                    present.add(relative)
                    kind = stat.S_IFMT(member.external_attr >> 16) if member.create_system == 3 else 0
                    if kind not in {0, stat.S_IFREG}:
                        writer.excluded.append(f"{relative}: link_or_special")
                        continue
                    entry = resolved.entries.get(relative)
                    if entry is None:
                        raise GitHubError("github_archive_untracked_file")
                    if entry.type != "blob" or entry.mode not in {"100644", "100755"}:
                        writer.excluded.append(f"{relative}: git_link_or_submodule")
                        continue
                    reason = file_exclusion(relative, member.file_size, settings)
                    if reason:
                        writer.excluded.append(f"{relative}: {reason}")
                        continue
                    with archive.open(member) as file:
                        raw = file.read(settings.max_file_bytes + 1)
                    if len(raw) > settings.max_file_bytes:
                        raise GitHubError("github_archive_size_mismatch")
                    blob = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
                    if blob != entry.sha or (entry.size is not None and len(raw) != entry.size):
                        raise GitHubError("github_blob_mismatch")
                    writer.add(relative, raw)
                for path, entry in resolved.entries.items():
                    if entry.type != "tree" and path not in present:
                        reason = "git_link_or_submodule" if entry.type != "blob" or entry.mode == "120000" else (file_exclusion(path, entry.size or 0, settings) or "archive_omitted")
                        writer.excluded.append(f"{path}: {reason}")
        return writer.finish(resolved.source.url, source_type="github", requested_ref=resolved.source.requested_ref, commit_sha=resolved.commit_sha, archive_hash=digest.hexdigest(), dirty=False)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError):
        writer.abort()
        raise GitHubError("github_invalid_archive") from None
    except BaseException:
        writer.abort()
        raise
