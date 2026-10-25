"""R29 uses the unchanged shared actual-main admission checks."""
import pytest

from test_duty_completion_registration_guard_R27 import assert_actual_main_registration_and_positive_caps
from test_duty_optimizer_adapter import no_external_network


@pytest.mark.parametrize('variant', ['valid', 'absent', 'missing-http', 'missing-increment', 'missing-phase'])
async def test_r29_actual_main_registration_and_positive_caps(tmp_path, monkeypatch, request, variant):
    await assert_actual_main_registration_and_positive_caps(tmp_path, monkeypatch, request, variant,
        wave='R29', case='layout-local-paired-page-comparison', http_cap=8, increment_cap=121, phase_cap=129,
        output_env='REPORT_R29_GUARD_OUT')
