"""Dedicated single-active-worker process; API processes never execute jobs."""
import argparse
import signal
import threading
import time
from repolens.config import Settings
from repolens.storage import open_database
from repolens.tasks import TaskService
from repolens.model_client import configured_model


def main():
    parser=argparse.ArgumentParser(description='RepoLens dedicated worker')
    parser.add_argument('--health',action='store_true')
    args=parser.parse_args()
    settings=Settings.from_env().model_copy(update={'execution_mode':'worker'})
    db=open_database(settings)
    if args.health:
        with db.connect() as conn:
            row=conn.execute('SELECT expires FROM worker_lease WHERE id=1').fetchone()
        raise SystemExit(0 if row and row['expires']>time.time() else 1)
    service=TaskService(settings,db,configured_model(settings))
    stopped=threading.Event()
    def stop(signum,frame):stopped.set()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,stop)
    try:
        # Container restarts may precede the previous worker's five-second expiry.
        while not stopped.is_set():
            try:service.start();break
            except ValueError as exc:
                if str(exc)!='worker_already_running':raise
                stopped.wait(1)
        while not stopped.wait(.25):
            if service.stopping.is_set() or not service.worker or not service.worker.is_alive():
                raise RuntimeError('worker_authority_or_loop_lost')
    finally:service.stop()


if __name__=='__main__':main()
