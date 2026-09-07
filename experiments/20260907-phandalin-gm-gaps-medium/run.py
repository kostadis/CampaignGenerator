"""The effort isolate: the gap-marking prompt at medium instead of low.

The low run answered "does fable leave the GM's narration alone if told to, and
mark where it stopped?" — it did, 17 times. But that run moved two things at once
against the earlier fable drafts: the prompt sentence AND effort medium -> low.
This run moves effort back and changes nothing else, so the pair is a clean
isolate of the dial.

Both prompt files are copied byte-for-byte from ../20260907-phandalin-fable-gm-gaps
and verified against its manifest before any call. Nothing about the contract is
reconsidered here; if the prompt needed changing, this would be the wrong
experiment to change it in.

WHAT THE PAIR IS FOR. The division of labour the gap markers create is the point,
not the marker count: the model cleans up and shapes the players' dialogue, and
the human writes the scene. The low run established that fable will hold that
line. The question here is only whether the prose BETWEEN the gaps — the dialogue
work, which is the half being delegated — is better at medium, and whether the
gaps land in the same places.

Marker agreement between the two runs is reported as a set comparison, not a
score. Two runs marking the same passage is evidence the passage is genuinely
GM-narrated; a passage only one run marks is a question for the GM, not a defect.
"""
import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CG = ROOT.parents[1]
LOW = ROOT.parent / '20260907-phandalin-fable-gm-gaps'

