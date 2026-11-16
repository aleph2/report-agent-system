"""Render an immutable working copy with available local Office engines."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import quote


def convert_pdf(store, data, suffix):
    candidates = []
    native = shutil.which('libreoffice') or shutil.which('soffice')
    if native:
        candidates.append((native, False))
    windows = Path('C:/Program Files/LibreOffice/program/soffice.com')
    bridge = Path('/mnt/c/Program Files/LibreOffice/program/soffice.com')
    if windows.exists():
        candidates.append((str(windows), False))
    elif bridge.exists() and shutil.which('wslpath'):
        candidates.append((str(bridge), True))
    failures = []
    for executable, bridged in dict.fromkeys(candidates):
        with tempfile.TemporaryDirectory(prefix='report-render-', dir=store.root if bridged else None) as tmp:
            folder = Path(tmp).resolve()
            source = folder / ('input' + suffix)
            source.write_bytes(data)

            def external(path):
                return subprocess.run(['wslpath', '-w', str(path)], check=True,
                    capture_output=True, text=True).stdout.strip() if bridged else str(path)

            try:
                profile = ('file:///' + quote(external(folder / 'profile').replace('\\', '/'), safe=':/')
                    if bridged else (folder / 'profile').as_uri())
                result = subprocess.run([executable, '-env:UserInstallation=' + profile,
                    '--headless', '--convert-to', 'pdf', '--outdir', external(folder), external(source)],
                    capture_output=True, timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                target = folder / 'input.pdf'
                if result.returncode or not target.is_file():
                    failures.append({'engine': Path(executable).name, 'bridge': bridged,
                        'returncode': result.returncode, 'code': 'PDF_NOT_PRODUCED'})
                    continue
                pdf = target.read_bytes()
                if not pdf.startswith(b'%PDF-'):
                    failures.append({'engine': Path(executable).name, 'code': 'INVALID_PDF'})
                    continue
                import pypdfium2 as pdfium
                try:
                    with pdfium.PdfDocument(pdf) as document:
                        if len(document) == 0:
                            raise ValueError('Empty PDF')
                except (pdfium.PdfiumError, ValueError):
                    failures.append({'engine': Path(executable).name, 'code': 'INVALID_PDF'})
                    continue
                return pdf, {'executable': Path(executable).name, 'windows_bridge': bridged,
                    'binary_digest': hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
                    'prior_attempts': failures}
            except (subprocess.SubprocessError, OSError) as exc:
                failures.append({'engine': Path(executable).name, 'bridge': bridged, 'code': type(exc).__name__})
    return None, {'attempts': failures, 'code': 'RENDER_UNAVAILABLE'}
