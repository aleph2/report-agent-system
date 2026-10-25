from pathlib import Path
from types import SimpleNamespace

from report_agent.office_render import convert_pdf


def test_invalid_pdf_falls_back_without_modifying_source(tmp_path, monkeypatch):
    import pypdfium2 as pdfium
    import report_agent.office_render as module
    native = tmp_path/'native'
    native.write_bytes(b'engine')
    original_exists = Path.exists
    monkeypatch.setattr(Path, 'exists', lambda p: True if str(p) == 'C:/Program Files/LibreOffice/program/soffice.com' else original_exists(p))
    monkeypatch.setattr(module.shutil, 'which', lambda name: str(native) if name == 'libreoffice' else None)
    read_bytes = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda p: b'windows-engine' if str(p) == 'C:/Program Files/LibreOffice/program/soffice.com' else read_bytes(p))
    attempts = []
    def run(command, **kwargs):
        source = Path(command[-1])
        assert source.read_bytes() == b'original workbook'
        attempts.append(command[0])
        target = source.with_suffix('.pdf')
        if len(attempts) == 1:
            target.write_bytes(b'%PDF- damaged')
        else:
            document = pdfium.PdfDocument.new()
            page = document.new_page(100, 100)
            page.close()
            document.save(target)
            document.close()
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, 'run', run)
    result, identity = convert_pdf(SimpleNamespace(root=tmp_path), b'original workbook', '.xlsx')
    assert result.startswith(b'%PDF-')
    assert len(attempts) == 2
    assert identity['prior_attempts'][0]['code'] == 'INVALID_PDF'


def test_missing_renderer_reports_blocked_evidence(tmp_path, monkeypatch):
    import report_agent.office_render as module
    monkeypatch.setattr(module.shutil, 'which', lambda name: None)
    monkeypatch.setattr(Path, 'exists', lambda p: False)
    result, diagnostic = convert_pdf(SimpleNamespace(root=tmp_path), b'copy', '.docx')
    assert result is None
    assert diagnostic == {'attempts': [], 'code': 'RENDER_UNAVAILABLE'}
