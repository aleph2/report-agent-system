"""Persist a synthetic library/revision trace. No provider model or engineering input."""
import argparse
import asyncio
import json
import runpy
from pathlib import Path

from report_agent.exporting import export_docx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    if (args.project / 'state.db').exists():
        raise SystemExit('Use a new isolated project directory; do not replay this scripted trial into existing state.')
    fixtures = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'tests/test_library_trunk.py'))
    ws = asyncio.run(fixtures['exercise_library'](args.project))
    status = ws.status()
    path = args.project / 'synthetic-library-report.docx'
    path.write_bytes(export_docx(ws, status['delivery']['draft_id']))
    print(json.dumps({'mode': 'scripted_fixture', 'status': status['status'], 'tasks': len(ws.tasks()),
                      'source_versions': len(status['sources']), 'results': len(ws.results()), 'export': str(path)}, indent=2))


if __name__ == '__main__':
    main()
