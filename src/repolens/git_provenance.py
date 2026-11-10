"""Bounded, pure-data Git provenance. Never loads config, hooks, alternates or executables.

Loose SHA-1 objects only. Unsupported/packed/worktree metadata falls back to manifest.
"""
import hashlib
import re
import zlib
import time
from repolens.secure_io import secure_read

OID = re.compile(r"^[0-9a-f]{40}$")
OBJECT_LIMIT = 2 * 1024 * 1024


def verified_commit(repo, blob_ids):
    try:
        consumed = 0
        deadline = time.monotonic() + 5
        def read(path, limit=OBJECT_LIMIT):
            nonlocal consumed
            if time.monotonic() > deadline:
                raise ValueError("git_metadata_limit")
            raw = secure_read(repo, ".git/" + path, limit)
            consumed += len(raw)
            if consumed > 16 * 1024 * 1024:
                raise ValueError("git_metadata_limit")
            if len(raw) > limit:
                raise ValueError("git_metadata_limit")
            return raw

        head = read("HEAD", 4096).decode("ascii").strip()
        if head.startswith("ref: "):
            ref = head[5:]
            if not ref.startswith("refs/") or ".." in ref or "\\" in ref or ":" in ref:
                return None
            head = read(ref, 4096).decode("ascii").strip()
        if not OID.fullmatch(head):
            return None
        count = 0

        def object_data(oid, expected):
            nonlocal count
            count += 1
            if count > 10000 or not OID.fullmatch(oid):
                raise ValueError("git_metadata_limit")
            packed = read("objects/" + oid[:2] + "/" + oid[2:])
            decoder = zlib.decompressobj()
            data = decoder.decompress(packed, OBJECT_LIMIT + 1)
            if len(data) > OBJECT_LIMIT or not decoder.eof or hashlib.sha1(data).hexdigest() != oid:
                raise ValueError("git_object_integrity")
            header, body = data.split(b"\0", 1)
            if header != f"{expected} {len(body)}".encode():
                raise ValueError("git_object_type")
            return body

        commit = object_data(head, "commit")
        tree = commit.split(b"\n", 1)[0]
        if not tree.startswith(b"tree "):
            return None
        entries = {}
        def walk(tree_oid, prefix="", depth=0):
            if depth > 80:
                raise ValueError("git_tree_depth")
            raw = object_data(tree_oid, "tree")
            offset = 0
            while offset < len(raw):
                stop = raw.index(b"\0", offset)
                mode, name = raw[offset:stop].split(b" ", 1)
                oid_bytes = raw[stop + 1:stop + 21]
                if len(oid_bytes) != 20 or b"/" in name or name in {b".", b".."}:
                    raise ValueError("invalid_git_tree")
                path = prefix + name.decode("utf-8")
                oid = oid_bytes.hex()
                if mode == b"40000":
                    walk(oid, path + "/", depth + 1)
                elif mode in {b"100644", b"100755"}:
                    entries[path] = oid
                offset = stop + 21
        walk(tree[5:].decode("ascii"))
        # Every included byte must belong to this commit; excluded files remain explicitly excluded.
        return head if all(entries.get(path) == oid for path, oid in blob_ids.items()) else None
    except (OSError, ValueError, UnicodeError, zlib.error, RecursionError):
        return None
