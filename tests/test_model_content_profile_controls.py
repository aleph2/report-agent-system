"""Native platform content middleware controls; no generated response or network."""
from copy import deepcopy
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import ToolMessage
from deepagents.middleware.unsupported_content import UnsupportedContentMiddleware
import pytest

from report_agent.deep_models import configured_model
from test_agent_duty_image_routing import PNG_BASE64
from test_deep_models import configured
from test_deep_runtime import Driver


@pytest.mark.parametrize("profile", [{"image_inputs": True, "image_tool_message": True}, None], ids=["explicit-vision", "unknown-capability"])
async def test_builtin_does_not_globally_disable_vision_or_relabel_unknown(profile):
    model = Driver()("writer").model_copy(update={"profile": profile})
    message = ToolMessage(content=[{"type": "image", "base64": PNG_BASE64, "mime_type": "image/png"}],
                          tool_call_id="original-read", name="read_file", status="success",
                          additional_kwargs={"read_file_path": "/synthetic.png", "read_file_media_type": "image/png"})
    before = deepcopy(message.model_dump())
    observed = []
    async def handler(request):
        observed.append(request)
    await UnsupportedContentMiddleware().awrap_model_call(ModelRequest(model=model, messages=[message]), handler)
    assert len(observed) == 1 and observed[0].messages[0] is message
    assert message.model_dump() == before


async def test_glm_capability_binding_does_not_mark_other_model_text_only(configured, monkeypatch):
    for suffix, value in {"MODEL": "deepseek-v4.1-flash-1017", "BASE_URL": "https://offline.invalid/v1", "API_KEY": "synthetic-key"}.items():
        monkeypatch.setenv("REPORT_REVIEWER_" + suffix, value)
    model = configured_model(configured, "reviewer")
    try:
        # Unknown profile remains unknown; this is not proof of vision support.
        assert not model.profile or model.profile.get("image_inputs") is not False
    finally:
        await model.root_async_client.close()
        model.root_client.close()
