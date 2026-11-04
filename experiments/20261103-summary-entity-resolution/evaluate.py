"""Check real-source evidence and score blind model outputs without promoting identity."""
import argparse
import hashlib
import json
from pathlib import Path

RELATIONS = {'same_referent', 'distinct_referents', 'separate_scope',
             'overlap_or_membership', 'ambiguous', 'corrected_nonreferent'}
KINDS = {'individual', 'group', 'kind', 'unknown', 'nonreferent'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_evidence(result, case, payload):
    refs = {r['id']: r for r in payload['references']}
    errors, checked, covered = [], [], set()
    if result['relation'] not in RELATIONS:
        errors.append('unsupported relation')
    for side in ('left', 'right'):
        context = result.get(f'{side}_context', {})
        if context.get('granularity') not in KINDS:
            errors.append(f'invalid {side} granularity')
    if result['relation'] == 'same_referent':
        kinds = {result.get(f'{s}_context', {}).get('granularity') for s in ('left', 'right')}
        if len(kinds) > 1 or kinds & {'unknown', 'nonreferent'}:
            errors.append('same_referent lacks compatible specific granularity')
    for evidence in result.get('evidence', []):
        rid = evidence.get('reference')
        quote = evidence.get('quote', '')
        if rid not in (case['left'], case['right']):
            errors.append('evidence names an unrelated reference')
            continue
        passage = refs[rid]['passage']
        text = payload['passages'][passage]['text']
        if not quote or quote not in text:
            errors.append(f'quote absent from exact passage: {rid}')
            continue
        starts = []
        pos = text.find(quote)
        while pos != -1:
            starts.append(pos)
            pos = text.find(quote, pos+1)
        if any(pos <= refs[rid]['start'] and refs[rid]['end'] <= pos+len(quote) for pos in starts):
            covered.add(rid)
            for other in (case['left'], case['right']):
                if refs[other]['passage'] == passage and any(
                        pos <= refs[other]['start'] and refs[other]['end'] <= pos+len(quote) for pos in starts):
                    covered.add(other)
        else:
            errors.append(f'quote is from the passage but does not cover marked reference: {rid}')
        checked.append({'reference': rid, 'passage': passage,
                        'quote_sha256': hashlib.sha256(quote.encode()).hexdigest(),
                        'matching_span_starts': starts, 'length': len(quote)})
    if result['relation'] != 'ambiguous':
        required = {case[side] for side in ('left', 'right')}
        if not required <= covered:
            errors.append('evidence does not cover both exact marked references')
    return {'valid': not errors, 'errors': errors, 'checked_spans': checked,
            'limit': 'verbatim support checking is not semantic certification'}


def candidate_graph(results, cases):
    """Store experimental mention coidentity separately from disjointness and membership."""
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    indexed = {c['id']: c for c in cases}
    edges = []
    for result in results:
        case = indexed[result['id']]
        left, right = case['left'], case['right']
        if result['relation'] == 'same_referent' and result['evidence_check']['valid']:
            a, b = find(left), find(right)
            parent[max(a, b)] = min(a, b)
        edges.append({'case': result['id'], 'left': left, 'right': right,
                      'relation': result['relation'], 'status': 'unreviewed_model_proposal'})
    conflicts = []
    for edge in edges:
        if edge['relation'] == 'distinct_referents' and find(edge['left']) == find(edge['right']):
            conflicts.append(edge['case'])
    groups = {}
    for rid in sorted(parent):
        groups.setdefault(find(rid), []).append(rid)
    return {'coidentity_candidate_clusters': sorted(groups.values()), 'relations': edges,
            'coidentity_distinctness_conflicts': conflicts,
            'authority': 'experimental graph only; no approved entity IDs, aliases or registry writes'}


def evaluate(run, control_run=None):
    registration = json.loads((run/'registration.json').read_text())
    for path, key in [('gold.json', 'gold_sha256'), ('payload.json', 'payload_sha256'),
                      ('input_hashes.json', 'input_hashes_sha256')]:
        if sha(run/path) != registration[key]:
            raise ValueError(f'registered input changed: {path}')
    payload = json.loads((run/'payload.json').read_text())
    gold = {g['id']: g for g in json.loads((run/'gold.json').read_text())}
    arms = {}
    for arm in ('context', 'surface_only'):
        arm_run = control_run if arm == 'surface_only' and control_run else run
        arm_registration = json.loads((arm_run/'registration.json').read_text())
        data = json.loads((arm_run/f'{arm}.response.json').read_text())
        record = json.loads((arm_run/f'{arm}.record.json').read_text())
        if record['payload_sha256'] != arm_registration['payload_sha256'] or record['response_sha256'] != sha(arm_run/f'{arm}.response.json'):
            raise ValueError('model/output/input binding mismatch')
        if arm_run != run:
            # Reuse only a byte-identical control input; retain its original receipt.
            import copy
            control = copy.deepcopy(payload)
            control['references'] = [{'id': r['id'], 'surface': payload['passages'][r['passage']]['text'][r['start']:r['end']]}
                                     for r in payload['references']]
            control['passages'] = {}
            expected_prompt = json.dumps(control, ensure_ascii=False)
            if hashlib.sha256(expected_prompt.encode()).hexdigest() != record['prompt_sha256']:
                raise ValueError('reused control prompt is not identical')
            if arm_registration['gold_sha256'] != registration['gold_sha256']:
                raise ValueError('gold changed between presentation trials')
        results = {r['id']: r for r in data['results']}
        if len(results) != len(data['results']) or set(results) != set(gold):
            raise ValueError('missing, duplicate or unrequested cases')
        scored = []
        for case in payload['cases']:
            result = results[case['id']]
            result['draft_expected_relation'] = gold[case['id']]['relation']
            result['strict_source_expectation'] = gold[case['id']]['strict_source_expectation']
            result['matches_draft_expectation'] = result['relation'] == gold[case['id']]['relation']
            result['evidence_check'] = validate_evidence(result, case, payload) if arm == 'context' else {
                'valid': None, 'errors': [], 'limit': 'source contexts removed in this arm'}
            scored.append(result)
        strict = [r for r in scored if r['strict_source_expectation']]
        arms[arm] = {'model_record': record, 'source_run': str(arm_run), 'cases': len(scored),
                     'strict_cases': len(strict),
                     'strict_exact_matches': sum(r['matches_draft_expectation'] for r in strict),
                     'abstentions': sum(r['relation'] == 'ambiguous' for r in scored),
                     'positive_coidentity_proposals': sum(r['relation'] == 'same_referent' for r in scored),
                     'strict_false_coidentity': [r['id'] for r in strict if r['relation'] == 'same_referent' and r['draft_expected_relation'] != 'same_referent'],
                     'evidence_failures': [r['id'] for r in scored if r['evidence_check']['valid'] is False],
                     'results': scored}
    graph = candidate_graph(arms['context']['results'], payload['cases'])
    paired_system = arms['context']['model_record']['system_sha256'] == arms['surface_only']['model_record']['system_sha256']
    report = {'experiment': 'raw-summary contextual mention comparison with surface-only control',
              'paired_system_instructions': paired_system,
              'expectations': 'researcher source-based draft gold; not independent GM adjudication',
              'registration': registration, 'arms': arms, 'candidate_graph': graph,
              'limitations': ['One model and one run per arm; not a statistical accuracy estimate.',
                              'Researcher marked mention spans; model receives raw context without hand-labeled identity/location features.',
                              'Three exploratory cases have weaker or underspecified identity continuity and are reported separately.',
                              'Source-byte evidence checks do not prove every semantic inference.',
                              'NVIDIA Auto Ontology runtime and production registry remain unchanged.']}
    (run/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--control-run', type=Path)
    args = parser.parse_args()
    report = evaluate(args.run, args.control_run)
    print(json.dumps({arm: {k: v for k, v in value.items() if k not in ('results', 'model_record')}
                      for arm, value in report['arms'].items()}, indent=2))


if __name__ == '__main__':
    main()
