"""Small SQL dialect boundary for the application's fixed, parameterized queries."""
import re

# Short application transactions and saver writes share one lock domain. Single active
# execution worker is intentional; the lock also serializes API read/modify/write.
STATE_LOCK = 734882001
UPSERTS = {
    'entities': (('kind','id','payload'), ('kind','id')),
    'worker_lease': (('id','owner','epoch','expires'), ('id',)),
    'execution_calls': (('id','task_id','cache_key','status','payload'), ('id',)),
    'execution_cache': (('task_id','kind','cache_key','payload'), ('task_id','kind','cache_key')),
}


class Row(dict):
    def __getitem__(self,key):
        return list(self.values())[key] if isinstance(key,int) else super().__getitem__(key)


class Cursor:
    def __init__(self,cursor):self.raw=cursor
    def fetchone(self):
        row=self.raw.fetchone()
        return Row(row) if row is not None else None
    def fetchall(self):return [Row(row) for row in self.raw.fetchall()]
    def __iter__(self):return (Row(row) for row in self.raw)


class Connection:
    def __init__(self,raw):self.raw=raw
    @property
    def in_transaction(self):return True
    def execute(self,sql,params=None):
        if sql.strip().upper()=='BEGIN IMMEDIATE':return self
        match=re.match(r'INSERT OR REPLACE INTO (\w+) VALUES (.+)$',sql,re.I|re.S)
        if match:
            table,values=match.groups()
            columns,keys=UPSERTS[table.lower()]
            changes=','.join(f'{name}=EXCLUDED.{name}' for name in columns if name not in keys)
            sql=f"INSERT INTO {table} ({','.join(columns)}) VALUES {values} ON CONFLICT ({','.join(keys)}) DO UPDATE SET {changes}"
        sql=sql.replace('ORDER BY rowid DESC','ORDER BY id DESC')
        # Epoch timestamps need double precision (PostgreSQL REAL is float32).
        if sql.lstrip().upper().startswith('CREATE TABLE'):
            sql=re.sub(r'\bREAL\b','DOUBLE PRECISION',sql,flags=re.I)
        # psycopg parses literal percent signs too when parameters are supplied.
        if params is not None:sql=sql.replace('%','%%')
        sql=sql.replace('?', '%s')
        return Cursor(self.raw.execute(sql,params))
