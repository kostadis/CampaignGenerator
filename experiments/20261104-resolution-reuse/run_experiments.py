"""Exercise cache reuse/invalidation against saved Terra proposals, offline."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile

from reuse import ProposalCache, digest


def run(runtime):
    payload = json.loads((runtime/'payload.json').read_text())
    record = json.loads((runtime/'context.record.json').read_text())
    response_path = runtime/'context.response.json'
    import hashlib
    assert hashlib.sha256(response_path.read_bytes()).hexdigest() == record['response_sha256']
    assert hashlib.sha256((runtime/'payload.json').read_bytes()).hexdigest() == record['payload_sha256']
    results = json.loads(response_path.read_text())['results']
    config = {'campaign': 'Phandalin', 'model': record['model'], 'effort': record['effort'],
              'system_sha256': record['system_sha256'], 'registry_revision': 'not_supplied',
              'rulings_revision': 'not_supplied', 'pipeline_version': 'snapshot-cache-v1'}
    cases = payload['cases']
    observations = []

    def check(name, cache, data, settings, expected, canonical=False, repeats=1):
        statuses = [cache.lookup(data, settings, c['id'], canonical=canonical)['status']
                    for _ in range(repeats) for c in cases]
        assert statuses == [expected]*len(statuses), (name, statuses)
        observations.append({'experiment': name, 'lookups': len(statuses),
                             'expected': expected, 'observed': expected, 'passed': True})

    with tempfile.TemporaryDirectory(prefix='resolution-reuse-') as tmp:
        db = Path(tmp)/'cache.sqlite'
        cache = ProposalCache(db)
        check('cold snapshot', cache, payload, config, 'resolution_required')
        cache.store(payload, config, results)
        cache.close()
        cache = ProposalCache(db)
        check('ten repeats after process-style reopen', cache, payload, config,
              'cached_proposal', repeats=10)
        check('proposal is not canon', cache, payload, config, 'review_required', canonical=True)
        for field, value in [('model', 'different-model'), ('effort', 'high'),
                             ('system_sha256', 'new-instructions'),
                             ('registry_revision', 'new-registry'),
                             ('rulings_revision', 'new-GM-ruling'),
                             ('campaign', 'different-campaign')]:
            changed = {**config, field: value}
            check(f'changed {field}', cache, payload, changed, 'resolution_required')
        changed = deepcopy(payload)
        next(iter(changed['passages'].values()))['text'] += '\nNew evidence.'
        check('changed existing passage', cache, changed, config, 'resolution_required')
        changed = deepcopy(payload)
        changed['passages']['new_passage'] = {'chapter': 999, 'text': 'New candidate context.'}
        check('added passage or candidate context', cache, changed, config, 'resolution_required')
        changed = deepcopy(payload)
        changed['references'][0]['start'] += 1
        check('changed marked reference', cache, changed, config, 'resolution_required')
        # Ambiguity is a reusable outcome, not a reason to call on every lookup.
        ambiguous = next(r for r in results if r['id'] == 'q16')
        assert ambiguous['relation'] == 'ambiguous'
        assert cache.lookup(payload, config, 'q16')['result']['relation'] == 'ambiguous'
        observations.append({'experiment': 'q16 ambiguity preserved', 'passed': True})
        cache.db.execute("UPDATE proposals SET response_hash='tampered'")
        cache.db.commit()
        check('corrupt saved response', cache, payload, config, 'corrupt_cache')
        cache.close()
    return {'model_calls_made': 0, 'saved_model': record['model'], 'saved_effort': record['effort'],
            'response_sha256': record['response_sha256'], 'fixture_snapshot': digest(payload),
            'experiments': observations,
            'limits': ['Offline reuse/invalidation tests, not additional model-accuracy trials.',
                       'Snapshot-wide invalidation because the model saw the whole payload.',
                       'No gold used, no automatic review, no canonical writes, no inference on cache miss.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.runtime)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'passed': len(result['experiments']), 'model_calls_made': 0}))
