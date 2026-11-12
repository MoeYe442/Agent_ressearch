"""Validate ZIP metadata and Git blob identity before writing allowed snapshot text."""
import hashlib
from pathlib import PureWindowsPath
import re
import stat
import struct
import unicodedata
import zipfile
import zlib

from repolens.github_client import GitHubError
from repolens.repositories import SnapshotWriter, file_exclusion

RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE)


def safe_parts(path):
    if not path or len(path.encode("utf-8")) > 4096 or path.startswith("/") or "\\" in path or ":" in path or any(ord(c) < 32 or ord(c) == 127 for c in path):
        raise GitHubError("github_archive_path")
    parts = path.split("/")
    if len(parts) > 80:
        raise GitHubError("github_archive_path")
    for part in parts:
        if not part or part in {".", ".."} or part.endswith((".", " ")) or PureWindowsPath(part).is_reserved() or RESERVED.match(part) or any(c in part for c in '<>"|?*'):
            raise GitHubError("github_archive_path")
    return parts


def alias_key(path):
    return unicodedata.normalize("NFC", path).casefold()


def check_central_directory(source, settings):
    """Bound metadata before ZipFile allocates its complete ZipInfo list.

    GitHub-sized archives need neither multi-disk, SFX nor ZIP64 structures;
    rejecting unsupported variants keeps both the scanner and decoder bounded.
    """
    source.seek(0, 2)
    size = source.tell()
    tail_start = max(0, size - 65557)
    source.seek(tail_start)
    tail = source.read(65557)
    position = tail.rfind(b"PK\x05\x06")
    end = None
    while position >= 0:
        if position + 22 <= len(tail):
            fields = struct.unpack("<4s4H2IH", tail[position:position + 22])
            if position + 22 + fields[-1] == len(tail):
                end = fields
                break
        position = tail.rfind(b"PK\x05\x06", 0, position)
    if end is None:
        raise GitHubError("github_invalid_archive")
    _, disk, directory_disk, disk_entries, entries, directory_size, directory_offset, _ = end
    if entries == 65535 or directory_size == 0xffffffff or directory_offset == 0xffffffff:
        raise GitHubError("github_archive_zip64_unsupported")
    if disk or directory_disk or disk_entries != entries or directory_offset + directory_size != tail_start + position:
        raise GitHubError("github_invalid_archive")
    if entries > settings.github_max_members:
        raise GitHubError("github_member_limit")
    if directory_size > settings.github_max_metadata_bytes:
        raise GitHubError("github_archive_metadata_limit")
    source.seek(directory_offset)
    stop, count, unpacked = directory_offset + directory_size, 0, 0
    while source.tell() < stop:
        header = source.read(46)
        if len(header) != 46:
            raise GitHubError("github_invalid_archive")
        values = struct.unpack("<4s6H3I5H2I", header)
        if values[0] != b"PK\x01\x02":
            raise GitHubError("github_invalid_archive")
        count += 1
        unpacked += values[9]
        if count > settings.github_max_members:
            raise GitHubError("github_member_limit")
        if unpacked > settings.github_max_unpacked_bytes:
            raise GitHubError("github_unpacked_limit")
        if values[4] not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise GitHubError("github_archive_compression")
        name_size, extra_size, comment_size = values[10:13]
        if name_size > 4096 or source.tell() + name_size + extra_size + comment_size > stop:
            raise GitHubError("github_archive_path")
        source.seek(name_size + extra_size + comment_size, 1)
    if source.tell() != stop or count != entries:
        raise GitHubError("github_invalid_archive")
    source.seek(0)


def validated_members(archive, settings, cancelled=lambda: False):
    members = archive.infolist()
    if len(members) > settings.github_max_members:
        raise GitHubError("github_member_limit")
    if sum(member.file_size for member in members) > settings.github_max_unpacked_bytes:
        raise GitHubError("github_unpacked_limit")
    records, seen, files, parents, spellings, wrapper = [], set(), set(), set(), {}, None
    for member in members:
        if cancelled():
            raise GitHubError("github_import_cancelled")
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
        for index in range(2, len(parts) + 1):
            prefix = "/".join(parts[1:index])
            prefix_key = alias_key(prefix)
            if prefix_key in spellings and spellings[prefix_key] != prefix:
                raise GitHubError("github_archive_duplicate")
            spellings[prefix_key] = prefix
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


def import_github_snapshot(resolved, archive_path, settings, snapshot_id, *, cancelled=lambda: False):
    writer = SnapshotWriter(settings, snapshot_id)
    try:
        for path in resolved.entries:
            if cancelled():
                raise GitHubError("github_import_cancelled")
            safe_parts(path)
        with archive_path.open("rb") as source:
            digest, compressed = hashlib.sha256(), 0
            while chunk := source.read(64 * 1024):
                if cancelled():
                    raise GitHubError("github_import_cancelled")
                compressed += len(chunk)
                if compressed > settings.github_max_download_bytes:
                    raise GitHubError("github_download_limit")
                digest.update(chunk)
            source.seek(0)
            check_central_directory(source, settings)
            with zipfile.ZipFile(source) as archive:
                records = validated_members(archive, settings, cancelled)
                present = set()
                for relative, member in records:
                    if cancelled():
                        raise GitHubError("github_import_cancelled")
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
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error, struct.error):
        writer.abort()
        raise GitHubError("github_invalid_archive") from None
    except BaseException:
        writer.abort()
        raise
