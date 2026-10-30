import hashlib
import pytest
from report_agent.prompt_sources import load_prompt


@pytest.mark.parametrize('source,fragments',[
    ('working-summary-concise',('failed or rejected call committed','unobserved transition','actual saved field','not an unchecked item')),
    ('content-reviewer-v4',('coverage statement and reason','artifact actually observed','an unassigned artifact','adds no check'))])
def test_reviewed_failure_class_rules_are_in_actual_prompt_sources(source,fragments):
    text=load_prompt(source)
    for fragment in fragments:
        assert fragment in text
    assert hashlib.sha256(load_prompt('working-summary').encode()).hexdigest() == 'f07d90b4a03aa720187ca2232802cb3fdae5c3e24f42228ab4f4ba35b1b94e8c'
