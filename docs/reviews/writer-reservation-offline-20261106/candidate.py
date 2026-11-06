"""Offline forecast experiment. Never a RequestBound or live reservation policy."""
from hashlib import sha256
import json

class CandidateExceeded(ValueError):
    pass

def forecast(payload, counter):
    if (payload.get('model')!='glm-5.3' or payload.get('stream',False) is not False
            or type(payload.get('n',1)) is not int or payload.get('n',1)!=1):
        raise ValueError('SUPPORTED_SINGLE_TEXT_REQUEST_REQUIRED')
    outputs=[payload[k] for k in ('max_tokens','max_completion_tokens') if k in payload]
    if not outputs or any(type(n) is not int or n!=65536 for n in outputs):
        raise ValueError('CONFIGURED_OUTPUT_65536_REQUIRED')
    measured=counter.measure(payload); local=measured['tokens']
    if type(local) is not int or not 0<=local<=1048576:
        raise ValueError('LOCAL_INPUT_OUTSIDE_MODEL_CEILING')
    # shortcut: empirical framing allowance; replace only with a serving contract.
    estimated_input=min(1048576,(6*local+4)//5+4096)
    return {'local_input_tokens':local,'input_estimate':estimated_input,
            'output_allowance':65536,'total_estimate':estimated_input+65536,
            'hard_bound_verified':False,'counter':measured,
            'payload_json_sha256':sha256(json.dumps(payload,ensure_ascii=False,
                separators=(',',':'),allow_nan=False).encode()).hexdigest()}

def check_response(candidate, usage):
    """Call after settling real usage; raises before allowing further work.

    Diagnostic only: it cannot undo the response's cost or edit the ledger.
    """
    keys=('prompt_tokens','completion_tokens','total_tokens')
    if (not isinstance(usage,dict) or any(type(usage.get(k)) is not int
            or usage[k]<0 for k in keys)
            or usage['prompt_tokens']+usage['completion_tokens']!=usage['total_tokens']):
        raise CandidateExceeded('USAGE_UNVERIFIED')
    codes=[]
    if usage['prompt_tokens']>candidate['input_estimate']:codes.append('INPUT_ESTIMATE_EXCEEDED')
    if usage['completion_tokens']>candidate['output_allowance']:codes.append('OUTPUT_ALLOWANCE_EXCEEDED')
    if usage['total_tokens']>candidate['total_estimate']:codes.append('TOTAL_ESTIMATE_EXCEEDED')
    if codes:raise CandidateExceeded('|'.join(codes))
    return {k:usage[k] for k in keys}
