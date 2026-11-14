"""Fenced local execution authority and durable request journals."""
import hashlib
import json
import threading
import time
import sqlite3
from uuid import uuid4


class LeaseLost(Exception):
    pass


class WorkerPaused(BaseException):
    pass


class RecoveryRejected(BaseException):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def seal(value):
    return json.dumps({'checksum':digest(value),'value':value},ensure_ascii=False)


def unseal(raw,code):
    try:
        envelope=json.loads(raw)
        if envelope['checksum']!=digest(envelope['value']):raise ValueError()
        return envelope['value']
    except (TypeError,ValueError,KeyError):raise RecoveryRejected(code) from None


class WorkerLease:
    def __init__(self,db,ttl=5,clock=time.time,on_lost=lambda:None):
        self.db,self.ttl,self.clock=db,ttl,clock
        self.owner,self.epoch=uuid4().hex,0
        self.on_lost=on_lost
        self.halted=threading.Event();self.lost=threading.Event();self.thread=None
        with db.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS worker_lease (id INTEGER PRIMARY KEY, owner TEXT, epoch INTEGER, expires REAL)')
            conn.execute('CREATE TABLE IF NOT EXISTS execution_runs (task_id TEXT PRIMARY KEY, signature TEXT, started REAL, deadline REAL, budget TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS execution_calls (id TEXT PRIMARY KEY, task_id TEXT, cache_key TEXT, status TEXT, payload TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS execution_cache (task_id TEXT, kind TEXT, cache_key TEXT, payload TEXT, PRIMARY KEY(task_id,kind,cache_key))')

    def acquire(self):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM worker_lease WHERE id=1').fetchone()
            if row and row['expires']>self.clock() and row['owner']!=self.owner:
                raise ValueError('worker_already_running')
            self.epoch=(row['epoch'] if row else 0)+1
            conn.execute('INSERT OR REPLACE INTO worker_lease VALUES (1,?,?,?)',(self.owner,self.epoch,self.clock()+self.ttl))

    def guard(self,conn):
        row=conn.execute('SELECT * FROM worker_lease WHERE id=1').fetchone()
        if not row or row['owner']!=self.owner or row['epoch']!=self.epoch or self.lost.is_set():
            self.lost.set()
            raise LeaseLost()
        if row['expires']<=self.clock():
            # Renewal races are linearized with takeover by SQLite's writer lock.
            if conn.in_transaction:conn.execute('UPDATE worker_lease SET expires=? WHERE id=1',(self.clock()+self.ttl,))
            else:self.renew()

    def renew(self):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT owner,epoch FROM worker_lease WHERE id=1').fetchone()
            if not row or row['owner']!=self.owner or row['epoch']!=self.epoch or self.lost.is_set():
                self.lost.set();raise LeaseLost()
            conn.execute('UPDATE worker_lease SET expires=? WHERE id=1',(self.clock()+self.ttl,))

    def start_heartbeat(self):
        def beat():
            while not self.halted.wait(self.ttl/3):
                try:self.renew()
                except sqlite3.OperationalError as exc:
                    if 'locked' in str(exc).lower():continue
                    self.lost.set();self.on_lost();return
                except BaseException:self.lost.set();self.on_lost();return
        self.thread=threading.Thread(target=beat,name='repolens-lease',daemon=True);self.thread.start()

    def release(self):
        self.halted.set()
        if self.thread:self.thread.join()
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('UPDATE worker_lease SET owner=?,expires=0 WHERE id=1 AND owner=? AND epoch=?',('',self.owner,self.epoch))


class ExecutionSession:
    def __init__(self,db,task_id,epoch,lease,signature,*,seconds=900,stopping=lambda:False):
        self.db,self.task_id,self.epoch,self.lease=db,task_id,epoch,lease
        self.signature,self.stopping=signature,stopping
        encoded=json.dumps(signature,sort_keys=True)
        with db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE');self.guard(conn)
            row=conn.execute('SELECT * FROM execution_runs WHERE task_id=?',(task_id,)).fetchone()
            if row and row['signature']!=encoded:
                raise RecoveryRejected('recovery_configuration_changed')
            if not row:
                started=time.time()
                conn.execute('INSERT INTO execution_runs VALUES (?,?,?,?,NULL)',(task_id,encoded,started,started+seconds))
                self.started,self.deadline_utc=started,started+seconds
            else:self.started,self.deadline_utc=row['started'],row['deadline']

    def guard(self,conn):
        self.lease.guard(conn)
        row=conn.execute("SELECT payload FROM entities WHERE kind='tasks' AND id=?",(self.task_id,)).fetchone()
        if not row:raise LeaseLost()
        task=json.loads(row['payload'])
        if task.get('execution_epoch',0)!=self.epoch or task['status']!='running':raise LeaseLost()

    def check(self):
        with self.db.connect() as conn:self.guard(conn)
        if self.stopping():raise WorkerPaused()

    def load_budget(self):
        with self.db.connect() as conn:
            row=conn.execute('SELECT budget FROM execution_runs WHERE task_id=?',(self.task_id,)).fetchone()
        return unseal(row['budget'],'recovery_budget_corrupt') if row and row['budget'] else None

    def save_budget(self,state,*,record=None,cache=None):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE');self.guard(conn)
            conn.execute('UPDATE execution_runs SET budget=? WHERE task_id=?',(seal(state),self.task_id))
            for item in (record if isinstance(record,list) else [record] if record else []):
                conn.execute('INSERT OR REPLACE INTO execution_calls VALUES (?,?,?,?,?)',(item['id'],self.task_id,item.get('cache_key'),item['status'],json.dumps(item)))
            if cache:
                kind,key,value=cache
                conn.execute('INSERT OR REPLACE INTO execution_cache VALUES (?,?,?,?)',(self.task_id,kind,key,seal(value)))

    def cache_key(self,kind,payload):
        return digest({'signature':self.signature,'kind':kind,'payload':payload})

    def get_cache(self,kind,key):
        with self.db.connect() as conn:
            self.guard(conn)
            row=conn.execute('SELECT payload FROM execution_cache WHERE task_id=? AND kind=? AND cache_key=?',(self.task_id,kind,key)).fetchone()
        if not row:return None
        return unseal(row['payload'],'recovery_cache_corrupt')

    def save_tool(self,key,result):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE');self.guard(conn)
            conn.execute('INSERT OR REPLACE INTO execution_cache VALUES (?,?,?,?)',(self.task_id,'tool',key,seal(result)))
