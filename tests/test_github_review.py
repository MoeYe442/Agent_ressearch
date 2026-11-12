import asyncio
import socket
import struct
import threading
import time
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
import zipfile
from repolens.config import Settings
from repolens.github_client import GitHubClient, GitHubError, GitHubSource
from repolens.github_import import import_github_snapshot
from repolens.models import RepositorySnapshot
from repolens.tasks import TaskService
from tests.github_fixtures import GitHubFixture, archive, public_dns, response
from tests.test_github_import import prepare


@pytest.mark.parametrize("names", [("Pkg/a.py", "pkg/b.py"), ("pkg/e\u0301/a.py", "pkg/é/b.py")])
def test_implicit_directory_aliases_rejected(tmp_path, names):
    settings, resolved, path, _ = prepare(tmp_path, {name: b"pass\n" for name in names})
    with pytest.raises(GitHubError, match="github_archive_path|github_archive_duplicate"):
        import_github_snapshot(resolved, path, settings, uuid4().hex)


@pytest.mark.parametrize("name", ["CON .py", "COM¹.py", "LPT²/file.py", "CONIN$.py", "CONOUT$.py"])
def test_all_windows_reserved_device_spellings_rejected(tmp_path, name):
    settings, resolved, path, _ = prepare(tmp_path, {name: b"pass\n"})
    with pytest.raises(GitHubError, match="github_archive_path"):
        import_github_snapshot(resolved, path, settings, uuid4().hex)


def test_dns_obeys_request_deadline(tmp_path):
    async def slow_dns(host):
        await asyncio.sleep(.5)
        return ["140.82.112.4"]
    settings=Settings(workspace_root=tmp_path,data_dir=tmp_path/"data",github_request_timeout=.03)
    adapter=GitHubClient(settings,transport=httpx.MockTransport(GitHubFixture()),resolve_host=slow_dns)
    started=time.monotonic()
    with pytest.raises(GitHubError,match="github_import_timeout"):
        adapter.resolve(GitHubSource.parse("https://github.com/example/demo"))
    assert time.monotonic()-started<.3


