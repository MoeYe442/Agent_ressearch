"""HTTP adapter for providers implementing Chat Completions tool calling."""
import json
import asyncio
import ssl
import certifi
import time
import copy
from typing import Protocol
import httpx
from pydantic import ValidationError
from repolens.models import ModelTurn, ModelUsage, ToolCall


class ChatModel(Protocol):
    def complete(self, messages: list[dict], tools: list[dict], max_output_tokens: int) -> ModelTurn: ...


class ProviderError(Exception):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.code, self.retryable = code, retryable


class HTTPChatModel:
    def __init__(self, settings):
        self.settings = settings
        self.deadline = None
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    def with_deadline(self, deadline):
        model = copy.copy(self)
        model.deadline = deadline
        return model

    def complete(self, messages, tools, max_output_tokens):
        return asyncio.run(self._complete(messages, tools, max_output_tokens))

    async def _complete(self, messages, tools, max_output_tokens):
        timeout = self.settings.provider_timeout
        if self.deadline is not None:
            timeout = max(0.01, min(timeout, self.deadline - time.monotonic()))
        try:
            async with asyncio.timeout(timeout):
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, verify=self.ssl_context) as client:
                    async with client.stream("POST", self.settings.model_url.rstrip("/") + "/chat/completions", headers={"Authorization": "Bearer " + self.settings.model_key.get_secret_value()}, json={"model": self.settings.model_name, "messages": messages, "tools": tools, "tool_choice": "auto", "max_tokens": max_output_tokens}) as response:
                        if response.status_code != 200:
                            raise ProviderError(f"provider_http_{response.status_code}", response.status_code in {408, 429, 500, 502, 503, 504})
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 2 * 1024 * 1024:
                                raise ProviderError("provider_response_too_large")
                        data = json.loads(body)
            message = data["choices"][0]["message"]
            tool_calls = []
            for item in message.get("tool_calls") or []:
                raw_args = item["function"]["arguments"]
                try:
                    arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except (TypeError, ValueError):
                    arguments = raw_args  # Registry rejects malformed arguments as a structured error.
                tool_calls.append(ToolCall(id=item["id"], name=item["function"]["name"], arguments=arguments))
            usage = data.get("usage")
            measured = ModelUsage(input_tokens=usage["prompt_tokens"], output_tokens=usage["completion_tokens"]) if usage and "prompt_tokens" in usage and "completion_tokens" in usage else None
            return ModelTurn(tool_calls=tool_calls, content=message.get("content") or "", usage=measured)
        except TimeoutError:
            exhausted = self.deadline is not None and time.monotonic() >= self.deadline
            raise ProviderError("time_budget_exhausted" if exhausted else "provider_timeout", retryable=not exhausted) from None
        except (httpx.TimeoutException, httpx.NetworkError):
            raise ProviderError("provider_network_error", retryable=True) from None
        except (KeyError, TypeError, ValueError, ValidationError, httpx.HTTPError):
            raise ProviderError("provider_protocol_error") from None


def configured_model(settings):
    return HTTPChatModel(settings) if settings.model_name and settings.model_key.get_secret_value() else None
