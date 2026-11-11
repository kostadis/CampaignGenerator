"""Open only source files named by retrieved hits through the declared corpus TOC."""
import argparse
import hashlib
import json
from pathlib import Path

from retrieval import anchor, normalize, parse_hits


def expand(run, toc_path, campaign_root):
    toc=json.loads(toc_path.read_text())
    assert toc['valid'] and not toc['findings']
    declared={}
    for entry in toc['kinds']['summaries']['files']:
        basename=Path(entry['path']).name
        if basename in declared:
            raise ValueError('CLI basename is ambiguous; cannot expand safely')
        declared[basename]=entry
    registration=json.loads((run/'registration.json').read_text())
    assert hashlib.sha256((run/'payload.json').read_bytes()).hexdigest()==registration['payload_sha256']
    payload=json.loads((run/'payload.json').read_text())
    refs={r['id']:r for r in payload['references']}
    snapshots={}
    requests={}
    for name in registration['requests']:
        record=json.loads((run/f'{name}.record.json').read_text())
        assert record['returncode']==0
        assert hashlib.sha256((run/f'{name}.stdout.txt').read_bytes()).hexdigest()==record['stdout_sha256']
        hits=parse_hits((run/f'{name}.stdout.txt').read_text())
        opened=[]
        for hit in hits:
            entry=declared[hit['source']]
            key=entry['path']
            if key not in snapshots:
                path=campaign_root/key
                assert path.resolve().is_relative_to(campaign_root.resolve())
                assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['sha256']
                snapshots[key]={'sha256':entry['sha256'],'text':path.read_text()}
            opened.append({'rank':hit['rank'],'path':key})
        requests[name]=opened
    modes={}
    for mode in ('bare','context'):
        cases=[]
        for case in payload['cases']:
            name=registration['case_requests'][case['id']][mode]
            ranks={}
            for side in ('left','right'):
                r=refs[case[side]]; passage=payload['passages'][r['passage']]
                target=normalize(anchor(r,passage))
                matching=[v['rank'] for v in requests[name]
                          if Path(v['path']).name.startswith(f"{int(passage['chapter']):03d}-")
                          and target in normalize(snapshots[v['path']]['text'])]
                ranks[side]=min(matching,default=None)
            cases.append({'id':case['id'],'target_ranks':ranks,'coverage':{
                str(k):all(rank is not None and rank<=k for rank in ranks.values()) for k in (1,5,10)}})
        modes[mode]={'cases':len(cases),'both_target_anchors_after_expansion':{
            str(k):sum(c['coverage'][str(k)] for c in cases) for k in (1,5,10)},'results':cases}
    private={'files':snapshots,'requests':requests}
    (run/'source-expansion.private.json').write_text(json.dumps(private,ensure_ascii=False,indent=2)+'\n')
    return {'modes':modes,'opened_sources':{k:v['sha256'] for k,v in snapshots.items()},
            'declared_summary_files':len(declared),'gold_read':False,'new_searches':0,'generative_model_calls':0,
            'limit':'Full source expansion increases context size; it establishes evidence availability, not identity accuracy.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--toc',type=Path,required=True)
    parser.add_argument('--campaign-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    report=expand(args.run,args.toc,args.campaign_root)
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({m:v['both_target_anchors_after_expansion'] for m,v in report['modes'].items()},indent=2))
