"""Inspectable layout capabilities and explicit development handoffs."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .content_layout import LayoutOptions
from .errors import ActionForbidden, ActionRejected


def capabilities():
    folder = Path(__file__).parent
    engine = hashlib.sha256(b''.join((folder/name).read_bytes() for name in
        ('content_layout.py','content_export.py','office_finalize.py','office_render.py','layout_capabilities.py'))).hexdigest()
    program = Path('C:/Program Files/LibreOffice/program') if os.name == 'nt' else Path('/usr/lib/libreoffice/program')
    installed = (program/('soffice.bin' if os.name == 'nt' else 'soffice')).exists()
    if os.name != 'nt' and installed:
        try:
            installed = subprocess.run(['/usr/bin/python3','-c','import uno'], capture_output=True,
                timeout=10, env={k:v for k,v in os.environ.items() if k not in {'PYTHONHOME','PYTHONPATH'}}).returncode == 0
        except (OSError, subprocess.SubprocessError):
            installed = False
    return {'version':'layout-v10', 'engine_digest':engine,
        'controls':LayoutOptions.model_json_schema(),
        'directory_refresh':{'available':installed,'runtime':'native-windows' if os.name=='nt' else 'native-linux',
            'requires':'LibreOffice Writer + UNO Python; Ubuntu packages libreoffice-writer python3-uno fonts-noto-cjk'},
        'changes':['Independent table position, cell-paragraph alignment and cell first-line indent with global defaults and per-table overrides; None preserves previous behavior','TOC title/level styles, per-style/per-paragraph line multipliers and point/line paragraph spacing; explicit fonts override conflicting same-element theme attributes',
            'table paragraph line-spacing multiplier, outer border single/double and eighth-point width, left/hanging paragraph indentation; per-node overrides preserve content',
            'source-bound composite header lines; exact point line spacing; character-em indent resolved to points; isolated cover vertical alignment',
            'multipart headers omit unused tab positions; explicit empty first-page header/footer parts survive Office refresh',
            'per-node qualifier_placement: adjacent or numbered end_notes; all semantic text retained with visible marker and version-bound mapping',
            'source-bound left/center/right header parts, style/paragraph first-line indentation, optional blank first-page header/footer',
            'per-side page margins; style and exact-line typography including report/chapter titles',
            'header repeats a unique source line from an actually rendered body node with versioned provenance',
            'font settings express requested typography; installed font substitution and visual alignment require review',
            'exact unique source-line paragraph headings and spacing without content edits',
            'optional refreshed TOC with actual page numbers and preserved-content validation',
            'versioned capability requests returned through read_feedback'],
        'boundaries':'No content rewrite or arbitrary code execution. Missing controls can be requested from development; a request does not implement or approve them.'}


def refresh_directory(store, data):
    if not capabilities()['directory_refresh']['available']:
        raise ActionRejected('DIRECTORY_REFRESH_DEPENDENCY_UNAVAILABLE')
    from . import office_finalize
    with tempfile.TemporaryDirectory(prefix='directory-', dir=store.root) as temporary:
        folder = Path(temporary).resolve()
        source, target = folder/'input.docx', folder/'output.docx'
        source.write_bytes(data)
        result = subprocess.run([sys.executable, str(Path(office_finalize.__file__).resolve()),
            str(source), str(target)], capture_output=True, timeout=210,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            diagnostic = result.stderr.decode('utf-8',errors='replace')[-6000:]
            # Export executes inside ContentStore.operation's write transaction.
            # A second connection here deadlocks and hides this recoverable failure.
            diagnostics = store.root / 'diagnostics'
            try:
                diagnostics.mkdir(exist_ok=True)
                key = hashlib.sha256(data + diagnostic.encode('utf-8')).hexdigest()
                (diagnostics / (key + '.json')).write_text(json.dumps({
                    'kind': 'directory_refresh_failed', 'diagnostic': diagnostic,
                    'input_sha256': hashlib.sha256(data).hexdigest()}, ensure_ascii=False), encoding='utf-8')
            except OSError:
                # Failure to save an auxiliary log must not mask the tool outcome.
                pass
            raise ActionRejected('DIRECTORY_REFRESH_FAILED')
        receipt = json.loads(target.with_suffix('.finalize.json').read_text(encoding='utf-8'))
        return target.read_bytes(), receipt


def request_extension(contents, actor, operation_id, snapshot_ref, problem, attempted, requested_operation, evidence):
    snapshot = contents.read(snapshot_ref)
    if snapshot_ref['type'] != 'DocumentSnapshot':
        raise ActionRejected('SNAPSHOT_REQUIRED')
    if actor.role == 'layout':
        task = contents.read({'type':'DelegatedTask','id':actor.task_id,'version':1})
        if actor.id != 'content:layout:'+actor.task_id or task['payload'].get('layout_snapshot_ref') != snapshot_ref:
            raise ActionForbidden('FORBIDDEN: layout capability request scope')
    elif actor.role != 'coordinator' or snapshot['owner_id'] != actor.id:
        raise ActionForbidden('FORBIDDEN: capability request owner')
    if not attempted or not evidence or not requested_operation.strip():
        raise ActionRejected('CAPABILITY_REQUEST_REQUIRES_ATTEMPTS_EVIDENCE_AND_OPERATION')
    return contents.handoff(actor, operation_id, snapshot_ref, problem, evidence,
        'Development capability assessment requested; no automatic implementation or report approval.',
        details={'kind':'layout_capability_request','requested_operation':requested_operation,
            'attempted':attempted,'capability_version':capabilities()['engine_digest'],
            'resume_task_id':actor.task_id, 'destination':'development'})
