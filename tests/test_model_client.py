import httpx
import json
import pytest
from repolens.model_client import HTTPChatModel, ProviderError
from repolens.config import Settings


def connect(monkeypatch, tmp_path, response):
    original = httpx.AsyncClient
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        return response
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))
    return HTTPChatModel(Settings(workspace_root=tmp_path, data_dir=tmp_path / "data", model_name="test-provider", model_key="test-only-key"))


def test_http_adapter_parses_real_provider_shape(monkeypatch, tmp_path):
    model = connect(monkeypatch, tmp_path, httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"app.py"}'}}]}}], "usage": {"prompt_tokens": 42, "completion_tokens": 11}}))
    turn = model.complete([{"role": "user", "content": "Question"}], [], 100)
    assert turn.tool_calls[0].arguments == {"path": "app.py"}
    assert turn.usage.input_tokens == 42


def test_http_error_does_not_leak_provider_body(monkeypatch, tmp_path):
    model = connect(monkeypatch, tmp_path, httpx.Response(401, text="sensitive provider body"))
    with pytest.raises(ProviderError, match="provider_http_401") as exc:
        model.complete([], [], 100)
    assert not exc.value.retryable
    assert "sensitive" not in str(exc.value)


def test_http_adapter_reports_missing_usage(monkeypatch, tmp_path):
    model = connect(monkeypatch, tmp_path, httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]}))
    assert model.complete([], [], 100).usage is None


@pytest.mark.parametrize('tools',[[],[{'type':'function','function':{'name':'read_file','parameters':{'type':'object','properties':{}}}}]])
def test_adapter_omits_tool_fields_when_no_tools(monkeypatch,tmp_path,tools):
    original=httpx.AsyncClient
    def handler(request):
        body=json.loads(request.content)
        if tools:
            assert body['tools']==tools and body['tool_choice']=='auto'
        else:
            assert 'tools' not in body and 'tool_choice' not in body
        return httpx.Response(200,json={'choices':[{'message':{'content':'{}'}}]})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(handler)))
    model=HTTPChatModel(Settings(workspace_root=tmp_path,data_dir=tmp_path/'data',model_name='test'))
    assert model.complete([],tools,100).content=='{}'
