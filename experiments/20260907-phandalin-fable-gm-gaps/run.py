"""Does fable leave the GM's narration for the human instead of reassigning it?

One scene, one call. claude-fable-5-1 at --effort low.

Base is the control ("Version B") system prompt — the general adaptation brief
the GM preferred in campaigns#237 and again in the blind six-draft read. The user
message is byte-identical to every earlier run of this scene. Exactly one
sentence of the system prompt changes, and prompt.diff records it.

WHY THIS ARM EXISTS. The base contract says:

    Present the fictional consequences of mechanics without roll results, rules
    administration, software operation, or the GM as a character.

Forbidding the GM as a character, with no third option offered, makes silent
reassignment the compliant move — and that is what the fluent drafts did. In the
blind read, fable's composition draft dissolved the GM's explanation of the
two-way drop into Soma's own observation, and the local model's control draft
put it in Valphine's mouth. The reader cannot tell either happened. The one draft
that marked the seam (spark:composition) only did so by breaking the rule and
staging the GM as a character, which is not wanted either.

So the change adds the missing third option: leave a gap the human author fills.
The GM's descriptive narration is theirs to write; the model's job is to write
the players and mark, precisely, where it stopped.

The line drawn is between GM turns that DESCRIBE or EXPLAIN (9 and 3 of them in
this scene's source — a place, an event, a world fact, how something works) and
GM turns that merely CONFIRM or ADJUDICATE (9 and 1, all of the form "Yep."),
which stay table operation and stay dropped. Gapping the latter would bury the
former in noise.
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
SCENE_SRC = ROOT.parent / '20260907-phandalin-scene-composition'

MODEL = 'claude-fable-5-1'
EFFORT = 'low'
EFFORT_SOURCE = 'explicit'          # one of CLAUDE_CODE_EFFORT_SOURCES (CG#413)
BACKEND = 'claude-code'
MAX_TOKENS = 32000
MARKER = 'GM NARRATION — TO BE WRITTEN:'

# The single sentence replaced, and what replaces it. Anchored on the exact
# original text so a drifted base fails loudly instead of silently patching
# something else.
OLD = ('Present the fictional consequences of mechanics without roll results, '
       'rules administration, software operation, or the GM as a character.')
NEW = (
    'Present the fictional consequences of mechanics without roll results, '
    'rules administration, software operation, or the GM as a character. Where '
    'the source attributes a passage to the GM, do not transfer it to a player '
    'character: GM description and explanation must not become a character\'s '
    'speech, perception, memory, or inference, and must not be absorbed unmarked '
    'into the narrator\'s voice. A GM turn that only confirms or adjudicates a '
    'player\'s question is table operation and is dropped as before. A GM turn '
    'that describes or explains something — a place, an event, a world fact, how '
    'something works — is the human author\'s to write, so leave a gap for it '
    'rather than writing it yourself: emit, on its own line, '
    f'[{MARKER} one plain sentence stating what the source establishes there], '
    'and carry the scene on around it. Write everything the players said and did '
    'normally. These markers are required output, not commentary on your writing.')


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
    source_case = json.loads((SCENE_SRC / 'case.json').read_text())
    manifest = {}
    for destination, source_path in [('prompts/base_system.md', 'control/system_prompt.md'),
                                     ('prompts/user.md', 'user_prompt.md')]:
        data = (SCENE_SRC / source_path).read_bytes()
        expected = source_case['input_sha256'][source_path]
        if sha(data) != expected:
            raise ValueError(f'Source experiment evidence changed: {source_path}')
        save_new(ROOT / destination, data)
        manifest[destination] = expected

    base = (ROOT / 'prompts/base_system.md').read_text()
    if base.count(OLD) != 1:
        raise ValueError('Anchor sentence not found exactly once in the base contract')
    treated = base.replace(OLD, NEW, 1)
    if treated.replace(NEW, OLD, 1) != base:
        raise ValueError('Replacement is not cleanly reversible; refusing to proceed')
    save_new(ROOT / 'prompts/treated_system.md', treated)
    save_new(ROOT / 'prompt.diff', ''.join(difflib.unified_diff(
        base.splitlines(True), treated.splitlines(True),
        fromfile='prompts/base_system.md', tofile='prompts/treated_system.md')))
    for name in ('prompts/treated_system.md', 'prompt.diff', 'run.py'):
        manifest[name] = sha((ROOT / name).read_bytes())

    case = {
        'prepared_at': datetime.now(timezone.utc).isoformat(),
        'question': 'Told not to reassign GM narration, and given a gap marker to use '
                    'instead, does fable leave those passages for the human author?',
        'base_prompt': f'{SCENE_SRC.name}/control/system_prompt.md (the preferred brief)',
        'campaign_commit': source_case['campaign_commit'],
        'generator_commit': subprocess.check_output(
            ['git', '-C', str(CG), 'rev-parse', 'HEAD'], text=True).strip(),
        'backend': BACKEND, 'model': MODEL,
        'claude_code_effort': EFFORT, 'claude_code_effort_source': EFFORT_SOURCE,
        'effort_note': 'low, not the medium of the earlier arms — a deliberate second '
                       'change, so this run is not a clean isolate of the prompt edit.',
        'max_tokens_argument': MAX_TOKENS,
        'scene_heading': source_case['scene_heading'],
        'marker': MARKER,
        'gm_turns_in_source': {'describing': 9, 'explaining': 3,
                               'confirming': 9, 'agreeing': 1},
        'treatment': 'One sentence of paragraph 5 replaced. Adds the third option the base '
                     'contract lacked: neither stage the GM as a character nor silently '
                     'reassign their narration, but mark a gap for the human to write.',
        'design': 'Single call. User message byte-identical to every earlier run of this '
                  'scene; system prompt differs from the preferred brief by one sentence.',
        'limits': 'One sample, stochastic, no seed. Two variables move at once (the prompt '
                  'sentence AND effort medium->low), so a difference from the earlier fable '
                  'drafts cannot be attributed to either alone. Whether the marked gaps are '
                  'the RIGHT gaps is a judgement for the GM against the source, not '
                  'something the marker count establishes.',
        'input_sha256': manifest,
    }
    save_new(ROOT / 'case.json', json_text(case))
    verify(case)
    print(json_text({'status': 'prepared',
                     'diff_lines': len((ROOT / 'prompt.diff').read_text().splitlines()),
                     'system_words': len(treated.split()),
                     'user_words': len((ROOT / 'prompts/user.md').read_text().split())}))


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
        run['headings_verbatim'] = re.findall(r'^#{1,6} .+$', response, re.M)
        found = re.findall(r'^#{1,6} (.+)$', response, re.M)
        run['headings_match_after_normalization'] = (
            [normalize(h) for h in found] == [normalize(case['scene_heading'])])
        # The point of the run: count and keep the gaps, don't just pass/fail on them.
        run['markers'] = re.findall(r'^.*' + re.escape(MARKER) + r'.*$', response, re.M)
        run['marker_count'] = len(run['markers'])
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
                     'wall_clock_seconds': run['wall_clock_seconds'],
                     'actual_identity': run['actual_identity']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'render'])
    args = parser.parse_args()
    prepare() if args.action == 'prepare' else render()
