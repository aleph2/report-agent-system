"""Original P22 node IDs and oracles; scenario shared with selection sensitivity."""
import pytest

from duty_probe_completion_chain import run_completion_chain
from test_task_supervision import ws, offline


@pytest.mark.parametrize('b_available', [True, False])
async def test_p22_native_small_chain_keeps_first_draft_and_unresolved_evidence(ws, request, b_available):
    await run_completion_chain(ws, request, b_available)
