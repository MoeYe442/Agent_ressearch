"""Cleanup derived, generated import paths only; never trust persisted root strings."""
import re
import shutil
from repolens.repositories import is_link


def cleanup_import(settings, snapshot_id, *, snapshot=False, download=False):
    if not re.fullmatch(r"[0-9a-f]{32}", snapshot_id):
        return False
    data = settings.data_dir.resolve()
    success = True
    for category, enabled, name in [("snapshots", snapshot, snapshot_id), ("downloads", download, snapshot_id + ".zip")]:
        if not enabled:
            continue
        parent = data / category
        target = parent / name
        try:
            if not parent.exists():
                continue
            if is_link(parent) or parent.resolve().parent != data:
                success = False
                continue
            try:
                if is_link(target):
                    success = False
                    continue
            except FileNotFoundError:
                continue
            if not target.resolve().is_relative_to(parent):
                success = False
                continue
            if category == "snapshots":
                shutil.rmtree(target)
            else:
                target.unlink()
        except OSError:
            success = False
    return success