MODEL = 'claude-fable-5-1'
EFFORT = 'medium'
EFFORT_SOURCE = 'explicit'
BACKEND = 'claude-code'
MAX_TOKENS = 32000
MARKER = 'GM NARRATION — TO BE WRITTEN:'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_text(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + '\n'


def save_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value.encode() if isinstance(value, str) else value
    with path.open('xb') as handle:
        handle.write(data)


def normalize(text):
    return (text.replace('’', "'").replace('‘', "'")
                .replace('“', '"').replace('”', '"'))


def verify(case):
    changed = [p for p, expected in case['input_sha256'].items()
               if sha((ROOT / p).read_bytes()) != expected]
    if changed:
        raise ValueError(f'Frozen inputs changed: {changed}')


def prepare():
    if (ROOT / 'case.json').exists() or (ROOT / 'prompts').exists():
        raise ValueError('Prepared case already exists; preserve it or use a fresh directory')
    low_case = json.loads((LOW / 'case.json').read_text())
    manifest = {}
    for name in ('prompts/treated_system.md', 'prompts/user.md'):
        data = (LOW / name).read_bytes()
        if sha(data) != low_case['input_sha256'][name]:
            raise ValueError(f'Source experiment evidence changed: {name}')
        save_new(ROOT / name, data)
        manifest[name] = low_case['input_sha256'][name]
    manifest['run.py'] = sha((ROOT / 'run.py').read_bytes())

    low_run = json.loads((LOW / 'run.json').read_text())
    if low_run['status'] != 'rendered':
        raise ValueError('The low run did not complete; nothing to isolate against')

    case = {
        'prepared_at': datetime.now(timezone.utc).isoformat(),
        'question': 'Same gap-marking contract at medium effort: is the dialogue prose '
                    'between the gaps better, and do the gaps land in the same places?',
        'isolates': str(LOW),
        'isolated_variable': 'claude_code_effort: low -> medium. Prompts byte-identical.',
        'campaign_commit': low_case['campaign_commit'],
        'generator_commit': subprocess.check_output(
            ['git', '-C', str(CG), 'rev-parse', 'HEAD'], text=True).strip(),
        'backend': BACKEND, 'model': MODEL,
        'claude_code_effort': EFFORT, 'claude_code_effort_source': EFFORT_SOURCE,
        'max_tokens_argument': MAX_TOKENS,
        'scene_heading': low_case['scene_heading'],
        'marker': MARKER,
        'compared_against': {'effort': low_run['requested_claude_code_effort'],
                             'words': low_run['words'],
                             'marker_count': low_run['marker_count'],
                             'response_sha256': low_run['response_sha256']},
        'design': 'One call. Both prompts byte-identical to the low run; only the effort differs.',
        'limits': 'One sample per effort level. Two stochastic single samples cannot separate an '
                  'effort difference from run-to-run variance — a difference here is a reason to '
                  'repeat, not a result. Marker agreement is a set comparison for the GM to read, '
                  'never a correctness score: the source, not the other run, is the authority on '
                  'whether a passage is GM-narrated.',
        'input_sha256': manifest,
    }
    save_new(ROOT / 'case.json', json_text(case))
    verify(case)
    print(json_text({'status': 'prepared', 'isolating': case['isolated_variable']}))


def render():
    case = json.loads((ROOT / 'case.json').read_text())
    verify(case)
    if (ROOT / 'run.json').exists() or (ROOT / 'response.md').exists():
        raise ValueError('An attempt already exists; preserve it')
    run = {'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat(),
           'case_sha256': sha((ROOT / 'case.json').read_bytes()),
           'backend': BACKEND, 'requested_model': MODEL,
           'requested_claude_code_effort': EFFORT}
    save_new(ROOT / 'run.json', json_text(run))
    sys.path.insert(0, str(CG))
    started = datetime.now(timezone.utc)
    try:
        from campaignlib import make_client, call_api
        client = make_client(backend=BACKEND, model_override=MODEL,
                             claude_code_effort=EFFORT,
                             claude_code_effort_source=EFFORT_SOURCE)
        response = call_api(client, (ROOT / 'prompts/treated_system.md').read_text(),
                            (ROOT / 'prompts/user.md').read_text(), MODEL,
                            max_tokens=MAX_TOKENS)
        save_new(ROOT / 'response.md', response)
        run['response_sha256'] = sha(response.encode())
        run['words'] = len(response.split())
        identity = client.last_run_identity.as_dict()
        run['actual_identity'] = identity
        if (identity['model'] != MODEL or identity['claude_code_effort'] != EFFORT
                or not identity['claude_code_effort_override']):
            raise ValueError('Actual selection differs from the experiment')
        verify(case)
        found = re.findall(r'^#{1,6} (.+)$', response, re.M)
        run['headings_verbatim'] = re.findall(r'^#{1,6} .+$', response, re.M)
        run['headings_match_after_normalization'] = (
            [normalize(h) for h in found] == [normalize(case['scene_heading'])])
        run['markers'] = re.findall(r'^.*' + re.escape(MARKER) + r'.*$', response, re.M)
        run['marker_count'] = len(run['markers'])
        run['prose_words'] = len(re.sub(
            r'^.*' + re.escape(MARKER) + r'.*$', '', response, flags=re.M).split())
        if not run['headings_match_after_normalization']:
            raise ValueError('Section structure differs from the fixed plan even after '
                             'folding typography; raw response preserved')
        run['status'] = 'rendered'
    except BaseException as exc:
        run['status'] = 'failed'
        run['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        finished = datetime.now(timezone.utc)
        run['finished_at'] = finished.isoformat()
        run['wall_clock_seconds'] = round((finished - started).total_seconds(), 1)
        (ROOT / 'run.json').write_text(json_text(run))
    print(json_text({'status': run['status'], 'words': run['words'],
                     'prose_words': run['prose_words'],
                     'marker_count': run['marker_count'],
                     'wall_clock_seconds': run['wall_clock_seconds'],
                     'actual_identity': run['actual_identity']}))


def compare():
    """Set comparison of the two runs' gaps and prose. No model call."""
    mine = json.loads((ROOT / 'run.json').read_text())
    theirs = json.loads((LOW / 'run.json').read_text())
    for run, path in ((mine, ROOT), (theirs, LOW)):
        if run['status'] != 'rendered' or sha((path / 'response.md').read_bytes()) != run['response_sha256']:
            raise ValueError(f'{path.name}: no completed unchanged response')

    def says(run):
        return [m.split(MARKER, 1)[1].strip().rstrip(']').strip() for m in run['markers']]

    low_says, med_says = says(theirs), says(mine)
    matcher = difflib.SequenceMatcher(None,
                                      [normalize(s).lower() for s in low_says],
                                      [normalize(s).lower() for s in med_says])
    # Near-identical statements are the same gap even when worded differently;
    # anything below the cutoff is reported as its own gap for the GM to judge.
    pairs, only_low, only_med = [], [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            pairs += [{'low': low_says[i], 'medium': med_says[j], 'identical': True}
                      for i, j in zip(range(i1, i2), range(j1, j2))]
        else:
            for i in range(i1, i2):
                best, score = None, 0.0
                for j in range(j1, j2):
                    r = difflib.SequenceMatcher(None, low_says[i].lower(),
                                                med_says[j].lower()).ratio()
                    if r > score:
                        best, score = j, r
                if score >= 0.55:
                    pairs.append({'low': low_says[i], 'medium': med_says[best],
                                  'identical': False, 'similarity': round(score, 3)})
                else:
                    only_low.append(low_says[i])
            for j in range(j1, j2):
                if not any(p.get('medium') == med_says[j] for p in pairs):
                    only_med.append(med_says[j])
    out = {
        'low': {'effort': 'low', 'words': theirs['words'], 'gaps': theirs['marker_count'],
                'seconds': theirs['wall_clock_seconds']},
        'medium': {'effort': 'medium', 'words': mine['words'], 'gaps': mine['marker_count'],
                   'prose_words': mine['prose_words'], 'seconds': mine['wall_clock_seconds']},
        'gaps_both_runs_marked': len(pairs),
        'gaps_only_low_marked': only_low,
        'gaps_only_medium_marked': only_med,
        'paired': pairs,
        'reading': 'A gap both runs marked is evidence the passage really is GM-narrated. A gap '
                   'only one marked is a question for the GM against the source extraction, not '
                   'a defect in either run. This is a set comparison, not a score.',
    }
    save_new(ROOT / 'comparison.json', json_text(out))
    print(json_text({k: v for k, v in out.items() if k != 'paired'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'render', 'compare'])
    args = parser.parse_args()
    {'prepare': prepare, 'render': render, 'compare': compare}[args.action]()
