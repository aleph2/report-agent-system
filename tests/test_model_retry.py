import pytest
from google.adk.models.llm_response import LlmResponse
from google.adk.models.llm_request import LlmRequest

from report_agent.models import ObservedModel
from report_agent.store import Store


class HttpFailure(Exception):
    def __init__(self, status):
        self.status_code = status


class Transport:
    def __init__(self, status=503, partial=False, recover=True):
        self.calls = 0
        self.status = status
        self.partial = partial
        self.recover = recover

    async def generate_content_async(self, request, stream=False):
        self.calls += 1
        if self.partial:
            yield LlmResponse()
        if self.calls == 1 or not self.recover:
            raise HttpFailure(self.status)
        yield LlmResponse()


async def consume(tmp_path, inner):
    model = ObservedModel(model="offline", inner=inner, store=Store(tmp_path), purpose="test", retry_delay_seconds=0)
    return [r async for r in model.generate_content_async(LlmRequest())]


async def test_transient_http_retry_shared_and_audited(tmp_path):
    inner = Transport()
    assert len(await consume(tmp_path, inner)) == 1
    assert inner.calls == 2
    assert len([e for e in Store(tmp_path).events() if e["kind"] == "model_retry"]) == 1


@pytest.mark.parametrize("status,partial,expected", [(401, False, 1), (403, False, 1), (400, False, 1),
                                                     (503, True, 1), (503, False, 3), (None, False, 1)])
async def test_do_not_blindly_retry_auth_partial_or_unknown_failures(tmp_path, status, partial, expected):
    inner = Transport(status, partial, recover=False)
    with pytest.raises(HttpFailure):
        await consume(tmp_path, inner)
    assert inner.calls == expected
