import json

import httpx
import openai
import pytest
from langchain_openai.chat_models.base import OpenAIConnectionError, OpenAITimeoutError
from openai import PermissionDeniedError

from report_agent.deep_models import LocalAudit, configured_model, error_data
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.store import Store


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_MODEL", "glm-5.3")
    monkeypatch.setenv("REPORT_BASE_URL", "https://model.invalid/v1")
    monkeypatch.setenv("REPORT_API_KEY", "test-private-key")
    return Store(tmp_path)


def test_unauthorized_model_cannot_fallback(configured, monkeypatch):
    monkeypatch.setenv("REPORT_MODEL", "qwen3.8-max")
    with pytest.raises(RuntimeError, match="AUTHORIZED_GLM53"):
        configured_model(configured, "reviewer")


@pytest.mark.parametrize("failure,expected", [(503, 2), (403, 1)])
async def test_sdk_shared_retry_and_actual_request_contract(configured, failure, expected):
    requests = []

    async def handle(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(failure, json={"error": {"message": "synthetic failure", "type": "test"}})
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 1,
            "model": "glm-5.3", "choices": [{"index": 0, "finish_reason": "stop",
                                               "message": {"role": "assistant", "content": "OK"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        model = configured_model(configured, "coordinator")
        from openai import AsyncOpenAI
        sdk = AsyncOpenAI(api_key="test-private-key", base_url="https://model.invalid/v1",
                          http_client=client, max_retries=2)
        model.async_client = sdk.chat.completions
        if failure == 403:
            with pytest.raises(PermissionDeniedError) as captured:
                await model.ainvoke("hello")
            assert error_data(captured.value)["http_status"] == 403
        else:
            assert (await model.ainvoke("hello")).content == "OK"
    assert len(requests) == expected
    assert requests[0]["model"] == "glm-5.3"
    assert requests[0]["reasoning_effort"] == "high"
    assert requests[0]["thinking"] == {"type": "enabled", "clear_thinking": False}
    assert requests[0]["parallel_tool_calls"] is False
    assert requests[0]["max_completion_tokens"] == 65536
    assert "test-private-key" not in json.dumps(configured.events())
    responses = [e for e in configured.events() if e["kind"] == "deep_model_response"]
    if failure == 503:
        assert responses[0]["data"]["usage"]["total_tokens"] == 3


def private_request():
    return httpx.Request("POST", "https://private-host.invalid/v1?key=private-url-key",
                         headers={"Authorization": "Bearer private-header-key"},
                         content=b"private-engineering-body")


def assert_safe_error(data):
    serialized = json.dumps(data)
    for secret in ("private-host", "private-url-key", "private-header-key", "private-engineering-body",
                   "private-provider-message", "PRIVATE_PROVIDER_BODY", "Authorization", "https://"):
        assert secret not in serialized


@pytest.mark.parametrize("error_type", [openai.APIConnectionError, OpenAIConnectionError])
def test_sdk_connection_hierarchy_without_message_serialization(error_type, monkeypatch):
    error = error_type(message="private-provider-message", request=private_request())
    error.body = {"error": "PRIVATE_PROVIDER_BODY"}
    def forbidden_str(_):
        raise AssertionError("Provider __str__ must not be called")
    monkeypatch.setattr(error_type, "__str__", forbidden_str)
    data = error_data(error)
    assert data == {"type": error_type.__name__, "http_status": None, "message": "MODEL_CONNECTION_FAILED"}
    assert_safe_error(data)


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadError, httpx.WriteError,
                                        httpx.RemoteProtocolError, httpx.ProxyError])
def test_httpx_transport_classification(error_type):
    data = error_data(error_type("private-provider-message", request=private_request()))
    assert data["message"] == "MODEL_CONNECTION_FAILED"
    assert data["http_status"] is None
    assert_safe_error(data)


@pytest.mark.parametrize("error_type", [openai.APITimeoutError, OpenAITimeoutError])
def test_sdk_timeouts_are_not_classified_as_connection_failures(error_type):
    data = error_data(error_type(private_request()))
    assert data["message"] == "MODEL_REQUEST_TIMEOUT"
    assert_safe_error(data)


@pytest.mark.parametrize("error_type", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout,
                                        httpx.PoolTimeout, TimeoutError])
def test_known_timeout_types(error_type):
    data = error_data(error_type("private-provider-message"))
    assert data["message"] == "MODEL_REQUEST_TIMEOUT"
    assert_safe_error(data)


@pytest.mark.parametrize("error_type,status,message", [
    (openai.AuthenticationError, 401, "MODEL_AUTHENTICATION_FAILED"),
    (openai.PermissionDeniedError, 403, "MODEL_PERMISSION_DENIED"),
    (openai.RateLimitError, 429, "MODEL_RATE_LIMITED"),
    (openai.InternalServerError, 503, "MODEL_SERVICE_UNAVAILABLE"),
])
def test_sdk_status_classification_never_exposes_response_body(error_type, status, message):
    response = httpx.Response(status, request=private_request(), text="private-engineering-body")
    error = error_type("PRIVATE_PROVIDER_BODY", response=response,
                       body={"message": "private-provider-message", "api_key": "private-header-key"})
    data = error_data(error)
    assert data["message"] == message and data["http_status"] == status
    assert_safe_error(data)


@pytest.mark.parametrize("status,message", [(401, "MODEL_AUTHENTICATION_FAILED"),
    (403, "MODEL_PERMISSION_DENIED"), (429, "MODEL_RATE_LIMITED"), (408, "MODEL_REQUEST_TIMEOUT"),
    (504, "MODEL_REQUEST_TIMEOUT"), (503, "MODEL_SERVICE_UNAVAILABLE"), (400, "MODEL_REQUEST_REJECTED")])
def test_httpx_trusted_status_classification(status, message):
    request = private_request()
    response = httpx.Response(status, request=request, text="private-engineering-body")
    error = httpx.HTTPStatusError("private-provider-message", request=request, response=response)
    data = error_data(error)
    assert data["message"] == message and data["http_status"] == status
    assert_safe_error(data)


def test_cause_types_explain_wrapped_connection_and_timeout_without_text():
    network = httpx.ConnectError("private-engineering-body", request=private_request())
    sdk = openai.APIConnectionError(message="private-provider-message", request=private_request())
    sdk.__cause__ = network
    outer = OpenAIConnectionError(message="PRIVATE_PROVIDER_BODY", request=private_request())
    outer.__cause__ = sdk
    data = error_data(outer)
    assert data["cause_types"] == ["APIConnectionError", "ConnectError"]
    assert data["message"] == "MODEL_CONNECTION_FAILED"
    assert_safe_error(data)
    sdk.__cause__ = httpx.ReadTimeout("private-provider-message", request=private_request())
    timeout = error_data(outer)
    assert timeout["message"] == "MODEL_REQUEST_TIMEOUT"
    assert timeout["cause_types"] == ["APIConnectionError", "ReadTimeout"]
    assert_safe_error(timeout)


def test_wrapped_status_is_classified_without_serializing_wrapper():
    request = private_request()
    outer = RuntimeError("private-provider-message")
    outer.__cause__ = openai.RateLimitError("PRIVATE_PROVIDER_BODY",
        response=httpx.Response(429, request=request), body={"error": "private-engineering-body"})
    data = error_data(outer)
    assert data == {"type": "RuntimeError", "http_status": 429, "message": "MODEL_RATE_LIMITED",
                    "cause_types": ["RateLimitError"]}
    assert_safe_error(data)


def test_cause_walk_is_bounded_and_cycle_safe():
    root = error = Exception("private-provider-message")
    for _ in range(10):
        error.__cause__ = Exception("private-engineering-body")
        error = error.__cause__
    error.__cause__ = TimeoutError("private-provider-message")
    data = error_data(root)
    assert data["cause_types"] == ["Exception"] * 4
    assert data["cause_chain_truncated"] is True
    assert data["message"] == "EXECUTION_FAILED"
    root.__cause__ = root
    assert error_data(root) == {"type": "Exception", "http_status": None,
                                "message": "EXECUTION_FAILED", "cause_chain_truncated": True}
    assert_safe_error(data)


def test_untrusted_names_status_attributes_and_exception_text_do_not_classify():
    impersonator = type("OpenAIConnectionError", (Exception,), {})
    error = impersonator("APIConnectionError private-provider-message")
    error.status_code = 401
    assert error_data(error)["message"] == "EXECUTION_FAILED"
    assert error_data(error)["http_status"] is None
    error.status_code = {"api_key": "private-header-key"}
    assert_safe_error(error_data(error))
    strange = type("https://private-host.invalid/private-header-key", (Exception,), {})
    assert error_data(strange())["type"] == "Exception"
    long_name = type("X" * 200, (Exception,), {})
    assert error_data(long_name())["type"] == "Exception"


@pytest.mark.parametrize("error", [ActionRejected("SOURCE_NOT_IN_PROJECT"),
    ActionForbidden("REPLACEMENT_OWNER_MISMATCH"), RuntimeError("REPEATED_ACTION_WITHOUT_PROGRESS"),
    ValueError("INVALID_RESULT_PAGE"), PermissionError("RESULT_OWNER_MISMATCH"),
    RuntimeError("EXECUTION_FAILED")])
def test_existing_business_codes_are_preserved(error):
    error.__cause__ = httpx.ConnectError("private-provider-message")
    assert error_data(error)["message"] == error.args[0]
    assert_safe_error(error_data(error))


def test_audit_stores_sanitized_transport_presentation(configured):
    error = OpenAIConnectionError(message="private-provider-message", request=private_request())
    error.__cause__ = httpx.ConnectError("private-engineering-body", request=private_request())
    LocalAudit(configured, "writer").on_llm_error(error, run_id="synthetic-error")
    event = configured.events()[-1]
    assert event["kind"] == "deep_model_error"
    assert event["data"]["message"] == "MODEL_CONNECTION_FAILED"
    assert event["data"]["cause_types"] == ["ConnectError"]
    assert_safe_error(event)
