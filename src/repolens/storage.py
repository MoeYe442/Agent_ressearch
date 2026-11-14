import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from repolens.models import RepositorySnapshot


class AtomicSqliteConnection(sqlite3.Connection):
    def execute(self,sql,parameters=()):
        if sql.strip().upper()=='BEGIN IMMEDIATE' and self.in_transaction:return self.cursor()
        return super().execute(sql,parameters)


class Database:
    def __init__(self, path: Path, *, postgres_url=None):
        self.path = Path(path)
        self.postgres_url=postgres_url
        self.backend='postgres' if postgres_url else 'sqlite'
        self.local=threading.local()
        self.worker_guard=None
        if not postgres_url:self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            if not postgres_url:conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS entities (kind TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(kind,id))")
            conn.execute("CREATE TABLE IF NOT EXISTS events (task_id TEXT, sequence INTEGER, payload TEXT NOT NULL, PRIMARY KEY(task_id,sequence))")

    @contextmanager
    def connect(self):
        active=getattr(self.local,'connection',None)
        if active is not None:
            yield active
            return
        if self.postgres_url:
            import psycopg
            from psycopg.rows import dict_row
            from repolens.postgres import Connection,STATE_LOCK
            with psycopg.connect(self.postgres_url,row_factory=dict_row,connect_timeout=5) as raw:
                raw.execute("SET LOCAL lock_timeout = '20s'")
                raw.execute('SELECT pg_advisory_xact_lock(%s)',(STATE_LOCK,))
                self.local.connection=Connection(raw)
                self.local.hooks=[]
                try:
                    if self.worker_guard:self.worker_guard(self.local.connection)
                    yield self.local.connection
                    hooks=self.local.hooks
                finally:self.local.connection=None
            for hook in hooks:hook()
            return
        conn = sqlite3.connect(self.path, timeout=20,factory=AtomicSqliteConnection)
        conn.row_factory = sqlite3.Row
        try:
            self.local.connection=conn
            self.local.hooks=[]
            if self.worker_guard:
                conn.execute('BEGIN IMMEDIATE')
                self.worker_guard(conn)
            yield conn
            conn.commit()
            hooks=self.local.hooks
        except BaseException:
            conn.rollback()
            raise
        finally:
            self.local.connection=None
            conn.close()
        for hook in hooks:hook()

    def on_commit(self,callback):
        if getattr(self.local,'connection',None) is not None:self.local.hooks.append(callback)
        else:callback()

    @contextmanager
    def atomic(self):
        """Share one transaction across nested domain operations in this thread."""
        if getattr(self.local,'connection',None) is not None:
            if not self.local.connection.in_transaction:self.local.connection.execute('BEGIN IMMEDIATE')
            yield self.local.connection
            return
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self.local.connection=conn
            try:yield conn
            finally:self.local.connection=None

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

    def save_task_event(self, task, event, report=None, graph=None, guard=None,extra_entities=None):
        """Task state and its corresponding event commit atomically."""
        from datetime import datetime, timezone
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if guard:guard(conn)
            sequence = conn.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE task_id=?", (task.id,)).fetchone()[0]
            event = event.model_copy(update={"task_id": task.id, "sequence": sequence, "timestamp": datetime.now(timezone.utc).isoformat()})
            conn.execute("INSERT OR REPLACE INTO entities VALUES ('tasks',?,?)", (task.id, task.model_dump_json()))
            if report is not None:
                conn.execute("INSERT OR REPLACE INTO entities VALUES ('reports',?,?)", (task.id, report.model_dump_json()))
            if graph is not None:
                conn.execute("INSERT OR REPLACE INTO entities VALUES ('graphs',?,?)", (task.id, json.dumps(graph, ensure_ascii=False)))
            for kind,key,payload in extra_entities or []:
                conn.execute('INSERT OR REPLACE INTO entities VALUES (?,?,?)',(kind,key,json.dumps(payload)))
            conn.execute("INSERT INTO events VALUES (?,?,?)", (task.id, sequence, event.model_dump_json()))
        return event

    def task_events(self, task_id, after_sequence=0):
        from repolens.models import TaskEvent
        with self.connect() as conn:
            rows = conn.execute("SELECT payload FROM events WHERE task_id=? AND sequence>? ORDER BY sequence", (task_id, after_sequence)).fetchall()
        return [TaskEvent.model_validate_json(row[0]) for row in rows]


def open_database(settings):
    return Database(settings.data_dir/'repolens.sqlite',postgres_url=settings.database_url.get_secret_value() or None)
