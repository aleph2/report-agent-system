from concurrent.futures import ThreadPoolExecutor
import pytest
from report_agent.token_budget import TokenBudget
from report_agent.request_budget import RequestBudgetExceeded


def amend(budget, **changes):
    values = dict(previous_maximum=100, new_maximum=160,
        authorization_id='direct-user-addition', authorization_sha256='a'*64)
    return TokenBudget.increase_authorization(budget.path, **(values | changes))


def test_additive_grant_keeps_usage_unknown_bounds_and_old_live_cap(tmp_path):
    old = TokenBudget(tmp_path/'budget.db', 100, {'m':40})
    known, unknown = old.reserve('m'), old.reserve('m')
    old.settle(known, {'total_tokens':30, 'prompt_tokens_details':{'cached_tokens':20}})
    old.settle(unknown, None)
    with old.connect() as db:
        before = list(db.execute('SELECT * FROM attempts ORDER BY id'))
    assert amend(old)['applied']
    assert not amend(old)['applied']
    assert old.maximum == 100
    with pytest.raises(RequestBudgetExceeded):
        old.reserve('m')
    new = TokenBudget(old.path, 160, {'m':40})
    assert new.snapshot()['recorded_tokens'] == 30
    assert new.snapshot()['reserved_or_unknown_upper_bounds'] == 40
    assert new.snapshot()['remaining_for_new_reservations'] == 90
    with new.connect() as db:
        assert list(db.execute('SELECT * FROM attempts ORDER BY id')) == before
        assert db.execute('SELECT COUNT(*) FROM authorization_amendments').fetchone()[0] == 1
    new.reserve('m')
    with pytest.raises(ValueError, match='TOKEN_AUTHORIZATION_CONFLICT'):
        TokenBudget(old.path, 100, {'m':40})


@pytest.mark.parametrize('changes', [dict(new_maximum=100), dict(new_maximum=99),
    dict(new_maximum=True), dict(authorization_sha256='missing'), dict(authorization_id='')])
def test_invalid_addition_cannot_change_budget(tmp_path, changes):
    b = TokenBudget(tmp_path/'budget.db', 100, {'m':40})
    with pytest.raises(ValueError):
        amend(b, **changes)
    assert TokenBudget(b.path, 100, {'m':40}).snapshot()['maximum_tokens'] == 100


def test_competing_additions_have_one_cas_winner_and_conflicting_replay_fails(tmp_path):
    b = TokenBudget(tmp_path/'budget.db', 100, {'m':40})
    def apply(identity):
        try:
            return amend(b, authorization_id=identity)['applied']
        except ValueError as exc:
            assert str(exc) == 'TOKEN_AUTHORIZATION_COMPARE_AND_SWAP_FAILED'
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(apply, ['one','two'])) == 1
    with b.connect() as db:
        identity = db.execute('SELECT id FROM authorization_amendments').fetchone()[0]
    with pytest.raises(ValueError, match='AMENDMENT_CONFLICT'):
        amend(b, authorization_id=identity, authorization_sha256='b'*64)
    assert TokenBudget(b.path, 160, {'m':40}).snapshot()['maximum_tokens'] == 160
