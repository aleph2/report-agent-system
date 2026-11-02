"""Read a case's emitted metrics without opening state.db or triggering work."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from report_agent.runtime_metrics import summarize

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.case / 'runtime-metrics.jsonl'), ensure_ascii=False, indent=2))
