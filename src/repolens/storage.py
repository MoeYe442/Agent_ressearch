import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from repolens.models import RepositorySnapshot


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS entities (kind TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(kind,id))")
            conn.execute("CREATE TABLE IF NOT EXISTS events (task_id TEXT, sequence INTEGER, payload TEXT NOT NULL, PRIMARY KEY(task_id,sequence))")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def put(self, kind, key, value):
        payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO entities VALUES (?,?,?)", (kind, key, json.dumps(payload, ensure_ascii=False)))

    def get(self, kind, key):
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM entities WHERE kind=? AND id=?", (kind, key)).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    def all(self, kind):
        with self.connect() as conn:
            return [json.loads(r[0]) for r in conn.execute("SELECT payload FROM entities WHERE kind=? ORDER BY rowid DESC", (kind,))]

    def put_snapshot(self, snapshot):
        self.put("snapshots", snapshot.id, snapshot)

    def get_snapshot(self, snapshot_id):
        return RepositorySnapshot.model_validate(self.get("snapshots", snapshot_id))

    def save_task_event(self, task, event, report=None):
        """Task state and its corresponding event commit atomically."""
        from datetime import datetime, timezone
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            sequence = conn.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE task_id=?", (task.id,)).fetchone()[0]
            event = event.model_copy(update={"task_id": task.id, "sequence": sequence, "timestamp": datetime.now(timezone.utc).isoformat()})
            conn.execute("INSERT OR REPLACE INTO entities VALUES ('tasks',?,?)", (task.id, task.model_dump_json()))
            if report is not None:
                conn.execute("INSERT OR REPLACE INTO entities VALUES ('reports',?,?)", (task.id, report.model_dump_json()))
            conn.execute("INSERT INTO events VALUES (?,?,?)", (task.id, sequence, event.model_dump_json()))
        return event

    def task_events(self, task_id, after_sequence=0):
        from repolens.models import TaskEvent
        with self.connect() as conn:
            rows = conn.execute("SELECT payload FROM events WHERE task_id=? AND sequence>? ORDER BY sequence", (task_id, after_sequence)).fetchall()
        return [TaskEvent.model_validate_json(row[0]) for row in rows]
