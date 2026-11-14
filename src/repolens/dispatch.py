"""Durable database dispatch with optional, disposable Redis wake notifications."""
import json
import queue
import threading
import time


class DurableQueue:
    def __init__(self,db,settings,lease):
        self.db,self.lease=db,lease
        self.current=threading.local()
        self.redis=None;self.degraded=False;self.name=settings.redis_queue
        url=settings.redis_url.get_secret_value()
        if url:
            import redis
            self.redis=redis.Redis.from_url(url,decode_responses=True,socket_connect_timeout=1,socket_timeout=2)
        with db.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS dispatch_jobs (kind TEXT, job_id TEXT, state TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, PRIMARY KEY(kind,job_id))')

    def put(self,item):
        kind,key=item
        with self.db.connect() as conn:
            conn.execute("INSERT INTO dispatch_jobs VALUES (?,?,'pending',?) ON CONFLICT(kind,job_id) DO UPDATE SET state='pending',created=excluded.created",(kind,key,time.time()))
        # A notification may precede an outer transaction commit or be lost. The
        # consumer always polls the authoritative outbox, never trusts Redis state.
        if self.redis:self.db.on_commit(lambda:self._notify(kind,key))

    def _notify(self,kind,key):
        if self.redis:
            try:
                with self.redis.pipeline() as pipe:
                    pipe.lpush(self.name,json.dumps({'kind':kind,'id':key}))
                    pipe.ltrim(self.name,0,999);pipe.execute()
                self.degraded=False
            except Exception:self.degraded=True

    def is_pending(self,kind,key):
        with self.db.connect() as conn:
            row=conn.execute('SELECT state FROM dispatch_jobs WHERE kind=? AND job_id=?',(kind,key)).fetchone()
        return bool(row and row['state']=='pending')

    def abandon_claimed(self):
        with self.db.atomic() as conn:
            self.lease.guard(conn)
            conn.execute("UPDATE dispatch_jobs SET state='done' WHERE state='claimed'")

    def get(self,timeout=.1):
        with self.db.atomic() as conn:
            self.lease.guard(conn)
            row=conn.execute("SELECT kind,job_id FROM dispatch_jobs WHERE state='pending' ORDER BY created,kind,job_id LIMIT 1").fetchone()
            if row:
                item=(row['kind'],row['job_id'])
                conn.execute("UPDATE dispatch_jobs SET state='claimed' WHERE kind=? AND job_id=?",item)
                self.current.item=item
                return item
        if self.redis:
            try:self.redis.brpop(self.name,timeout=max(.1,timeout));self.degraded=False
            except Exception:self.degraded=True;time.sleep(timeout)
        else:time.sleep(timeout)
        raise queue.Empty

    def task_done(self):
        item=getattr(self.current,'item',None)
        if item:
            with self.db.atomic() as conn:
                self.lease.guard(conn)
                conn.execute("UPDATE dispatch_jobs SET state='done' WHERE kind=? AND job_id=?",item)
            self.current.item=None

    def close(self):
        if self.redis:self.redis.close()
