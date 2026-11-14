"""Official PostgreSQL checkpoint format with transactional execution fencing."""
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from repolens.postgres import Connection,STATE_LOCK


def connection(db):
    return psycopg.connect(db.postgres_url,autocommit=True,prepare_threshold=0,row_factory=dict_row,connect_timeout=5)


def setup_postgres(db):
    # Official setup includes CREATE INDEX CONCURRENTLY: it must run in autocommit,
    # outside the application's transaction. A separate session lock guards DDL.
    with connection(db) as conn:
        conn.execute('SELECT pg_advisory_lock(%s)',(STATE_LOCK+1,))
        try:PostgresSaver(conn,serde=JsonPlusSerializer(pickle_fallback=False,allowed_msgpack_modules=None)).setup()
        finally:conn.execute('SELECT pg_advisory_unlock(%s)',(STATE_LOCK+1,))


class FencedPostgresSaver(PostgresSaver):
    def __init__(self,conn,session):
        super().__init__(conn,serde=JsonPlusSerializer(pickle_fallback=False,allowed_msgpack_modules=None))
        self.session=session

    @contextmanager
    def _cursor(self,*,pipeline=False):
        # Deliberately avoid the base class's non-transactional pipeline writes.
        with self.lock,self.conn.transaction():
            self.conn.execute("SET LOCAL lock_timeout = '20s'")
            self.conn.execute('SELECT pg_advisory_xact_lock(%s)',(STATE_LOCK,))
            self.session.guard(Connection(self.conn))
            with self.conn.cursor(binary=True) as cursor:yield cursor


@contextmanager
def postgres_saver_for(session):
    with connection(session.db) as conn:yield FencedPostgresSaver(conn,session)
