"""R30 reuses the unchanged actual-main registration and positive-cap checks."""
import pytest

from test_duty_completion_registration_guard_R27 import assert_actual_main_registration_and_positive_caps
from test_duty_optimizer_adapter import no_external_network


@pytest.mark.parametrize('variant', ['valid', 'absent', 'missing-http', 'missing-increment', 'missing-phase'])
async def test_r30_actual_main_registration_and_positive_caps(tmp_path, monkeypatch, request, variant):
    await assert_actual_main_registration_and_positive_caps(tmp_path, monkeypatch, request, variant,
        wave='R30', case='writer-independent-analysis', http_cap=6, increment_cap=127, phase_cap=135,
        output_env='REPORT_R30_GUARD_OUT')
