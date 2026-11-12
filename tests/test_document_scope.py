import hashlib
import pytest
from repolens.models import ToolContext
from repolens.document_scope import source_type,allows_path


def test_repository_documents_are_snapshot_bound(indexed):
    _,_,snapshot,_,store,_=indexed
    evidence=store.read_evidence(snapshot.id,'README.md',1,3)
    assert evidence.source_type=='repository_document'
    assert evidence.snapshot_id==snapshot.id
    assert store.validate_evidence(evidence.id,snapshot.id)


def test_old_markdown_evidence_id_remains_valid(indexed):
    _,db,snapshot,_,store,_=indexed
    evidence=store.read_evidence(snapshot.id,'README.md',1,3)
    raw=evidence.model_dump();raw.pop('source_type')
    db.put('evidence',evidence.id,raw)
    assert store.get(evidence.id).source_type=='repository_document'
    assert store.get(evidence.id).id==evidence.id


def test_source_directory_changes_do_not_change_document_evidence(indexed):
    from pathlib import Path
    _,_,snapshot,_,store,_=indexed
    before=store.read_evidence(snapshot.id,'README.md',1,3)
    (Path(snapshot.source)/'README.md').write_text('changed')
    assert store.get(before.id).excerpt==before.excerpt


def test_docs_search_filters_before_limit(indexed):
    from repolens.indexing import build_index,RepositoryIndex
    _,db,snapshot,_,_,_=indexed
    for i in range(25):
        path=f'a{i:02}.py';raw=b'marker=1\n'
        (snapshot.root/path).write_bytes(raw)
        snapshot.manifest[path]=hashlib.sha256(raw).hexdigest()
    raw=b'# marker\n'
    (snapshot.root/'z.md').write_bytes(raw)
    snapshot.manifest['z.md']=hashlib.sha256(raw).hexdigest()
    db.put_snapshot(snapshot);build_index(snapshot,db)
    hits=RepositoryIndex(db).search_text(snapshot.id,'marker',1,scope='docs')
    assert len(hits)==1 and hits[0].path=='z.md'


@pytest.mark.parametrize('scope,path',[('code','README.md'),('docs','app.py')])
def test_role_cannot_read_outside_scope(indexed,scope,path):
    _,_,snapshot,_,_,tools=indexed
    result=tools.invoke('read_file',{'path':path},ToolContext(snapshot_id=snapshot.id,task_id='test',source_scope=scope))
    assert result.error_code=='tool_scope_denied'


def test_docs_role_cannot_retrieve_code_evidence(indexed):
    _,_,snapshot,_,store,tools=indexed
    evidence=store.read_evidence(snapshot.id,'app.py',1,2)
    result=tools.invoke('retrieve_evidence',{'evidence_id':evidence.id},ToolContext(snapshot_id=snapshot.id,task_id='test',source_scope='docs'))
    assert result.error_code=='tool_scope_denied' and not result.evidence_ids


def test_model_cannot_override_scope_or_snapshot(indexed):
    _,_,snapshot,_,_,tools=indexed
    result=tools.invoke('read_file',{'path':'app.py','source_scope':'all'},ToolContext(snapshot_id=snapshot.id,task_id='test',source_scope='docs'))
    assert result.error_code=='invalid_arguments'


def test_missing_documents_are_explicit(indexed):
    _,_,snapshot,_,_,tools=indexed
    result=tools.invoke('search_text',{'query':'no_such_document_xyz'},ToolContext(snapshot_id=snapshot.id,task_id='test',source_scope='docs'))
    assert result.status=='ok' and result.data==[] and not result.evidence_ids
