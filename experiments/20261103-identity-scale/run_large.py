"""Run the unchanged blind resolver on five frozen batches; no gold is read here."""
import argparse
from pathlib import Path
import subprocess
import sys
import time


def main(run):
    runner=Path(__file__).resolve().parents[1]/'20261103-summary-entity-resolution/run_models.py'
    for i in range(1,6):
        batch=run/f'batch-{i:02d}'
        print(f'batch-{i:02d}: starting frozen context and surface-only arms',flush=True)
        started=time.monotonic()
        result=subprocess.run([sys.executable,str(runner),'--run',str(batch),
                               '--model','gpt-6.1-terra','--effort','medium'])
        if result.returncode:
            raise RuntimeError(f'{batch.name} failed; preserve output and inspect, no automatic rerun')
        print(f'{batch.name}: both arms retained; wall time {time.monotonic()-started:.1f}s',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    main(parser.parse_args().run)
