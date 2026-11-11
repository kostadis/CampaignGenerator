"""Aggregate frozen batch scores, preserving failures and exploratory separation."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'20261103-summary-entity-resolution'))
from evaluate import evaluate, candidate_graph


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(rows):
    strict=[r for r in rows if r['strict']]
    return {'cases':len(rows),'strict_cases':len(strict),
            'strict_label_matches':sum(r['predicted']==r['expected'] for r in strict),
            'strict_label_and_evidence_matches':(None if all(r['evidence_valid'] is None for r in strict) else
                sum(r['predicted']==r['expected'] and r['evidence_valid'] is True for r in strict)),
            'all_evidence_failures':[r['id'] for r in rows if r['evidence_valid'] is False],
            'strict_false_coidentity':[r['id'] for r in strict if r['predicted']=='same_referent' and r['expected']!='same_referent'],
            'strict_mismatches':[r['id'] for r in strict if r['predicted']!=r['expected']],
            'abstentions':sum(r['predicted']=='ambiguous' for r in rows),
            'exploratory_cases':len(rows)-len(strict),
            'exploratory_label_matches':sum(r['predicted']==r['expected'] for r in rows if not r['strict']),
            'expected_ambiguous_nonabstentions':[r['id'] for r in rows if r['expected']=='ambiguous' and r['predicted']!='ambiguous'],
            'prediction_counts':dict(Counter(r['predicted'] for r in rows))}


def aggregate(run, previous):
    protocol=json.loads((run/'protocol.json').read_text())
    selection=json.loads((run/'selection.json').read_text())
    assert sha(run/'protocol.json')==selection['protocol_sha256']
    assert sha(run/'gold.json')==selection['gold_sha256']
    registration=json.loads((run/'registration.json').read_text())
    for filename,key in [('payload.json','payload_sha256'),('gold.json','gold_sha256'),('input_hashes.json','input_hashes_sha256')]:
        assert sha(run/filename)==registration[key]
    gold={g['id']:g for g in json.loads((run/'gold.json').read_text())}
    payload=json.loads((run/'payload.json').read_text())
    expected_cases={c['id']:c for c in payload['cases']}
    assert len(expected_cases)==len(payload['cases'])==100
    assert not set(protocol['source_chapters'])&{3,4,5,18,39,42,46}
    previous_report=json.loads(previous.read_text())
    expected_system=previous_report['model_records']['context']['system_sha256']
    arms={'context':[],'surface_only':[]}
    raw_context=[]
    records={}
    for batch in protocol['batches']:
        path=run/batch['directory']
        assert sha(path/'payload.json')==batch['payload_sha256']
        assert json.loads((path/'input_hashes.json').read_text())==json.loads((run/'input_hashes.json').read_text())
        subset=json.loads((path/'payload.json').read_text())
        for case in subset['cases']:assert case==expected_cases[case['id']]
        indexed_refs={r['id']:r for r in payload['references']}
        for ref in subset['references']:assert ref==indexed_refs[ref['id']]
        for pid,passage in subset['passages'].items():assert passage==payload['passages'][pid]
        batch_gold={g['id']:g for g in json.loads((path/'gold.json').read_text())}
        for cid,expectation in batch_gold.items():assert expectation==gold[cid]
        report=evaluate(path)
        records[batch['directory']]={}
        for arm in arms:
            record=report['arms'][arm]['model_record']
            assert record['model']=='gpt-6.1-terra' and record['effort']=='medium'
            assert record['system_sha256']==expected_system and record['gold_sent'] is False
            records[batch['directory']][arm]=record
            for result in report['arms'][arm]['results']:
                expectation=gold[result['id']]
                arms[arm].append({'id':result['id'],'strict':expectation['strict_source_expectation'],
                    'category':expectation['category'],'expected':expectation['relation'],
                    'predicted':result['relation'],'evidence_valid':result['evidence_check']['valid'],
                    'evidence_errors':result['evidence_check']['errors'],'batch':batch['directory']})
            if arm=='context':raw_context.extend(report['arms'][arm]['results'])
    for rows in arms.values():
        assert len(rows)==len({r['id'] for r in rows})==100
        assert {r['id'] for r in rows}==set(gold)
        rows.sort(key=lambda r:r['id'])
    graph=candidate_graph(raw_context,payload['cases'])
    categories={category:metrics([r for r in arms['context'] if r['category']==category])
                for category in sorted({g['category'] for g in gold.values()})}
    relations={relation:metrics([r for r in arms['context'] if r['expected']==relation])
               for relation in sorted({g['relation'] for g in gold.values()})}
    confusion=Counter((r['expected'],r['predicted']) for r in arms['context'] if r['strict'])
    return {'protocol':protocol,'arms':{a:metrics(rows) for a,rows in arms.items()},
            'context_by_category':categories,'context_by_expected_relation':relations,
            'strict_confusion':[{'expected':a,'predicted':b,'count':n} for (a,b),n in sorted(confusion.items())],
            'results':arms,'global_coidentity_distinctness_conflicts':graph['coidentity_distinctness_conflicts'],
            'model_records':records,'root_registration':registration,
            'prior_small_trial':previous_report['terra_medium'],
            'comparison_limit':'New chapters, longer narrative context and batches; not the identical original task or independent trials.',
            'gold_rulings':'Researcher expectations; no independent GM adjudication; exploratory cases excluded from strict denominator.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--previous',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    report=aggregate(args.run,args.previous)
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'arms':report['arms'],'global_conflicts':report['global_coidentity_distinctness_conflicts']},indent=2))
