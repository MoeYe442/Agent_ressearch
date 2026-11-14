"""Official SqliteSaver format with authority checks inside its write transaction."""
import sqlite3
from contextlib import contextmanager
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


class FencedSqliteSaver(SqliteSaver):
    def __init__(self,conn,session):
        super().__init__(conn,serde=JsonPlusSerializer(pickle_fallback=False,allowed_msgpack_modules=None))
        self.session=session
        self.setup()

    @contextmanager
    def cursor(self,transaction=True):
        with self.lock:
            self.setup();cursor=self.conn.cursor()
            try:
                if transaction:
                    self.conn.execute('BEGIN IMMEDIATE');self.session.guard(self.conn)
                yield cursor
            except BaseException:
                if transaction:self.conn.rollback()
                raise
            else:
                if transaction:self.conn.commit()
            finally:cursor.close()


@contextmanager
def saver_for(session):
    if session.db.backend=='postgres':
        from repolens.postgres_checkpoints import postgres_saver_for
        with postgres_saver_for(session) as saver:yield saver
        return
    conn=sqlite3.connect(session.db.path,check_same_thread=False,timeout=20)
    conn.row_factory=sqlite3.Row
    try:yield FencedSqliteSaver(conn,session)
    finally:conn.close()


def checkpoint_exists(db,task_id):
    with db.connect() as conn:
        if db.backend=='postgres':
            if not conn.execute("SELECT to_regclass('checkpoints') AS name").fetchone()['name']:return False
        elif not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoints'").fetchone():return False
        return conn.execute("SELECT 1 FROM checkpoints WHERE thread_id=? AND checkpoint_ns='' LIMIT 1",(task_id,)).fetchone() is not None
