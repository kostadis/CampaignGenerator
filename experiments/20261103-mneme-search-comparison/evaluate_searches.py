"""Offline retrieval coverage evaluation. Does not score entity identity."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

from retrieval import parse_hits, score_case


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(run):
    registration=json.loads((run/'registration.json').read_text())
    assert sha(run/'payload.json')==registration['payload_sha256']
    assert sha(run/'queries.json')==registration['queries_sha256']
    payload=json.loads((run/'payload.json').read_text())
    observations={}
    for name in registration['requests']:
        record=json.loads((run/f'{name}.record.json').read_text())
        assert sha(run/f'{name}.stdout.txt')==record['stdout_sha256']
        assert sha(run/f'{name}.stderr.txt')==record['stderr_sha256']
        stdout=(run/f'{name}.stdout.txt').read_text()
        stderr=(run/f'{name}.stderr.txt').read_text()
        hits=parse_hits(stdout) if record['returncode']==0 else []
        observations[name]={'hits':hits,'returncode':record['returncode'],
            'elapsed_seconds':record['elapsed_seconds'],
            'embedder_identity_warning':'EmbedderIdentityUnknownWarning' in stdout+stderr,
            'related_theme_block_present':'Related (LLM-tagged themes' in stdout,
            'verbatim_hits':len(hits)}
    modes={}
    for mode in ('bare','context'):
        scored=[]
        for case in payload['cases']:
            name=registration['case_requests'][case['id']][mode]
            observed=observations[name]
            result=score_case(case,payload,observed['hits'])
            result['request']=name
            result['returncode']=observed['returncode']
            scored.append(result)
        modes[mode]={'cases':len(scored),'coverage':{str(k):{
            metric:sum(c['coverage'][str(k)][metric] for c in scored)
            for metric in ('both_sources','both_target_anchors')} for k in (1,5,10)},'results':scored}
    requests={name:{k:v for k,v in observed.items() if k!='hits'} for name,observed in observations.items()}
    return {'task':'retrieval coverage of frozen mention pairs; not relation accuracy',
        'requests':requests,'unique_search_requests':len(requests),
        'failed_requests':[name for name,r in requests.items() if r['returncode']!=0],
        'median_cli_seconds':statistics.median(r['elapsed_seconds'] for r in requests.values()),
        'modes':modes,'gold_read':False,'generative_model_calls':0,
        'limits':['Human-authored context queries use known encounter clues; no blind user-query distribution.',
                  'Coverage uses normalized exact 60-character neighborhoods around frozen targets in displayed verbatim hits.',
                  'Source coverage checks chapter-prefixed basename, not identity or sufficient supporting evidence.',
                  'Palace searches all indexed summaries, unlike the manually selected 14-passage model task.',
                  'No same/distinct/membership predictions are produced by mneme search.',
                  'Related LLM-tagged themes are excluded from coverage scoring.',
                  'Embedding inference occurs at query time; zero generative calls does not mean zero model use.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    report=evaluate(args.run)
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v['coverage'] for k,v in report['modes'].items()},indent=2))
