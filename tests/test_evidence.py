import hashlib
import pytest


def test_evidence_matches_exact_lines(indexed):
    _, _, snapshot, _, store, _ = indexed
    evidence = store.read_evidence(snapshot.id, "app.py", 9, 11)
    assert evidence.excerpt == '    def run(self, task_id):\n        self.store.save(task_id, "running")\n        return {"status": "done"}\n'
    assert evidence.content_hash == hashlib.sha256(evidence.excerpt.encode()).hexdigest()
    assert store.validate_evidence(evidence.id, snapshot.id)
    assert store.read_evidence(snapshot.id, "app.py", 9, 11).id == evidence.id
    (snapshot.root / "app.py").write_text("tampered", encoding="utf-8")
    assert not store.validate_evidence(evidence.id, snapshot.id)


@pytest.mark.parametrize("path", ["../secret.py", "C:/secret.py", "/etc/passwd", "..\\secret.py", "app.py:stream"])
def test_rejects_parent_traversal_and_absolute_path(indexed, path):
    _, _, snapshot, _, store, _ = indexed
    with pytest.raises(ValueError):
        store.read_evidence(snapshot.id, path, 1, 2)


def test_rejects_snapshot_mismatch(indexed):
    _, _, snapshot, _, store, _ = indexed
    evidence = store.read_evidence(snapshot.id, "app.py", 1, 2)
    assert not store.validate_evidence(evidence.id, "other")
    with pytest.raises(ValueError):
        store.read_evidence(snapshot.id, "app.py", 1, 1000)