def test_blocked_os_dns_does_not_delay_run_shutdown(tmp_path, monkeypatch):
    release=threading.Event()
    original=socket.getaddrinfo
    def blocked(*args,**kwargs):
        release.wait(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(socket,"getaddrinfo",blocked)
    settings=Settings(workspace_root=tmp_path,data_dir=tmp_path/"data",github_import_timeout=.04)
    adapter=GitHubClient(settings,transport=httpx.MockTransport(GitHubFixture()))
    started=time.monotonic()
    try:
        with pytest.raises(GitHubError,match="github_import_timeout"):
            adapter.resolve(GitHubSource.parse("https://github.com/example/demo"))
        assert time.monotonic()-started<.4
    finally:
        release.set()


def test_restart_cleans_only_interrupted_import_artifacts(indexed):
    settings,db,_,_,_,_=indexed
    snapshot_id="f"*32
    root=settings.data_dir/"snapshots"/snapshot_id
    root.mkdir(parents=True)
    (root/"partial.py").write_text("partial")
    downloads=settings.data_dir/"downloads"
    downloads.mkdir()
    own=downloads/(snapshot_id+".zip")
    own.write_bytes(b"partial")
    keep=downloads/"keep.zip"
    keep.write_bytes(b"keep")
    db.put_snapshot(RepositorySnapshot(id=snapshot_id,source="https://github.com/example/demo",source_type="github",root=root))
    service=TaskService(settings,db,None)
    service.start()
    try:
        assert not own.exists() and not root.exists()
        assert keep.read_bytes()==b"keep"
        assert db.get_snapshot(snapshot_id).error_code=="interrupted_import"
    finally:
        service.stop()


def test_indexing_failure_removes_own_snapshot(indexed,monkeypatch):
    from repolens import tasks
    settings,db,snapshot,_,_,_=indexed
    def fail(*args):
        raise RuntimeError("index failure")
    monkeypatch.setattr(tasks,"build_index",fail)
    service=TaskService(settings,db,None)
    service.start()
    try:
        imported=service.import_repository(Path(snapshot.source))
        for _ in range(300):
            saved=db.get_snapshot(imported.id)
            if saved.status=="failed":
                break
            time.sleep(.01)
        assert saved.status=="failed"
        assert not saved.root.exists()
        assert snapshot.root.exists()
    finally:
        service.stop()


def test_shutdown_cannot_publish_ready_after_return(indexed):
    settings,db,_,_,_,_=indexed
    gate,entered=threading.Event(),threading.Event()
    fixture=GitHubFixture()
    async def handler(request):
        if request.url.host=="codeload.github.com":
            entered.set()
            while not gate.is_set():
                await asyncio.sleep(.01)
        return fixture(request)
    factory=lambda settings:GitHubClient(settings,transport=httpx.MockTransport(handler),resolve_host=public_dns)
    service=TaskService(settings.model_copy(update={"provider_timeout":.01,"github_request_timeout":5}),db,None,factory)
    service.start()
    imported=service.import_github_repository("https://github.com/example/demo")
    try:
        assert entered.wait(3)
        service.stop()
        gate.set()
        time.sleep(.1)
        assert not service.worker.is_alive()
        assert db.get_snapshot(imported.id).status=="failed"
    finally:
        gate.set()
        service.stop()


@pytest.mark.parametrize("compression", [zipfile.ZIP_BZIP2,zipfile.ZIP_LZMA])
def test_only_bounded_archive_compression_is_accepted(tmp_path,compression):
    settings,resolved,path,fixture=prepare(tmp_path,{"a.py":b"pass\n"})
    with zipfile.ZipFile(path,"w",compression=compression) as z:
        z.writestr("root/a.py",b"pass\n")
    with pytest.raises(GitHubError,match="github_archive_compression"):
        import_github_snapshot(resolved,path,settings,uuid4().hex)


def test_central_directory_limit_precedes_zipinfo_allocation(tmp_path,monkeypatch):
    from repolens import github_import
    settings,resolved,path,_=prepare(tmp_path,{"a.py":b"pass\n","b.py":b"pass\n"})
    data=bytearray(path.read_bytes())
    offset=data.rfind(b"PK\x05\x06")
    struct.pack_into("<HH",data,offset+8,1,1)  # forged low entry count must not bypass actual scan
    path.write_bytes(data)
    def must_not_allocate(*args,**kwargs):
        raise AssertionError("ZipInfo allocation reached before member limit")
    monkeypatch.setattr(github_import.zipfile,"ZipFile",must_not_allocate)
    with pytest.raises(GitHubError,match="github_member_limit"):
        import_github_snapshot(resolved,path,settings.model_copy(update={"github_max_members":1}),uuid4().hex)


def test_deep_archive_path_is_rejected_before_writing(tmp_path):
    settings,resolved,path,_=prepare(tmp_path,{"/".join(["d"]*100)+"/a.py":b"pass\n"})
    with pytest.raises(GitHubError,match="github_archive_path"):
        import_github_snapshot(resolved,path,settings,uuid4().hex)


def test_download_does_not_truncate_or_remove_preexisting_file(tmp_path):
    settings=Settings(workspace_root=tmp_path,data_dir=tmp_path/"data")
    adapter=GitHubClient(settings,transport=httpx.MockTransport(GitHubFixture()),resolve_host=public_dns)
    resolved=adapter.resolve(GitHubSource.parse("https://github.com/example/demo"))
    destination=tmp_path/"owned-by-another-job.zip"
    destination.write_bytes(b"keep")
    with pytest.raises(GitHubError,match="github_download_exists"):
        adapter.download_archive(resolved,destination)
    assert destination.read_bytes()==b"keep"


def test_symlinked_download_directory_is_not_followed(tmp_path):
    import os,subprocess
    if os.name!="nt":
        pytest.skip("Windows junction")
    settings=Settings(workspace_root=tmp_path,data_dir=tmp_path/"data")
    adapter=GitHubClient(settings,transport=httpx.MockTransport(GitHubFixture()),resolve_host=public_dns)
    resolved=adapter.resolve(GitHubSource.parse("https://github.com/example/demo"))
    outside=tmp_path/"outside"
    outside.mkdir()
    junction=tmp_path/"downloads"
    subprocess.run(["cmd","/c","mklink","/J",str(junction),str(outside)],check=True,capture_output=True)
    with pytest.raises(GitHubError,match="github_download_storage"):
        adapter.download_archive(resolved,junction/"new.zip")
    assert not (outside/"new.zip").exists()


def test_upstream_non_object_json_is_stable_protocol_error(tmp_path):
    settings=Settings(workspace_root=tmp_path,data_dir=tmp_path/"data")
    adapter=GitHubClient(settings,transport=httpx.MockTransport(lambda r:response(json=[])),resolve_host=public_dns)
    with pytest.raises(GitHubError,match="github_protocol_error"):
        adapter.resolve(GitHubSource.parse("https://github.com/example/demo"))


def test_persisted_legacy_snapshot_is_normalized_in_list(indexed):
    from fastapi.testclient import TestClient
    from repolens.api import create_app
    settings,db,snapshot,_,_,_=indexed
    raw=snapshot.model_dump(mode="json")
    for field in ["source_type","requested_ref","archive_hash"]:
        raw.pop(field)
    db.put("snapshots",snapshot.id,raw)
    with TestClient(create_app(settings),client=("127.0.0.1",1)) as client:
        listed=next(item for item in client.get("/repositories").json() if item["id"]==snapshot.id)
        assert listed["source_type"]=="local"
        assert listed["requested_ref"] is None
        assert client.get("/repositories/"+snapshot.id).json()["source_type"]=="local"


def test_malformed_archive_redirect_is_stable_protocol_error(tmp_path):
    settings=Settings(workspace_root=tmp_path,data_dir=tmp_path/"data")
    adapter=GitHubClient(settings,transport=httpx.MockTransport(GitHubFixture()),resolve_host=public_dns)
    resolved=adapter.resolve(GitHubSource.parse("https://github.com/example/demo"))
    adapter.transport=httpx.MockTransport(lambda r:response(302,headers={"Location":"https://[broken"}))
    with pytest.raises(GitHubError,match="github_protocol_error|github_network_destination"):
        adapter.download_archive(resolved,tmp_path/"archive.zip")
