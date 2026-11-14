from pathlib import Path
import pytest
from repolens.recovery import signature
from repolens.tasks import TaskService
from tests.scripted_model import ScriptedModel


@pytest.mark.parametrize('field,value',[('graph_recursion_limit',1),('provider_timeout',10),('milvus_collection','changed_collection')])
def test_execution_configuration_change_invalidates_signature(indexed,field,value):
    settings,db=indexed[:2]
    task=TaskService(settings,db,ScriptedModel()).submit(indexed[2].id,'Question')
    original=signature(task,settings,db)
    assert signature(task,settings.model_copy(update={field:value}),db)!=original


@pytest.mark.parametrize('module',['review.py','model_client.py','retrieval_http.py','indexing.py','tasks.py','evidence.py'])
def test_execution_module_change_invalidates_signature(indexed,monkeypatch,module):
    settings,db=indexed[:2]
    task=TaskService(settings,db,ScriptedModel()).submit(indexed[2].id,'Question')
    original=signature(task,settings,db);read=Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda path:read(path)+(b'\n# changed execution semantics\n' if path.name==module else b''))
    assert signature(task,settings,db)!=original
