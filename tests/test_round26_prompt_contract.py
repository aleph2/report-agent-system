"""Static contract coverage only; real-model behavior assessed in next round."""
import re
import pytest
from report_agent.prompt_sources import load_prompt

@pytest.mark.parametrize('source,required',[
 ('content-reviewer-v4',['before substantive judgments','public working response','no separate planner']),
 ('working-summary-concise',['available schema','leave the general rule unresolved','actual version']),
 ('content-layout-v4',['layout.refresh_toc','export_config.layout','no automatically inherited']),
 ('content-writer-v4',['as-of time/stage','Do not predict approval','immutable version']),
 ('content-qualifiers-description',['Word prints nonstructural qualifiers','truthful section/page','distinct condition']),
 ('native-submit-review-v4-concise',['top-level tool argument','local required_checks index','missing_body_refs']),
 ('export-content-snapshot-v4',['layout.refresh_toc','top-level refresh_toc','export_config.layout'])])
def test_effective_static_contract_contains_scoped_corrections(source,required):
    text=re.sub(r'\s+',' ',load_prompt(source))
    for phrase in required:assert phrase in text,(source,phrase)
