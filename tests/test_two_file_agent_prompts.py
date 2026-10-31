"""Two-file authored prompts, exercised through the installed native harness."""
import pytest
import httpx
import hashlib
import shutil
from langchain_core.messages import AIMessage

from report_agent import prompt_sources
from report_agent.hierarchical_tools import role_prompt
from test_hierarchical_content import ws, seed
from test_reviewer_native_profile import native, commission
from test_deep_runtime import Driver, invoke


ROLES = ('coordinator', 'writer', 'reviewer', 'layout')


@pytest.fixture
def authored_rules(tmp_path, monkeypatch):
    rules = tmp_path / 'authored-rules'
    shutil.copytree(prompt_sources.RULES, rules)
    (rules / 'agent-common.md').write_text('Fixture common principles.', encoding='utf-8')
    for role in ROLES:
        (rules / f'agent-{role}.md').write_text(
            f'Fixture {role} responsibility.\n\nFixture {role} full definition.', encoding='utf-8')
    monkeypatch.setattr(prompt_sources, 'RULES', rules)
    return rules


@pytest.mark.parametrize('expected,actual', [('', 'Hidden role'), ('Allowed role', 'Allowed role\nHidden role')])
def test_renderer_cannot_fill_or_extend_authored_base(expected, actual):
    from langchain_core.messages import SystemMessage
    from report_agent.prompt_provenance import classify_agent_system
    assert classify_agent_system(SystemMessage(content=actual), expected)[0] == 'static_mismatch'


def test_empty_base_preserves_native_tools_and_declared_runtime_data():
    from langchain_core.messages import SystemMessage
    from langchain.agents.middleware.todo import WRITE_TODOS_SYSTEM_PROMPT
    from report_agent.prompt_provenance import classify_agent_system
    task = {'source': 'task/current', 'text': '{"task_id":"fixture"}'}
    for system in (None, SystemMessage(content=''), SystemMessage(content=WRITE_TODOS_SYSTEM_PROMPT),
                   SystemMessage(content=task['text'], additional_kwargs={'report_system_contributions': [task]})):
        assert classify_agent_system(system, '')[0] == 'exact'


@pytest.mark.parametrize('role', ROLES)
@pytest.mark.parametrize('common,own,expected', [
    ('', '', ''), ('Common only', '', 'Common only'),
    ('', 'Role only', 'Role only'), ('Common', 'Role', 'Common\n\nRole'),
    (' \n', '\t\n', ''), ('\n', 'Role', 'Role'), ('Common', '\n', 'Common'),
])
def test_only_two_files_supply_authored_prompt(tmp_path, monkeypatch, role, common, own, expected):
    monkeypatch.setattr(prompt_sources, 'RULES', tmp_path)
    (tmp_path / 'agent-common.md').write_text(common, encoding='utf-8')
    (tmp_path / ('agent-' + role.replace('_', '-') + '.md')).write_text(own, encoding='utf-8')
    assert role_prompt(role) == expected


def test_missing_role_is_not_replaced_with_a_default(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_sources, 'RULES', tmp_path)
    (tmp_path / 'agent-common.md').write_text('', encoding='utf-8')
    with pytest.raises(FileNotFoundError):
        role_prompt('writer')


@pytest.mark.parametrize('profile', ['legacy-v1', 'concise-v1'])
def test_old_profile_cannot_select_an_alternative_role(profile):
    assert prompt_sources.role_sources('writer', 'reader-expression-v2',
        'review-interfaces-v4', profile) == ['agent-common', 'agent-writer']


@pytest.mark.parametrize('role', ['coordinator', 'writer', 'reviewer', 'layout'])
@pytest.mark.parametrize('empty', [False, True, None])
async def test_actual_native_model_receives_only_two_authored_files(ws, tmp_path, monkeypatch, role, empty):
    from report_agent import deep_runtime
    native(ws)
    _, _, refs, snapshot, _ = seed(ws)
    # None exercises the actual checkout; other cases use real files and the real loader.
    if empty is not None:
        rules = tmp_path / 'rules'
        shutil.copytree(prompt_sources.RULES, rules)
        (rules / 'agent-common.md').write_text('' if empty else 'COMMON_CANARY', encoding='utf-8')
        for name in ROLES:
            (rules / ('agent-' + name + '.md')).write_text(
                '' if empty else 'OWN_CANARY_agent-' + name, encoding='utf-8')
        monkeypatch.setattr(prompt_sources, 'RULES', rules)
    expected = '\n\n'.join(text for text in (
        (prompt_sources.RULES / 'agent-common.md').read_text(encoding='utf-8'),
        (prompt_sources.RULES / ('agent-' + role + '.md')).read_text(encoding='utf-8')) if text.strip())
    assert role_prompt(role) == expected
    if empty is True:
        assert expected == ''
    def no_network(*args, **kwargs):
        raise AssertionError('Offline prompt verification must never dispatch HTTP')
    monkeypatch.setattr(httpx.Client, 'send', no_network)
    monkeypatch.setattr(httpx.AsyncClient, 'send', no_network)
    if role == 'coordinator':
        steps = [AIMessage(content='Synthetic completion')]
    else:
        args = commission(snapshot, refs) if role == 'reviewer' else {
            'subagent_type': role, 'description': 'Inspect synthetic scope only.',
            **({'layout_snapshot_ref': snapshot} if role == 'layout' else {})}
        steps = [invoke('task', **args), AIMessage(content='Synthetic completion')]
    driver = Driver(**{'coordinator': steps,
        **({role: [AIMessage(content='Synthetic child result')]} if role != 'coordinator' else {})})
    agent = deep_runtime.build_agent(ws, driver, None)
    await agent.ainvoke({'messages': [('user', 'Offline synthetic assignment')]})
    calls = [messages for actual_role, _, messages in driver.calls if actual_role == role]
    assert len(calls) == 1
    system = next((m for m in calls[0] if m.type == 'system'), None)
    blocks = system.content_blocks if system else []
    if expected:
        assert blocks[0] == {'type': 'text', 'text': expected}
    else:
        assert not any('CANARY' in b.get('text', '') for b in blocks)
    captures = [ws.store.get(e['data']['capture_key']) for e in ws.store.events()
        if e['kind'] == 'prompt_model_input' and e['data']['purpose'] == role]
    authored = captures[0]['sources'][0]
    assert authored['files'] == ['agent-common', 'agent-' + role]
    assert authored['sha256'] == hashlib.sha256(expected.encode()).hexdigest()
    assert captures[0]['status'] == 'exact'
    # Every additional block must be a native tool description or declared task data.
    assert {part['source'] for part in captures[0]['sources']} <= {
        'configured_role_files', 'langchain/TodoListMiddleware', 'native_registered_tools'}
    # Framework tool guidance is separate; it must not restore application role prose.
    text = system.text if system else ''
    assert 'You may write the report yourself.' not in text
    assert 'actual local check indexes when saving' not in text
    assert 'agent-context-' not in text
