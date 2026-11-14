"""Offline, non-destructive SQLite history import into an empty PostgreSQL database."""
import argparse
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from repolens.config import Settings
from repolens.storage import open_database
from repolens.execution_store import WorkerLease
from repolens.indexing import RepositoryIndex
from repolens.secure_io import secure_read
from repolens.postgres_checkpoints import setup_postgres


def migrate(source_data,settings):
    if not settings.database_url.get_secret_value():raise ValueError('postgres_target_required')
    source_data=source_data.resolve();target_data=settings.data_dir.resolve()
    if source_data==target_data:raise ValueError('distinct_source_and_target_required')
    source_db=source_data/'repolens.sqlite'
    counts={}
    with sqlite3.connect(source_db.as_uri()+'?mode=ro',uri=True) as source:
        source.row_factory=sqlite3.Row
        source.execute('BEGIN')
        entities=[dict(row) for row in source.execute('SELECT kind,id,payload FROM entities')]
        for row in entities:
            value=json.loads(row['payload'])
            if row['kind']=='tasks' and (value['status'] in {'queued','running'} or (value['status']=='partial' and value.get('error_code')=='interrupted')):
                raise ValueError('finish_or_cancel_tasks_before_migration')
            if row['kind']=='snapshots' and value['status']=='importing':raise ValueError('finish_imports_before_migration')
            if row['kind']=='retrieval_jobs' and value['status'] in {'queued','building'}:raise ValueError('finish_indexing_before_migration')
        target=open_database(settings);WorkerLease(target);RepositoryIndex(target)
        setup_postgres(target)
        with target.atomic() as conn:
            for table in ['entities','events','execution_runs','execution_calls','execution_cache']:
                if conn.execute(f'SELECT COUNT(*) AS n FROM {table}').fetchone()['n']:raise ValueError('empty_postgres_target_required')
            lease=conn.execute('SELECT expires FROM worker_lease WHERE id=1').fetchone()
            if lease and lease['expires']>time.time():raise ValueError('stop_target_worker_before_migration')
            snapshots=target_data/'snapshots'
            if snapshots.exists() and any(snapshots.iterdir()):raise ValueError('empty_snapshot_target_required')
            for row in entities:
                value=json.loads(row['payload'])
                if row['kind']=='snapshots':
                    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',row['id']):raise ValueError('invalid_snapshot_id')
                    destination=snapshots/row['id'];value['root']=str(destination)
                    if value['status']=='ready':
                        destination.mkdir(parents=True,exist_ok=False)
                        for relative,checksum in value['manifest'].items():
                            raw=secure_read(source_data/'snapshots'/row['id'],relative,settings.max_file_bytes)
                            if len(raw)>settings.max_file_bytes or hashlib.sha256(raw).hexdigest()!=checksum:raise ValueError('migration_snapshot_integrity_error')
                            file=destination/relative;file.parent.mkdir(parents=True,exist_ok=True)
                            with file.open('xb') as output:output.write(raw)
                elif row['kind']=='tasks':value['resume_available']=False
                elif row['kind']=='retrieval_jobs':
                    value.update(status='failed',error_code='reindex_after_migration')
                conn.execute('INSERT INTO entities VALUES (?,?,?)',(row['kind'],row['id'],json.dumps(value,ensure_ascii=False)))
            counts['entities']=len(entities)
            tables={row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            columns={
                'events':['task_id','sequence','payload'],
                'symbols':['snapshot_id','path','symbol','start_line','end_line'],
                'text_chunks':['snapshot_id','path','start_line','end_line','content'],
                'execution_runs':['task_id','signature','started','deadline','budget'],
                'execution_calls':['id','task_id','cache_key','status','payload'],
                'execution_cache':['task_id','kind','cache_key','payload'],
            }
            for table,names in columns.items():
                if table not in tables:continue
                count=0
                for row in source.execute(f"SELECT {','.join(names)} FROM {table}"):
                    conn.execute(f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",tuple(row));count+=1
                counts[table]=count
    return {'imported':counts,'source_unchanged':True,'checkpoints_migrated':False,'retrieval_rebuild_required':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-data',required=True,type=Path)
    args=parser.parse_args()
    # Never print DSNs, credentials or arbitrary database exception messages.
    try:result=migrate(args.source_data,Settings.from_env())
    except Exception as exc:
        code=str(exc) if isinstance(exc,ValueError) else 'migration_failed_keep_source_and_inspect_target'
        print(json.dumps({'error_code':code}));raise SystemExit(1) from None
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
