"""R28 CLI admission uses the unchanged native guard and shared test assertions."""
import pytest

from test_duty_completion_registration_guard_R27 import assert_actual_main_registration_and_positive_caps
from test_duty_optimizer_adapter import no_external_network


@pytest.mark.parametrize('variant', ['valid', 'absent', 'missing-http', 'missing-increment', 'missing-phase'])
async def test_r28_actual_main_registration_and_positive_caps(tmp_path, monkeypatch, request, variant):
    await assert_actual_main_registration_and_positive_caps(tmp_path, monkeypatch, request, variant,
        wave='R28', case='reviewer-current-source-investigation', http_cap=8, increment_cap=113, phase_cap=121,
        output_env='REPORT_R28_GUARD_OUT')
