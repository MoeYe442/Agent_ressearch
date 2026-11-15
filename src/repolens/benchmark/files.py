"""Bounded local artifacts, atomic publication and crash-safe single-runner locking."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
from uuid import uuid4
from repolens.benchmark.protocol import digest,Plan

MAX_FILE=16*1024*1024


def read_json(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_FILE:raise ValueError('artifact_missing_or_oversized')
    return json.loads(path.read_text(encoding='utf-8'),parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite_json')))


class Artifacts:
    def __init__(self,root):self.root=Path(root).resolve()
    def path(self,name):
        path=self.root/name
        if not path.resolve().is_relative_to(self.root) or any(part.is_symlink() for part in [path,*list(path.parents)[:len(Path(name).parts)]]):raise ValueError('artifact_path_denied')
        return path
    def read(self,name):
        envelope=read_json(self.path(name))
        if not isinstance(envelope,dict) or envelope.get('checksum')!=digest(envelope.get('value')):raise ValueError('artifact_checksum_mismatch')
        return envelope['value']
    def write(self,name,value,*,exclusive=False):
        path=self.path(name);path.parent.mkdir(parents=True,exist_ok=True)
        raw=json.dumps({'checksum':digest(value),'value':value},ensure_ascii=False,indent=2,allow_nan=False).encode()
        if len(raw)>MAX_FILE:raise ValueError('artifact_size_limit')
        temporary=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
        with temporary.open('xb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
        if exclusive:
            if os.name=='nt':os.rename(temporary,path)
            else:os.link(temporary,path);temporary.unlink()
        else:temporary.replace(path)
    def plan(self):return Plan.model_validate(self.read('plan.json'))


@contextmanager
def runner_lock(artifacts):
    artifacts.root.mkdir(parents=True,exist_ok=True)
    path=artifacts.path('.runner.lock')
    flags=os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0)
    fd=os.open(path,flags,0o600)
    try:
        if os.fstat(fd).st_size==0:os.write(fd,b'0')
        os.lseek(fd,0,os.SEEK_SET)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:os.close(fd)
