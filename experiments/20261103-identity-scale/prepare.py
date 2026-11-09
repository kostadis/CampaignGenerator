"""Freeze 100 new source comparisons before inference. No retrieval or canon writes."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import sys

from cases import CHAPTERS, build

PREVIOUS = Path(__file__).resolve().parents[1]/'20261103-summary-entity-resolution'
sys.path.insert(0, str(PREVIOUS))
from prepare_cases import explicit_targets


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def freeze(directory, payload, gold, evidence, hashes):
    directory.mkdir(parents=True,exist_ok=False)
    for name,value in [('payload.json',payload),('gold.json',gold),
                       ('reference_provenance.json',evidence),('input_hashes.json',hashes)]:
        write(directory/name,value)
    write(directory/'registration.json',{
        'gold_sha256':sha((directory/'gold.json').read_bytes()),
        'payload_sha256':sha((directory/'payload.json').read_bytes()),
        'input_hashes_sha256':sha((directory/'input_hashes.json').read_bytes()),
        'status':'Researcher-authored expectations frozen before model calls; not GM adjudication'})


def prepare(root, out):
    assert not set(CHAPTERS)&{3,4,5,18,39,42,46},'old fixture source leaked'
    texts,paths,hashes={}, {}, {}
    for chapter in CHAPTERS:
        candidates=list((root/'summaries').glob(f'20*-chapter_{chapter:02d}*/session-summary.md'))
        assert len(candidates)==1,(chapter,candidates)
        path=candidates[0]
        paths[chapter]=str(path.relative_to(root))
        texts[chapter]=path.read_text()
        hashes[paths[chapter]]=sha(path.read_bytes())
    passages,refs,evidence,symbols,cases,gold={}, {}, {}, {}, [], []

    def R(symbol,chapter,anchor,surface):
        text=texts[chapter]
        summary_start=text.index('## Summary')+len('## Summary')
        summary_end=text.find('\n## ',summary_start)
        if summary_end==-1: summary_end=len(text)
        summary=text[summary_start:summary_end]
        assert summary.count(anchor)==1,(symbol,'anchor occurrence count',summary.count(anchor),anchor)
        pos=summary_start+summary.index(anchor)
        assert surface in anchor,(symbol,'surface absent')
        start=pos+anchor.index(surface);end=start+len(surface)
        # Supply the entire authored narrative section for each selected chapter.
        # This retains prerequisites and alternative candidates outside the
        # immediate target paragraphs; Scenes/NPC appendices are not duplicated.
        pstart,pend=summary_start,summary_end
        pid='p'+sha(f'{chapter}:{pstart}:{pend}'.encode())[:12]
        rid='r'+sha(f'{chapter}:{start}:{end}'.encode())[:12]
        passages[pid]={'chapter':chapter,'text':text[pstart:pend]}
        refs[rid]={'id':rid,'passage':pid,'start':start-pstart,'end':end-pstart}
        evidence[rid]={'id':rid,'path':paths[chapter],'source_sha256':hashes[paths[chapter]],
                       'source_start':start,'source_end':end,'source_line':text.count('\n',0,start)+1,
                       'surface':surface,'passage_start':pstart,'passage_end':pend}
        assert passages[pid]['text'][start-pstart:end-pstart]==surface
        symbols[symbol]=rid

    def C(left,right,relation,rationale,strict=True,category='unspecified'):
        assert left in symbols and right in symbols,(left,right)
        assert symbols[left]!=symbols[right],(left,right,'same marked occurrence')
        pair=frozenset((symbols[left],symbols[right]))
        assert all(frozenset((c['left'],c['right']))!=pair for c in cases),'duplicate pair'
        cases.append({'left':symbols[left],'right':symbols[right]})
        gold.append({'relation':relation,'rationale':rationale,'strict_source_expectation':strict,
                     'category':category,'researcher_symbols':[left,right]})
    build(R,C)
    assert len(cases)==100,len(cases)
    paired=list(zip(cases,gold))
    rng=random.Random(20261103)
    rng.shuffle(paired)
    cases,gold=[],[]
    for i,(case,expectation) in enumerate(paired,1):
        if rng.randrange(2):case['left'],case['right']=case['right'],case['left']
        case['id']=expectation['id']=f'q{i:03d}'
        cases.append(case);gold.append(expectation)
    payload=explicit_targets({'passages':passages,'references':list(refs.values()),'cases':cases})
    freeze(out,payload,gold,evidence,hashes)
    batches=[]
    for i in range(5):
        selected=cases[i*20:(i+1)*20]
        ids={c['id'] for c in selected};rids={c[s] for c in selected for s in ('left','right')}
        rlist=[r for r in payload['references'] if r['id'] in rids]
        pids={r['passage'] for r in rlist}
        subset={'passages':{k:v for k,v in passages.items() if k in pids},'references':rlist,'cases':selected}
        name=f'batch-{i+1:02d}'
        freeze(out/name,subset,[g for g in gold if g['id'] in ids],
               {k:v for k,v in evidence.items() if k in rids},hashes)
        batches.append({'directory':name,'cases':len(selected),'payload_sha256':sha((out/name/'payload.json').read_bytes())})
    protocol={'campaign':'Phandalin','source_chapters':list(CHAPTERS),'source_files':len(hashes),
              'held_out_chapters_from_previous_fixture':True,'case_count':len(cases),'reference_count':len(refs),
              'passage_count':len(passages),'strict_cases':sum(g['strict_source_expectation'] for g in gold),
              'exploratory_cases':sum(not g['strict_source_expectation'] for g in gold),
              'expected_relation_counts':dict(Counter(g['relation'] for g in gold)),
              'strict_relation_counts':dict(Counter(g['relation'] for g in gold if g['strict_source_expectation'])),
              'category_counts':dict(Counter(g['category'] for g in gold)),
              'shuffle_seed':20261103,'batch_size':20,'batches':batches,
              'model':'gpt-6.1-terra','effort':'medium','backend':'codex-cli','planned_model_arm_requests':10,
              'baseline_system_reused':True,'mneme_used':False,'gold_transmitted':False,
              'context':'Full authored Summary sections for chapters referenced in each batch; no retrieval.',
              'authority':'researcher source-based draft expectations; not independent GM adjudication',
              'limits':['Related cases share passages and individuals; case counts are correlated.',
                        'Manually supplied references/context; not automatic extraction or retrieval.',
                        'Five relation classes; no held-out corrected_nonreferent examples.']}
    write(out/'protocol.json',protocol)
    print(json.dumps(protocol,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    prepare(args.campaign_root,args.out)
