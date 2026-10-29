from report_agent.decision_state import compact_context


def test_identical_assignment_goal_keeps_exact_invocation_and_navigation():
    goal='same assignment '*200
    context={'goal':'project goal','assignment':{'goal':goal},
             'current_invocation':{'description':goal},'operator_feedback':[],'issues':[]}
    result=compact_context(context)
    assert result['current_invocation']['description']==goal
    item=result['assignment']['goal']
    assert item['read_state_path']==['assignment','goal']
    assert item['same_as']==['current_invocation','description']
    assert 'preview' not in item


def test_changed_invocation_does_not_hide_original_assignment():
    original='original assignment '*100
    context={'goal':'project goal','assignment':{'goal':original},
             'current_invocation':{'description':original+' changed'},'operator_feedback':[],'issues':[]}
    item=compact_context(context)['assignment']['goal']
    assert item['preview'] and item['read_state_path']==['assignment','goal']
    assert 'same_as' not in item


def test_medium_identical_assignment_uses_reference_when_it_saves_space():
    goal="synthetic assignment "*30
    assert len(goal)<800
    context={"goal":"project","assignment":{"goal":goal},"current_invocation":{"description":goal},"operator_feedback":[],"issues":[]}
    result=compact_context(context)
    assert result["current_invocation"]["description"]==goal
    assert result["assignment"]["goal"]["same_as"]==["current_invocation","description"]

def test_short_identical_assignment_is_not_expanded_by_reference():
    goal="short"
    context={"goal":"project","assignment":{"goal":goal},"current_invocation":{"description":goal},"operator_feedback":[],"issues":[]}
    result=compact_context(context)
    assert result["assignment"]["goal"] == goal
