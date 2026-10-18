"""Offline operator management; no model calls, learner jobs or agent tools."""
import argparse
import json
from pathlib import Path

from report_agent.prompt_instructions import (
    configure_report, instruction_context, release_instruction, save_instruction,
)
from report_agent.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    configure = commands.add_parser('configure')
    configure.add_argument('--report-id', required=True)
    save = commands.add_parser('save')
    save.add_argument('--file', type=Path, required=True)
    save.add_argument('--expected-version', type=int, default=0)
    release = commands.add_parser('release')
    release.add_argument('--id', required=True)
    release.add_argument('--version', type=int, help='Omit to withdraw')
    release.add_argument('--expected-active', type=int)
    release.add_argument('--reason', required=True)
    preview = commands.add_parser('preview')
    preview.add_argument('--role', choices=['coordinator', 'writer', 'reviewer', 'layout'], required=True)
    preview.add_argument('--task-id')
    args = parser.parse_args()
    if not (args.project/'state.db').is_file():
        parser.error('Existing isolated project required')
    store = Store(args.project)
    store.manifest
    if args.command == 'configure':
        result = configure_report(store, args.report_id)
    elif args.command == 'save':
        result = save_instruction(store, json.loads(args.file.read_text(encoding='utf-8-sig')),
                                  expected_version=args.expected_version)
    elif args.command == 'release':
        result = release_instruction(store, args.id, args.version,
                                     expected_active=args.expected_active, reason=args.reason)
    else:
        # Host preview only; actual agent context binds task identity server-side.
        result = instruction_context(store, args.role, task_id=args.task_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
