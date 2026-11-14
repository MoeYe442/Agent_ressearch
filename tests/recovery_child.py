"""Crash-injection child only. Never imported by production modules."""
import argparse
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from langgraph.checkpoint.sqlite import SqliteSaver
from repolens.config import Settings
from repolens.storage import Database
from repolens.tasks import TaskService
from tests.scripted_model import ScriptedModel
from tests.collaborative_model import CollaborativeModel


def main():
    p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--workspace',required=True);p.add_argument('--snapshot',required=True);p.add_argument('--point',required=True);p.add_argument('--output',required=True);p.add_argument('--calls',required=True);args=p.parse_args()
    settings=Settings(workspace_root=Path(args.workspace),data_dir=Path(args.data),test_environment=True)
    db=Database(settings.data_dir/'repolens.sqlite');base=db.save_task_event
    def save(task,event,**kwargs):
        if (args.point=='response' and event.type=='model_completed') or (args.point=='terminal' and event.type=='task_finished' and task.status=='succeeded'):os._exit(72)
        return base(task,event,**kwargs)
    db.save_task_event=save
    class Model(ScriptedModel):
        def complete(self,messages,*a,**kw):
            with open(args.calls,'a',encoding='utf-8') as f:f.write('single\n')
            if args.point=='inflight':os._exit(72)
            return super().complete(messages,*a,**kw)
    class GraphModel(CollaborativeModel):
        def complete(self,messages,*a,**kw):
            system=messages[0]['content'];role=next((r for r in ['planner','reviewer','code','docs'] if 'ROLE: '+r in system),'unknown')
            with open(args.calls,'a',encoding='utf-8') as f:f.write(role+'\n')
            if role=='docs':threading.Event().wait(10)
            return super().complete(messages,*a,**kw)
    service=TaskService(settings,db,GraphModel() if args.point=='parallel' else Model())
    task=service.submit(args.snapshot,'Compare code and documentation' if args.point=='parallel' else 'Question',mode='collaborative' if args.point=='parallel' else 'single')
    Path(args.output).write_text(json.dumps({'task_id':task.id}),encoding='utf-8')
    if args.point=='parallel':
        conn=sqlite3.connect(db.path,check_same_thread=False);saver=SqliteSaver(conn);saver.setup()
        def watch():
            while True:
                checkpoint=saver.get_tuple({'configurable':{'thread_id':task.id}})
                if checkpoint and any(channel=='results' and isinstance(value,list) and any(row.get('role')=='code' for row in value) for _,channel,value in checkpoint.pending_writes):os._exit(72)
                time.sleep(.005)
        threading.Thread(target=watch,daemon=True).start()
    service.start()
    time.sleep(12)
    os._exit(73)


if __name__=='__main__':main()
