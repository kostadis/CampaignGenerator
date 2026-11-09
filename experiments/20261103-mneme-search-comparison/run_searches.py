"""Fixed read-only mneme CLI retrieval trial. No gold or generative model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args):
    if args.out.exists():
        raise ValueError('output must be fresh; do not overwrite or tune a completed trial')
    payload = json.loads((args.baseline/'payload.json').read_text())
    queries = json.loads(args.queries.read_text())
    assert set(queries) == {c['id'] for c in payload['cases']}
    refs = {r['id']: r for r in payload['references']}
    def bare(case):
        return 'ogres' if any('ogr' in refs[case[s]]['surface'].lower() for s in ('left','right')) else 'orcs'
    requests = {f'context-{cid}': text for cid,text in queries.items()}
    requests.update({'bare-ogres': 'ogres', 'bare-orcs': 'orcs'})
    args.out.mkdir(parents=True)
    (args.out/'payload.json').write_bytes((args.baseline/'payload.json').read_bytes())
    (args.out/'queries.json').write_bytes(args.queries.read_bytes())
    registration = {'campaign': args.campaign, 'campaign_dir': str(args.campaign_dir),
                    'payload_sha256': sha(args.out/'payload.json'), 'queries_sha256': sha(args.out/'queries.json'),
                    'wing': 'summaries', 'results': 10, 'gold_read': False,
                    'case_requests': {c['id']: {'context': f"context-{c['id']}", 'bare': f'bare-{bare(c)}'} for c in payload['cases']},
                    'requests': requests, 'protocol': 'Predeclared context query versus shared bare species; score verbatim hits only.'}
    (args.out/'registration.json').write_text(json.dumps(registration,indent=2)+'\n')
    for name, query in requests.items():
        command = ['mneme','mp','search',args.campaign,query,'--wing','summaries','--results','10','--dir',str(args.campaign_dir)]
        started = time.monotonic()
        try:
            result = subprocess.run(command,capture_output=True,text=True,timeout=90)
            stdout,stderr,status = result.stdout,result.stderr,result.returncode
        except subprocess.TimeoutExpired as error:
            stdout = error.stdout or b''; stderr = error.stderr or b''
            if isinstance(stdout,bytes): stdout=stdout.decode(errors='replace')
            if isinstance(stderr,bytes): stderr=stderr.decode(errors='replace')
            status = 'timeout'
        (args.out/f'{name}.stdout.txt').write_text(stdout)
        (args.out/f'{name}.stderr.txt').write_text(stderr)
        (args.out/f'{name}.record.json').write_text(json.dumps({'command': command,'returncode':status,
            'elapsed_seconds':round(time.monotonic()-started,3),
            'stdout_sha256':sha(args.out/f'{name}.stdout.txt'),'stderr_sha256':sha(args.out/f'{name}.stderr.txt')},indent=2)+'\n')
        print(f'{name}: {status}',flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--queries',type=Path,default=Path(__file__).with_name('queries.json'))
    parser.add_argument('--campaign',default='Phandalin')
    parser.add_argument('--campaign-dir',type=Path,required=True)
    run(parser.parse_args())
