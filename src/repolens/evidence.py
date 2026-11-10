import hashlib
from pathlib import PurePosixPath, PureWindowsPath
from repolens.models import Evidence
from repolens.repositories import decode_text, is_link
from repolens.secure_io import secure_read, physical_lines


class EvidenceStore:
    def __init__(self, db):
        self.db = db

    def file_text(self, snapshot_id, path, *, allow_importing=False):
        snapshot = self.db.get_snapshot(snapshot_id)
        if snapshot.status != "ready" and not (allow_importing and snapshot.status == "importing"):
            raise ValueError("snapshot_not_ready")
        if not path or "\\" in path or ":" in path or ".." in PurePosixPath(path).parts or PureWindowsPath(path).is_absolute() or PurePosixPath(path).is_absolute():
            raise ValueError("invalid_path")
        if path not in snapshot.manifest:
            raise ValueError("file_not_in_snapshot")
        root = snapshot.root.absolute()
        file = root / path
        current = file
        while current != root:
            if is_link(current):
                raise ValueError("snapshot_link")
            current = current.parent
        if not file.resolve(strict=True).is_relative_to(root):
            raise ValueError("invalid_path")
        raw = secure_read(root, path, 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != snapshot.manifest[path]:
            raise ValueError("snapshot_integrity_error")
        return decode_text(raw, file.suffix.lower())

    def read_evidence(self, snapshot_id, path, start_line=1, end_line=None):
        lines = physical_lines(self.file_text(snapshot_id, path))
        if end_line is None:
            end_line = min(len(lines), start_line + 79)
        if start_line < 1 or end_line < start_line or end_line > len(lines) or end_line - start_line + 1 > 160:
            raise ValueError("invalid_line_range")
        excerpt = "".join(lines[start_line - 1:end_line])
        digest = hashlib.sha256(excerpt.encode()).hexdigest()
        evidence_id = hashlib.sha256(f"{snapshot_id}:{path}:{start_line}:{end_line}:{digest}".encode()).hexdigest()
        evidence = Evidence(id=evidence_id, snapshot_id=snapshot_id, path=path, start_line=start_line, end_line=end_line, excerpt=excerpt, content_hash=digest, commit_sha=self.db.get_snapshot(snapshot_id).commit_sha)
        self.db.put("evidence", evidence_id, evidence)
        return evidence

    def get(self, evidence_id, snapshot_id=None):
        item = Evidence.model_validate(self.db.get("evidence", evidence_id))
        if snapshot_id is not None and snapshot_id != item.snapshot_id:
            raise ValueError("snapshot_mismatch")
        fresh = self.read_evidence(item.snapshot_id, item.path, item.start_line, item.end_line)
        if fresh != item:
            raise ValueError("evidence_integrity_error")
        return item

    def validate_evidence(self, evidence_id, snapshot_id):
        try:
            self.get(evidence_id, snapshot_id)
            return True
        except (KeyError, ValueError, OSError):
            return False
