"""Regression for the omitted-correction test material; no application repair."""
import json
from pathlib import Path

from langchain_core.messages import messages_to_dict
from test_bounded_review import Model
from test_task_supervision import ws, offline


async def test_correction_selection_delta_reaches_independent_and_optimizer_inputs(ws, tmp_path, monkeypatch, request):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    from probe_duty_completion import capture_optimizer
    packets, observations = [], []
    for include in (False, True):
        folder = tmp_path / str(include)
        folder.mkdir()
        service = Model(json.dumps({'findings': '70 conflicts with 75–100 in the supplied rule.', 'project_fact': None}))
        messages, _, observed = await capture_optimizer(ws, False, None, folder,
            text_model=service, include_correction=include)
        assert len(service.calls) == 1
        assert service.calls[0][-1][0] == 'user'
        packet = json.loads(service.calls[0][-1][1])
        packets.append(packet)
        fields = [v['selection']['field'] for v in packet['evidence']]
        assert fields == (['correction', 'before', 'evidence'] if include else ['before', 'evidence'])
        material = 'Customer feedback claims class B permits 70.'
        assert any(material in v['text'] for v in packet['evidence']) is include
        assert (material in json.dumps(messages_to_dict(messages), ensure_ascii=False)) is include
        observations.append({'include_correction': include, 'independent_input': packet,
                             'optimizer_messages': messages_to_dict(messages), 'delivered': observed})
    assert packets[0]['job_id'] == packets[1]['job_id']
    assert packets[0]['scope'] == packets[1]['scope']
    assert packets[0]['evidence'] == packets[1]['evidence'][1:]
    request.node.user_properties.append(('R6-material-delta', json.dumps(observations, ensure_ascii=False)))
