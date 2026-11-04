"""Conservative snapshot proposal cache; no inference or canonical writes."""
import hashlib
import json
from pathlib import Path
import sqlite3


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def identity(payload, config):
    # The tested model saw the entire payload. Every passage is a dependency.
    # Registry/ruling snapshots are required even though this fixture used none.
    required = {'campaign', 'model', 'effort', 'system_sha256',
                'registry_revision', 'rulings_revision', 'pipeline_version'}
    if not required <= config.keys():
        raise ValueError('missing resolution dependency')
    return digest({'payload': payload, 'config': config})


class ProposalCache:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS proposals '
                        '(snapshot TEXT, case_id TEXT, response TEXT, response_hash TEXT, '
                        'PRIMARY KEY(snapshot, case_id))')

    def store(self, payload, config, results):
        expected = {c['id'] for c in payload['cases']}
        if len(results) != len(expected) or {r['id'] for r in results} != expected:
            raise ValueError('incomplete or duplicate result set')
        key = identity(payload, config)
        with self.db:
            for result in results:
                self.db.execute('INSERT OR REPLACE INTO proposals VALUES(?,?,?,?)',
                                (key, result['id'], json.dumps(result), digest(result)))

    def lookup(self, payload, config, case_id, canonical=False):
        # Actual reviewed decisions need a separate authoritative ledger.
        # A cache hit and a successful quote check never constitute approval.
        if canonical:
            return {'status': 'review_required'}
        row = self.db.execute('SELECT response,response_hash FROM proposals '
                              'WHERE snapshot=? AND case_id=?',
                              (identity(payload, config), case_id)).fetchone()
        if row is None:
            return {'status': 'resolution_required'}
        result = json.loads(row[0])
        if digest(result) != row[1]:
            return {'status': 'corrupt_cache'}
        return {'status': 'cached_proposal', 'result': result}

    def close(self):
        self.db.close()
