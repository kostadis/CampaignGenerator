"""Can a gap be sealed? One sentence on top of the medium gap-marking run.

Both gap-marking runs left Brewbarry's history as a gap and then had Soma refer
to it anyway — "in the place he couldn't afford once." The gap is therefore not
a clean handoff: whatever the human writes there has to agree with prose that
already assumed an answer. This run adds one sentence telling the narrator not to
lean on what it left behind, and changes nothing else.

Isolated against ../20260907-phandalin-gm-gaps-medium: same model, same effort,
same user message, same treated contract plus one inserted sentence.

THE LINE THE SENTENCE DRAWS, and why it is not "never mention it". Some of this
material is what the players spend the scene talking about — the Harpers, the
basement, the tavern. Forbidding all reference would delete the dialogue, which
is the half of the job the model is supposed to be doing. So the rule separates
the two voices: the players' spoken lines may refer to anything, because they are
the players' own material and not the model's invention; the NARRATOR's own
description and interiority may not establish what a gap holds. That leaves the
fact unasserted outside the gap while keeping the conversation intact.

Whether that line is drawable in practice is the question. A plausible failure is
that the narration goes evasive — circling a fact it may not state — which would
be worse than the leak it fixes. That is a judgement for the GM on reading, not
something the leak check below can score.
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
GAPS = ROOT.parent / '20260907-phandalin-fable-gm-gaps'
MEDIUM = ROOT.parent / '20260907-phandalin-gm-gaps-medium'

MODEL = 'claude-fable-5-1'
EFFORT = 'medium'
EFFORT_SOURCE = 'explicit'
BACKEND = 'claude-code'
MAX_TOKENS = 32000
MARKER = 'GM NARRATION — TO BE WRITTEN:'

ANCHOR = 'These markers are required output, not commentary on your writing.'
ADDED = (
    ' Do not then write around a gap as though its passage already existed: outside the '
    'marker itself, the narrator must not state, restate, paraphrase, or build on what you '
    'have left for the human author. A line a player actually spoke stays as it is even when '
    'it refers to that material — the dialogue is theirs, not yours — but the narrator\'s own '
    'description and interiority must leave the fact unestablished, so the human can write the '
    'gap without contradicting the prose around it. Where that leaves a sentence with nothing '
    'to say, end the paragraph and go on; do not gesture at the withheld fact instead.')

# The observed leak, as a regression check rather than a score.
LEAK_PROBES = [('brewbarry_afford', r"afford"),
               ('basement', r"basement"),
               ('harper_symbol', r"\bharp\b|harper")]


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


def split_voices(text):
    """Narration vs quoted dialogue, per line, outside the markers.

    Crude on purpose: a line carrying a double quote counts as dialogue, the rest
    is narration. It cannot resolve a quote embedded mid-paragraph, so it is a
    pointer to passages worth reading, never a verdict on them.
    """
    body = re.sub(r'^.*' + re.escape(MARKER) + r'.*$', '', text, flags=re.M)
    narration, dialogue = [], []
    for line in body.split('\n'):
        if not line.strip() or line.startswith('#'):
            continue
        (dialogue if ('"' in line or '“' in line) else narration).append(line)
    return '\n'.join(narration), '\n'.join(dialogue)


def prepare():
    if (ROOT / 'case.json').exists() or (ROOT / 'prompts').exists():
        raise ValueError('Prepared case already exists; preserve it or use a fresh directory')
    gaps_case = json.loads((GAPS / 'case.json').read_text())
    manifest = {}
    for destination, source in (('prompts/base_system.md', 'prompts/treated_system.md'),
                                ('prompts/user.md', 'prompts/user.md')):
        data = (GAPS / source).read_bytes()
        if sha(data) != gaps_case['input_sha256'][source]:
            raise ValueError(f'Source experiment evidence changed: {source}')
        save_new(ROOT / destination, data)
        manifest[destination] = gaps_case['input_sha256'][source]

    base = (ROOT / 'prompts/base_system.md').read_text()
    if base.count(ANCHOR) != 1:
        raise ValueError('Anchor sentence not found exactly once in the base contract')
    treated = base.replace(ANCHOR, ANCHOR + ADDED, 1)
    if treated.replace(ANCHOR + ADDED, ANCHOR, 1) != base:
        raise ValueError('Insertion is not cleanly reversible; refusing to proceed')
    save_new(ROOT / 'prompts/treated_system.md', treated)
    save_new(ROOT / 'prompt.diff', ''.join(difflib.unified_diff(
        base.splitlines(True), treated.splitlines(True),
        fromfile='prompts/base_system.md', tofile='prompts/treated_system.md')))
    for name in ('prompts/treated_system.md', 'prompt.diff', 'run.py'):
        manifest[name] = sha((ROOT / name).read_bytes())

    medium_run = json.loads((MEDIUM / 'run.json').read_text())
    if medium_run['status'] != 'rendered':
        raise ValueError('The medium run did not complete; nothing to isolate against')

    case = {
        'prepared_at': datetime.now(timezone.utc).isoformat(),
        'question': 'Told not to lean on what it left in a gap, does fable seal the gaps — '
                    'and does the narration stay readable when it does?',
        'isolates': str(MEDIUM),
        'isolated_variable': 'One sentence added to the contract. Model, effort, and user '
                             'message identical to the medium run.',
        'campaign_commit': gaps_case['campaign_commit'],
        'generator_commit': subprocess.check_output(
            ['git', '-C', str(CG), 'rev-parse', 'HEAD'], text=True).strip(),
        'backend': BACKEND, 'model': MODEL,
        'claude_code_effort': EFFORT, 'claude_code_effort_source': EFFORT_SOURCE,
        'max_tokens_argument': MAX_TOKENS,
        'scene_heading': gaps_case['scene_heading'],
        'marker': MARKER,
        'observed_leak': "Both prior runs gapped Brewbarry's history and then wrote Soma "
                         "referring to it: 'in the place he couldn't afford once' (medium), "
                         "'a barbarian who could not afford a drink here a year ago' (low).",
        'compared_against': {'effort': medium_run['requested_claude_code_effort'],
                             'words': medium_run['words'],
                             'marker_count': medium_run['marker_count'],
                             'response_sha256': medium_run['response_sha256']},
        'design': 'One call. Contract differs from the medium run by one inserted sentence.',
        'limits': 'One sample. The leak check is a keyword probe over a crude narration/dialogue '
                  'split — it finds passages to read, and cannot certify that a gap is sealed or '
                  'that a surviving mention is a real leak. Whether the prose went evasive to '
                  'obey the rule is a reading judgement the probe cannot make at all.',
        'input_sha256': manifest,
    }
    save_new(ROOT / 'case.json', json_text(case))
    verify(case)
    print(json_text({'status': 'prepared',
                     'added_words': len(ADDED.split()),
                     'system_words': len(treated.split())}))


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
        narration, dialogue = split_voices(response)
        run['narration_words'] = len(narration.split())
        run['dialogue_words'] = len(dialogue.split())
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
                     'marker_count': run['marker_count'],
                     'narration_words': run['narration_words'],
                     'dialogue_words': run['dialogue_words'],
                     'wall_clock_seconds': run['wall_clock_seconds'],
                     'actual_identity': run['actual_identity']}))


def leaks():
    """Where each run's NARRATION touches gapped material. Read, don't score."""
    out = {}
    for label, path in (('medium', MEDIUM), ('sealed', ROOT)):
        run = json.loads((path / 'run.json').read_text())
        text = (path / 'response.md').read_text()
        if run['status'] != 'rendered' or sha(text.encode()) != run['response_sha256']:
            raise ValueError(f'{path.name}: no completed unchanged response')
        narration, dialogue = split_voices(text)
        hits = {}
        for name, pattern in LEAK_PROBES:
            rx = re.compile(pattern, re.I)
            hits[name] = {
                'in_narration': [ln.strip() for ln in narration.split('\n') if rx.search(ln)],
                'in_dialogue_count': sum(1 for ln in dialogue.split('\n') if rx.search(ln)),
                'in_a_gap': sum(1 for m in run['markers'] if rx.search(m)),
            }
        out[label] = {'gaps': run['marker_count'], 'words': run['words'],
                      'narration_words': len(narration.split()),
                      'dialogue_words': len(dialogue.split()), 'probes': hits}
    out['reading'] = ('in_narration is the list that matters: the narrator asserting something '
                      'a gap holds. Dialogue hits are the players\' own lines and are expected. '
                      'A keyword can match innocently, so every hit is a passage to read, not a '
                      'confirmed leak.')
    save_new(ROOT / 'leaks.json', json_text(out))
    print(json_text(out))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'render', 'leaks'])
    args = parser.parse_args()
    {'prepare': prepare, 'render': render, 'leaks': leaks}[args.action]()
