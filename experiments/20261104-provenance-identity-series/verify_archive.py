"""Verify archived experiment bytes and local documentation links, without inference."""
import hashlib
import json
from pathlib import Path
import re


def verify():
    suite = Path(__file__).resolve().parent
    experiments = suite.parent
    manifest = json.loads((suite/'manifest.json').read_text())
    for relative, expected in manifest['files'].items():
        path = experiments/relative
        assert path.is_file(), f'missing package member: {relative}'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, f'changed member: {relative}'
        if path.suffix == '.md':
            for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', path.read_text()):
                if '://' in target or target.startswith(('#', '/')):
                    continue
                target = target.split('#', 1)[0]
                assert (path.parent/target).exists(), f'broken link in {relative}: {target}'
    private = suite/'private-runtime'
    private_files = 0
    if private.exists():
        inventory = json.loads((private/'inventory.json').read_text())
        for relative, expected in inventory['files'].items():
            path = private/relative
            assert path.is_file(), f'missing private member: {relative}'
            assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, f'changed private member: {relative}'
        private_files = len(inventory['files'])
    return {'package_files_verified': len(manifest['files']),
            'private_files_verified': private_files, 'local_markdown_links_valid': True,
            'model_calls': 0}


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
