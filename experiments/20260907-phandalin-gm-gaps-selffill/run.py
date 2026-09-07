"""Let fable resolve its own gaps: narrate the description, discard the lore.

The inverse of the gap-marking runs. Those asked fable to STOP at the GM's
narration and hand it over. This asks it to come back to the 11 gaps it left in
the medium run and rule on each one itself:

  description — something a character in the scene could perceive right now (a
                place, an action, an event happening in front of them) — is
                written in the POV character's voice, as their perception.
  lore        — world or faction background that is not perceptible in this room
                at this moment — is discarded, and nothing is written in its
                place.

That is a SCOPE decision delegated to the model, which is what the gap markers
existed to keep out of its hands. Read the result as a test of whether fable can
make that call, not as a pipeline proposal: if the classification is wrong, the
error is invisible in the finished prose, which is exactly the failure the
marking design was built to prevent.

INPUT is the medium run's own draft, hash-verified, with its 11 markers intact,
appended to the user message every earlier run of this scene received (voice
references, POV plan, and the reviewed source extraction). The model therefore
has the source it needs to judge each marker, not only the marker's summary.

The system prompt is the preferred brief with ONE sentence replaced — the same
anchor the gap-marking arm replaced, carrying the opposite instruction.
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
MEDIUM = ROOT.parent / '20260907-phandalin-gm-gaps-medium'

MODEL = 'claude-fable-5-1'
EFFORT = 'medium'
EFFORT_SOURCE = 'explicit'
BACKEND = 'claude-code'
MAX_TOKENS = 32000
MARKER = 'GM NARRATION — TO BE WRITTEN:'

OLD = ('Present the fictional consequences of mechanics without roll results, '
       'rules administration, software operation, or the GM as a character.')
NEW = (
    'Present the fictional consequences of mechanics without roll results, '
    'rules administration, software operation, or the GM as a character. The supplied draft '
    'is complete except for bracketed [' + MARKER + ' ...] markers standing where the GM '
    'narrated. Resolve every one of them, and rule on each separately. If the marker holds '
    'DESCRIPTION — something a character present could perceive at that moment: a place, an '
    'action, an event happening in front of them — write it as the POV narrator\'s own '
    'perception, in their voice, at whatever length the moment needs, and remove the marker. '
    'If it holds LORE — world, faction, or historical background that nobody in the room '
    'perceives right now, however true — discard it: delete the marker and write nothing in '
    'its place, letting the scene close over the hole. Do not hedge by half-narrating a lore '
    'marker as something a character happens to know. Leave the surrounding draft as it '
    'stands; change it only where a sentence would not read across a discarded marker.')

TAIL = ('\n\n---\n\n# Draft to complete\n\nThe scene below is finished apart from its markers. '
        'Resolve each one as the writing contract directs, and output the completed scene.\n\n')


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
    scene_case = json.loads((SCENE_SRC / 'case.json').read_text())
    medium_run = json.loads((MEDIUM / 'run.json').read_text())
    draft = (MEDIUM / 'response.md').read_bytes()
    if medium_run['status'] != 'rendered' or sha(draft) != medium_run['response_sha256']:
        raise ValueError('The medium draft is missing or edited')

    manifest = {}
    base = (SCENE_SRC / 'control/system_prompt.md').read_bytes()
    if sha(base) != scene_case['input_sha256']['control/system_prompt.md']:
        raise ValueError('Source experiment evidence changed: control/system_prompt.md')
    save_new(ROOT / 'prompts/base_system.md', base)
    manifest['prompts/base_system.md'] = sha(base)

    original_user = (SCENE_SRC / 'user_prompt.md').read_bytes()
    if sha(original_user) != scene_case['input_sha256']['user_prompt.md']:
        raise ValueError('Source experiment evidence changed: user_prompt.md')
    save_new(ROOT / 'prompts/draft.md', draft)
    manifest['prompts/draft.md'] = medium_run['response_sha256']

    base_text = base.decode()
    if base_text.count(OLD) != 1:
        raise ValueError('Anchor sentence not found exactly once in the base contract')
    treated = base_text.replace(OLD, NEW, 1)
    if treated.replace(NEW, OLD, 1) != base_text:
        raise ValueError('Replacement is not cleanly reversible; refusing to proceed')
    save_new(ROOT / 'prompts/treated_system.md', treated)
    save_new(ROOT / 'prompt.diff', ''.join(difflib.unified_diff(
        base_text.splitlines(True), treated.splitlines(True),
        fromfile='prompts/base_system.md', tofile='prompts/treated_system.md')))
    save_new(ROOT / 'prompts/user.md', original_user.decode() + TAIL + draft.decode())
    for name in ('prompts/treated_system.md', 'prompts/user.md', 'prompt.diff', 'run.py'):
        manifest[name] = sha((ROOT / name).read_bytes())

    markers = re.findall(r'^.*' + re.escape(MARKER) + r'.*$', draft.decode(), re.M)
    case = {
        'prepared_at': datetime.now(timezone.utc).isoformat(),
        'question': 'Given its own 11 gaps, can fable tell description from lore — narrating '
                    'the first in the narrator\'s voice and discarding the second?',
        'input_draft': str(MEDIUM),
        'markers_to_resolve': len(markers),
        'markers': markers,
        'campaign_commit': scene_case['campaign_commit'],
        'generator_commit': subprocess.check_output(
            ['git', '-C', str(CG), 'rev-parse', 'HEAD'], text=True).strip(),
        'backend': BACKEND, 'model': MODEL,
        'claude_code_effort': EFFORT, 'claude_code_effort_source': EFFORT_SOURCE,
        'max_tokens_argument': MAX_TOKENS,
        'scene_heading': scene_case['scene_heading'],
        'treatment': 'One sentence of the preferred brief replaced with the resolve rule — the '
                     'same anchor the gap-marking arm replaced, carrying the opposite '
                     'instruction. User message is the original scene message plus the medium '
                     'draft appended verbatim.',
        'design': 'One call. Not a controlled comparison against any earlier arm: both the '
                  'task and the input differ.',
        'limits': 'One sample. This deliberately hands the model a scope decision — which GM '
                  'material is perceptible description and which is lore — and a wrong call is '
                  'invisible in the finished prose, which is the precise failure the gap markers '
                  'exist to prevent. Read it as a probe of the model\'s judgement, not as a '
                  'pipeline stage. Whether a discarded marker SHOULD have been discarded is a '
                  'question only the GM, reading against the source, can answer.',
        'input_sha256': manifest,
    }
    save_new(ROOT / 'case.json', json_text(case))
    verify(case)
    print(json_text({'status': 'prepared', 'markers_to_resolve': len(markers),
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
        found = re.findall(r'^#{1,6} (.+)$', response, re.M)
        run['headings_verbatim'] = re.findall(r'^#{1,6} .+$', response, re.M)
        run['headings_match_after_normalization'] = (
            [normalize(h) for h in found] == [normalize(case['scene_heading'])])
        run['markers_left_unresolved'] = re.findall(
            r'^.*' + re.escape(MARKER) + r'.*$', response, re.M)
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
                     'unresolved_markers': len(run['markers_left_unresolved']),
                     'wall_clock_seconds': run['wall_clock_seconds'],
                     'actual_identity': run['actual_identity']}))


def rulings():
    """For each original marker: what became of it. A review queue, not a score.

    Each marker's distinctive words are looked for in the finished scene. A marker
    whose content is present was narrated; one whose content is absent was
    discarded. The match is lexical, so it can be wrong in both directions — this
    orders the markers for reading against the source, and rules on nothing.
    """
    case = json.loads((ROOT / 'case.json').read_text())
    run = json.loads((ROOT / 'run.json').read_text())
    text = (ROOT / 'response.md').read_text()
    if run['status'] != 'rendered' or sha(text.encode()) != run['response_sha256']:
        raise ValueError('No completed unchanged response')
    stop = set('the a an and or of in on at to it is was were be been being for with from '
               'that this these those they them their there here as by but not no so if '
               'he she his her its who whom which what when where why how are am do does '
               'did done has have had will would can could should may might must'.split())
    body = normalize(text).lower()
    out = []
    for marker in case['markers']:
        says = marker.split(MARKER, 1)[1].strip().rstrip(']').strip()
        words = [w for w in re.findall(r'[a-z]{4,}', normalize(says).lower()) if w not in stop]
        present = [w for w in set(words) if w in body]
        out.append({'marker': says,
                    'distinctive_words': len(set(words)),
                    'words_present_in_scene': len(present),
                    'share_present': round(len(present) / max(1, len(set(words))), 2),
                    'likely': 'narrated' if len(present) / max(1, len(set(words))) >= 0.5
                              else 'discarded'})
    summary = {'markers': len(out),
               'likely_narrated': sum(1 for r in out if r['likely'] == 'narrated'),
               'likely_discarded': sum(1 for r in out if r['likely'] == 'discarded'),
               'unresolved_markers_left_in_output': len(run['markers_left_unresolved']),
               'words_before': json.loads((MEDIUM / 'run.json').read_text())['words'],
               'words_after': run['words'],
               'reading': 'A lexical presence test, not a classification. It orders the 11 '
                          'markers for reading against the source; whether a discard was right '
                          'is the GM\'s call and nothing here establishes it.',
               'rulings': out}
    save_new(ROOT / 'rulings.json', json_text(summary))
    print(json_text({k: v for k, v in summary.items() if k != 'rulings'}))
    for r in out:
        print(f"  {r['likely']:9} {r['share_present']:.2f}  {r['marker'][:88]}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'render', 'rulings'])
    args = parser.parse_args()
    {'prepare': prepare, 'render': render, 'rulings': rulings}[args.action]()
