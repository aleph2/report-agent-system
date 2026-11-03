"""Explicit external template PDFs join the same pinned staging input snapshot."""
import hashlib
import json
from pathlib import Path
import socket
import sys

import pytest

from test_ingestion import pdf_bytes
from test_pilot_m1_preparation import stage_fixture


def template(path, text='Optional external template.'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf_bytes((text,)))
    return path


def test_repeated_external_templates_are_copied_and_hash_pinned_without_modifying_originals(tmp_path, monkeypatch):
    state, args = stage_fixture(tmp_path, monkeypatch, extras=1)
    args.templates = [template(tmp_path / 'references' / 'template-a.pdf'),
                      template(tmp_path / 'other' / 'template-b.PDF', 'Second template.')]
    before = {path: path.read_bytes() for path in [*args.templates, *args.inputs.rglob('*')] if path.is_file()}
    state['stage'](args)
    receipt = json.loads((args.run / 'stage-receipt.json').read_text())
    pins = json.loads((args.run / 'approved-input-hashes.json').read_text())
    profiles = {item['path']: item for item in json.loads((args.run / 'pdf-limits.json').read_text())}
    for path in args.templates:
        relative = '成果报告/' + path.name
        data = before[path]
        digest = hashlib.sha256(data).hexdigest()
        assert (args.run / 'inputs' / relative).read_bytes() == data
        assert receipt['input_hashes'][relative] == pins[relative] == digest
        assert profiles[relative]['sha256'] == digest
    assert all(path.read_bytes() == data for path, data in before.items())
    assert receipt['status'] == 'staged_no_model_calls'
    assert not args.ledger.exists() and not (args.run / 'case').exists()


@pytest.mark.parametrize('explicit_empty', [False, True])
def test_template_option_is_optional_and_preserves_an_existing_reference_folder(tmp_path, monkeypatch, explicit_empty):
    state, args = stage_fixture(tmp_path, monkeypatch, extras=1)
    existing = template(args.inputs / '成果报告' / 'existing.pdf')
    if explicit_empty:
        args.templates = []
    state['stage'](args)
    assert (args.run / 'inputs' / '成果报告' / existing.name).read_bytes() == existing.read_bytes()
    pins = json.loads((args.run / 'approved-input-hashes.json').read_text())
    assert pins['成果报告/existing.pdf'] == hashlib.sha256(existing.read_bytes()).hexdigest()
    assert not args.ledger.exists()


@pytest.mark.parametrize('fault', ['input-collision', 'external-collision', 'symlink', 'not-pdf'])
def test_external_template_staging_refuses_unsafe_or_ambiguous_inputs(tmp_path, monkeypatch, fault):
    state, args = stage_fixture(tmp_path, monkeypatch, extras=1)
    external = template(tmp_path / 'external' / 'shared.pdf')
    args.templates = [external]
    if fault == 'input-collision':
        template(args.inputs / '成果报告' / external.name, 'Existing customer template.')
    elif fault == 'external-collision':
        args.templates.append(template(tmp_path / 'another' / external.name, 'Different same-name template.'))
    elif fault == 'symlink':
        link = tmp_path / 'linked.pdf'
        link.symlink_to(external)
        args.templates = [link]
    else:
        nonpdf = tmp_path / 'notes.md'
        nonpdf.write_text('Not a template PDF.', encoding='utf-8')
        args.templates = [nonpdf]
    original = external.read_bytes()
    with pytest.raises(ValueError, match='(?i)(template|collision|escape|type)'):
        state['stage'](args)
    assert external.read_bytes() == original
    assert not (args.run / 'stage-receipt.json').exists()
    assert not args.ledger.exists()


def test_cli_accepts_repeatable_template_paths(tmp_path, monkeypatch):
    state, args = stage_fixture(tmp_path, monkeypatch, extras=1)
    first = tmp_path / 'one.pdf'
    second = tmp_path / 'two.pdf'
    captured = []
    monkeypatch.setitem(state, 'stage', captured.append)
    monkeypatch.setattr(socket.socket, 'connect', socket.socket.connect)
    monkeypatch.setattr(sys, 'argv', ['stage_report.py', '--revision', args.revision,
        '--inputs', str(args.inputs), '--run', str(args.run), '--ledger', str(args.ledger),
        '--authority', args.authority, '--template', str(first), '--template', str(second)])
    state['main']()
    assert len(captured) == 1
    assert captured[0].templates == [Path(first), Path(second)]
