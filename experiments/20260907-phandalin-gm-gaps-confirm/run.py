"""Does the gap-marking contract hold on scenes it was not tuned on?

The contract was written and tested against one scene — Phandalin 2026-09-02
scene 5, Soma narrating, a dead drop in an alley. It marked 11 GM-narrated
passages there and left the players' material written. This runs the same
contract, unchanged and byte-identical, over four scenes it has never seen:

    Brewbarry   20260825 scene 1  A Banker's Revelation
    Valphine    20260811 scene 2  Bullying Through the Loan
    Vukradin    20260623 scene 3  The Universal Basic Treasure Proclamation
    Soma        20260818 scene 1  Arrival at the Spire

Four different narrators, four different sessions, four different scene shapes.
If the marking behaviour is a property of the contract it should survive all of
that; if it was a property of that one scene, this is where that shows.

WHAT WOULD COUNT AS FAILING. Not a different number of gaps — scenes carry
different amounts of GM narration and the count should vary. The contract fails
if a scene comes back with no markers at all while its source is full of GM
turns, if GM material is silently written into a character's perception again,
or if the marking swallows the players' dialogue. The per-scene GM-turn counts
below are recorded so the marker count can be read against how much GM narration
the scene actually contains, rather than in the abstract.

DELIBERATE DEVIATIONS from the tested configuration, both recorded in case.json:
the campaign style and character descriptions are the frozen snapshot the
original experiment used, while the scene extractions and POV plans are read
from the campaign's current HEAD — so the contract and its framing are held
fixed and only the material is new; and each scene ships its narrator's own
prose example alone, where the tested single-scene config carried the two
narrators of its parent chapter. Every scene here has exactly one narrator.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CG = ROOT.parents[1]
GAPS = ROOT.parent / '20260907-phandalin-fable-gm-gaps'
PARENT = ROOT.parent / '20260907-phandalin-adaptation'
CAMPAIGN = Path('/home/kostadis/phandalin')

MODEL = 'claude-fable-5-1'
EFFORT = 'medium'
EFFORT_SOURCE = 'explicit'
BACKEND = 'claude-code'
MAX_TOKENS = 32000
MARKER = 'GM NARRATION — TO BE WRITTEN:'

# arm -> (narrator slug, session, scene number, scene title from the session's plan)
SCENES = {
    'brewbarry': ('brewbarry', '20260825', 1, "A Banker's Revelation"),
    'valphine': ('valphine', '20260811', 2, 'Bullying Through the Loan'),
    'vukradin': ('vukradin', '20260623', 3, 'The Universal Basic Treasure Proclamation'),
    'soma': ('soma', '20260818', 1, 'Arrival at the Spire'),
}


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


def scene_files(session, number):
    """The smoothed extraction for a scene, found by its NN_ prefix.

    Matched on the number, never the title: a session's plan and its extraction
    filenames disagree often enough that name matching would silently pair the
    wrong source with the wrong plan (20260811 scene 2 is 'Bullying Through the
    Loan' in the plan and '02_securing_the_loan.md' on disk).
    """
    folder = CAMPAIGN / 'Phandalin/summaries' / session / 'scene_extractions_smoothed'
    hits = sorted(p for p in folder.glob(f'{number:02d}_*.md') if p.suffix == '.md')
    if len(hits) != 1:
        raise ValueError(f'{session} scene {number}: expected one extraction, found {hits}')
    plans = sorted((CAMPAIGN / 'Phandalin/summaries' / session).glob('narration*/plan.md'))
    if not plans:
        raise ValueError(f'{session}: no narration plan')
    return hits[0], plans[0]


def plan_section(plan_text, number):
    marker = f'## Scene {number}\n'
    if plan_text.count(marker) != 1:
        raise ValueError(f'Scene {number} not uniquely identified in the plan')
    rest = plan_text.split(marker, 1)[1]
    nxt = re.search(r'^## Scene \d+\n', rest, re.M)
    return marker + (rest[:nxt.start()] if nxt else rest).rstrip() + '\n'


def prepare():
    if (ROOT / 'case.json').exists() or (ROOT / 'prompts').exists():
        raise ValueError('Prepared case already exists; preserve it or use a fresh directory')
    gaps_case = json.loads((GAPS / 'case.json').read_text())
    parent_case = json.loads((PARENT / 'case.json').read_text())
    manifest = {}

    system = (GAPS / 'prompts/treated_system.md').read_bytes()
    if sha(system) != gaps_case['input_sha256']['prompts/treated_system.md']:
        raise ValueError('The tested contract has changed; refusing to confirm a different one')
    save_new(ROOT / 'prompts/system.md', system)
    manifest['prompts/system.md'] = sha(system)

    for name in ('campaign_style.md', 'character_references.md'):
        data = (PARENT / name).read_bytes()
        if sha(data) != parent_case['input_sha256'][name]:
            raise ValueError(f'Frozen framing changed: {name}')
        save_new(ROOT / f'inputs/{name}', data)
        manifest[f'inputs/{name}'] = sha(data)

    campaign_commit = subprocess.check_output(
        ['git', '-C', str(CAMPAIGN), 'rev-parse', 'HEAD'], text=True).strip()
    scenes = {}
    for arm, (slug, session, number, title) in SCENES.items():
        source_path, plan_path = scene_files(session, number)
        source = source_path.read_text()
        plan = plan_section(plan_path.read_text(), number)
        example = (CAMPAIGN / 'Phandalin/examples' / f'{slug}.md').read_text()
        heading = f'{slug.capitalize()} — {title}'
        user = [f'# Scene to write\n\n## {heading}',
                '# Campaign style\n\n' + (ROOT / 'inputs/campaign_style.md').read_text(),
                '# Character descriptions\n\n' + (ROOT / 'inputs/character_references.md').read_text(),
                '# Fixed POV plan\n\n' + plan,
                f'# Established prose examples: {slug}\n\n'
                'Style reference only; these are other events, not this session.\n\n' + example,
                f'# Reviewed source for {heading}\n\n' + source]
        save_new(ROOT / f'prompts/{arm}_user.md', '\n\n---\n\n'.join(user) + '\n')
        save_new(ROOT / f'inputs/{arm}_source.md', source)
        manifest[f'prompts/{arm}_user.md'] = sha((ROOT / f'prompts/{arm}_user.md').read_bytes())
        manifest[f'inputs/{arm}_source.md'] = sha(source.encode())
        # Two conventions live in this corpus: `**GM**` (20260825, 20260902) and
        # `**[GM]**` (20260623, 20260811). 20260811 goes further and carries JOINT
        # labels — `**[GM / Brewbarry]**` — where the source itself does not settle
        # who spoke. Count both, and count the joint ones separately: a contract
        # keyed on "where the source attributes a passage to the GM" has no clean
        # answer for those, and that is a property of the material, not the model.
        labels = re.findall(r'^\*\*\[?([^*\]]+)\]?\*\*', source, re.M)
        gm_turns = sum(1 for l in labels if re.search(r'\bGM\b|\bDM\b', l))
        joint = sum(1 for l in labels if re.search(r'\bGM\b|\bDM\b', l) and '/' in l)
        speakers = len(labels)
        convention = '**[GM]**' if '**[GM]**' in source else '**GM**'
        scenes[arm] = {
            'narrator': slug, 'session': session, 'scene_number': number, 'title': title,
            'heading': heading,
            'source_file': str(source_path.relative_to(CAMPAIGN)),
            'plan_file': str(plan_path.relative_to(CAMPAIGN)),
            'gm_turns_in_source': gm_turns,
            'joint_gm_player_turns': joint,
            'label_convention': convention,
            'total_labelled_turns': speakers,
            'source_words': len(source.split()),
            'user_words': len((ROOT / f'prompts/{arm}_user.md').read_text().split()),
        }
    manifest['run.py'] = sha((ROOT / 'run.py').read_bytes())

    case = {
        'prepared_at': datetime.now(timezone.utc).isoformat(),
        'question': 'Does the gap-marking contract behave the same on scenes and narrators it '
                    'was not written against?',
        'contract_from': str(GAPS),
        'contract_note': 'prompts/system.md is byte-identical to the tested contract. Nothing '
                         'about it is reconsidered here.',
        'tested_on': 'Phandalin 20260902 scene 5, Soma narrating — 11 markers at this effort.',
        'campaign_repository': str(CAMPAIGN),
        'campaign_commit': campaign_commit,
        'frozen_framing_from_commit': parent_case['campaign_commit'],
        'deviation_notes': [
            'Campaign style and character descriptions are the frozen snapshot from commit '
            + parent_case['campaign_commit'] + ', while extractions and plans are read from '
            'the campaign at ' + campaign_commit + '. The contract and its framing are held '
            'fixed so only the material is new.',
            'Each scene carries its narrator\'s prose example alone. The tested single-scene '
            'config carried two examples, being the two narrators of its parent chapter; every '
            'scene here has one narrator.',
        ],
        'generator_commit': subprocess.check_output(
            ['git', '-C', str(CG), 'rev-parse', 'HEAD'], text=True).strip(),
        'backend': BACKEND, 'model': MODEL,
        'claude_code_effort': EFFORT, 'claude_code_effort_source': EFFORT_SOURCE,
        'max_tokens_argument': MAX_TOKENS,
        'marker': MARKER,
        'arms': sorted(SCENES), 'scenes': scenes,
        'design': 'One call per scene, four scenes, four narrators, four sessions. Same '
                  'contract, model and effort throughout.',
        'limits': 'One sample per scene. A marker count is not a quality measure and scenes '
                  'legitimately differ in how much GM narration they contain — read each count '
                  'against that scene\'s gm_turns_in_source, and read the drafts. Nothing here '
                  'establishes that the marked passages are the RIGHT ones; only the GM, '
                  'against the source, can say that.',
        'input_sha256': manifest,
    }
    save_new(ROOT / 'case.json', json_text(case))
    verify(case)
    print(json_text({'status': 'prepared',
                     'scenes': {a: {'narrator': s['narrator'], 'session': s['session'],
                                    'gm_turns': s['gm_turns_in_source'],
                                    'joint_gm_player': s['joint_gm_player_turns'],
                                    'convention': s['label_convention'],
                                    'of_turns': s['total_labelled_turns'],
                                    'user_words': s['user_words']}
                                for a, s in scenes.items()}}))


def render(arm):
    case = json.loads((ROOT / 'case.json').read_text())
    verify(case)
    scene = case['scenes'][arm]
    target = ROOT / arm
    if (target / 'run.json').exists() or (target / 'response.md').exists():
        raise ValueError('An attempt already exists for this arm; preserve it')
    run = {'status': 'running', 'arm': arm, 'narrator': scene['narrator'],
           'session': scene['session'], 'title': scene['title'],
           'started_at': datetime.now(timezone.utc).isoformat(),
           'case_sha256': sha((ROOT / 'case.json').read_bytes()),
           'backend': BACKEND, 'requested_model': MODEL,
           'requested_claude_code_effort': EFFORT}
    save_new(target / 'run.json', json_text(run))
    sys.path.insert(0, str(CG))
    started = datetime.now(timezone.utc)
    try:
        from campaignlib import make_client, call_api
        client = make_client(backend=BACKEND, model_override=MODEL,
                             claude_code_effort=EFFORT,
                             claude_code_effort_source=EFFORT_SOURCE)
        response = call_api(client, (ROOT / 'prompts/system.md').read_text(),
                            (ROOT / f'prompts/{arm}_user.md').read_text(), MODEL,
                            max_tokens=MAX_TOKENS)
        save_new(target / 'response.md', response)
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
            [normalize(h) for h in found] == [normalize(scene['heading'])])
        run['markers'] = re.findall(r'^.*' + re.escape(MARKER) + r'.*$', response, re.M)
        run['marker_count'] = len(run['markers'])
        run['gm_turns_in_source'] = scene['gm_turns_in_source']
        if not run['headings_match_after_normalization']:
            raise ValueError('Section structure differs from the supplied heading even after '
                             'folding typography; raw response preserved')
        run['joint_gm_player_turns'] = scene['joint_gm_player_turns']
        if not run['markers'] and scene['gm_turns_in_source']:
            # A scene with no GM narration may legitimately produce no markers, so
            # this only fires when the source actually has GM turns to mark — which
            # is the failure this confirmation exists to catch.
            raise ValueError(f'No markers emitted against {scene["gm_turns_in_source"]} GM '
                             f'turns in the source; raw response preserved')
        run['status'] = 'rendered'
    except BaseException as exc:
        run['status'] = 'failed'
        run['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        finished = datetime.now(timezone.utc)
        run['finished_at'] = finished.isoformat()
        run['wall_clock_seconds'] = round((finished - started).total_seconds(), 1)
        (target / 'run.json').write_text(json_text(run))
    print(json_text({'arm': arm, 'narrator': scene['narrator'], 'status': run['status'],
                     'words': run['words'], 'markers': run['marker_count'],
                     'gm_turns_in_source': scene['gm_turns_in_source'],
                     'seconds': run['wall_clock_seconds']}))


def summary():
    case = json.loads((ROOT / 'case.json').read_text())
    rows, missing = [], []
    for arm in case['arms']:
        path = ROOT / arm / 'run.json'
        if not path.exists():
            missing.append(arm)
            continue
        run = json.loads(path.read_text())
        text = (ROOT / arm / 'response.md')
        row = {'arm': arm, 'narrator': run['narrator'], 'session': run['session'],
               'title': run['title'], 'status': run['status'],
               'words': run.get('words'), 'markers': run.get('marker_count'),
               'gm_turns_in_source': run.get('gm_turns_in_source'),
               'joint_gm_player_turns': run.get('joint_gm_player_turns'),
               'seconds': run.get('wall_clock_seconds'),
               'heading_ok': run.get('headings_match_after_normalization')}
        if run['status'] == 'rendered' and text.exists():
            body = re.sub(r'^.*' + re.escape(MARKER) + r'.*$', '', text.read_text(), flags=re.M)
            lines = [l for l in body.split('\n') if l.strip() and not l.startswith('#')]
            row['dialogue_lines'] = sum(1 for l in lines if '"' in l or '“' in l)
            row['narration_lines'] = len(lines) - row['dialogue_lines']
        else:
            row['error'] = run.get('error')
        rows.append(row)
    tested = {'scene': case['tested_on'], 'markers': 11}
    out = {'tested_on': tested, 'confirmation': rows, 'not_run': missing,
           'reading': 'Marker counts SHOULD vary — scenes contain different amounts of GM '
                      'narration. Read each against gm_turns_in_source. The contract holding '
                      'means: markers emitted, the supplied heading used, the players\' dialogue '
                      'still written. Whether the marked passages are the right ones is a '
                      'judgement against each source that no number here makes.'}
    save_new(ROOT / 'summary.json', json_text(out))
    print(json_text(out))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'render', 'summary'])
    parser.add_argument('arm', choices=sorted(SCENES), nargs='?')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    elif args.action == 'summary':
        summary()
    elif args.arm:
        render(args.arm)
    else:
        parser.error('render requires an arm')
