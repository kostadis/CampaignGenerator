"""One frozen A/B pair using the existing CampaignGenerator text-only adapter."""
import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CG = ROOT.parents[1]
PARENT = ROOT.parent / '20260907-phandalin-adaptation'
SESSION = 'inputs/Phandalin/summaries/20260902'
SOURCE = SESSION + '/scene_extractions_smoothed/05_the_dead_drop_at_the_house_of_a_thousand_faces.md'
TITLE = 'Soma — Harpers Behind the Wall'
MODEL = 'gpt-6-astra'
EFFORT = 'medium'
ARMS = ('control', 'composition')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value.encode() if isinstance(value, str) else value
    with path.open('xb') as handle:
        handle.write(data)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def verify(case):
    for path, expected in case['input_sha256'].items():
        if sha((ROOT / path).read_bytes()) != expected:
            raise ValueError(f'Frozen input changed: {path}')
    if sha((ROOT / 'assignment.json').read_bytes()) != case['assignment_sha256']:
        raise ValueError('Blinding assignment changed')


def prepare():
    if (ROOT / 'case.json').exists() or (ROOT / 'inputs').exists():
        raise ValueError('Prepared case already exists; preserve it')
    parent_case = json.loads((PARENT / 'case.json').read_text())
    for path, expected in parent_case['input_sha256'].items():
        if sha((PARENT / path).read_bytes()) != expected:
            raise ValueError(f'Parent evidence changed: {path}')
    copies = {
        'source.md': SOURCE,
        'campaign_style.md': 'campaign_style.md',
        'character_references.md': 'character_references.md',
        'examples/soma.md': 'inputs/Phandalin/examples/soma.md',
        'examples/vukradin.md': 'inputs/Phandalin/examples/vukradin.md',
        'original_plan.md': SESSION + '/narration3/plan.md',
        'original_system.md': 'system_prompt.md',
        'parent_case.json': 'case.json',
    }
    manifest = {}
    for target, source in copies.items():
        data = (PARENT / source).read_bytes()
        destination = ROOT / 'inputs' / target
        save_new(destination, data)
        manifest[str(destination.relative_to(ROOT))] = sha(data)
    original = (ROOT / 'inputs/original_system.md').read_text()
    intro = 'Write an engaging chapter of campaign fan fiction from the supplied reviewed scene extractions.'
    ending = 'Output only the finished chapter: the supplied chapter title followed by exactly the five supplied section headings and their narration. Do not include an audit, a coverage checklist, commentary on your writing, or new sections. Do not quote the source documents as documents.'
    if original.count(intro) != 1 or original.count(ending) != 1:
        raise ValueError('Unrecognized original writing contract')
    control = original.replace(intro, 'Write an engaging scene of campaign fan fiction from the supplied reviewed scene extraction.')
    control = control.replace(ending, 'Output only the finished scene under the supplied section heading. Do not include a chapter title, an audit, a coverage checklist, commentary on your writing, or new sections. Do not quote the source documents as documents.')
    paragraphs = control.split('\n\n')
    indices = [i for i, text in enumerate(paragraphs) if text.startswith('Compose complete scenes with')]
    if len(indices) != 1:
        raise ValueError('Composition paragraph not uniquely identified')
    old_block = paragraphs[indices[0]]
    new_block = (ROOT / 'composition_block.md').read_text().strip()
    composition = control.replace(old_block, new_block, 1)
    assert composition.replace(new_block, old_block, 1) == control
    save_new(ROOT / 'control/system_prompt.md', control)
    save_new(ROOT / 'composition/system_prompt.md', composition)
    save_new(ROOT / 'prompt.diff', ''.join(difflib.unified_diff(
        control.splitlines(True), composition.splitlines(True),
        fromfile='control/system_prompt.md', tofile='composition/system_prompt.md')))
    full_plan = (ROOT / 'inputs/original_plan.md').read_text()
    if full_plan.count('## Scene 5\n') != 1:
        raise ValueError('Scene 5 plan not uniquely identified')
    plan = '## Scene 5\n' + full_plan.split('## Scene 5\n', 1)[1]
    save_new(ROOT / 'inputs/scene_plan.md', plan)
    user = [f'# Scene to write\n\n## {TITLE}',
            '# Campaign style\n\n' + (ROOT / 'inputs/campaign_style.md').read_text(),
            '# Character descriptions\n\n' + (ROOT / 'inputs/character_references.md').read_text(),
            '# Fixed POV plan\n\n' + plan]
    for slug in ('vukradin', 'soma'):
        user.append(f'# Established prose examples: {slug}\n\n'
                    'Style reference only; these are other events, not this session.\n\n'
                    + (ROOT / f'inputs/examples/{slug}.md').read_text())
    user.append(f'# Reviewed source for {TITLE}\n\n' + (ROOT / 'inputs/source.md').read_text())
    save_new(ROOT / 'user_prompt.md', '\n\n---\n\n'.join(user) + '\n')
    order = list(ARMS)
    secrets.SystemRandom().shuffle(order)
    assignment = {'A': order[0], 'B': order[1]}
    save_new(ROOT / 'assignment.json', json_text(assignment))
    for name in ['inputs/scene_plan.md', 'run.py', 'build_reader.py',
                 'composition_block.md', 'evaluation_criteria.md', 'user_prompt.md',
                 'control/system_prompt.md', 'composition/system_prompt.md', 'prompt.diff']:
        manifest[name] = sha((ROOT / name).read_bytes())
    case = {
        'prepared_at': datetime.now(timezone.utc).isoformat(),
        'parent_experiment': str(PARENT),
        'campaign_commit': parent_case['campaign_commit'],
        'campaign_repository': 'https://github.com/kostadis/campaigns',
        'campaign_repository_visibility': 'public (confirmed during parent experiment)',
        'generator_commit': subprocess.check_output(['git', '-C', str(CG), 'rev-parse', 'HEAD'], text=True).strip(),
        'model': MODEL, 'reasoning_effort': EFFORT, 'backend': 'codex-cli',
        'max_tokens_argument': 32000,
        'token_limit_note': 'Codex subscription adapter does not enforce this API-style argument.',
        'arms': list(ARMS), 'scene_heading': TITLE, 'input_sha256': manifest,
        'assignment_sha256': sha((ROOT / 'assignment.json').read_bytes()),
        'design': 'One independent single-scene generation per arm. Identical user message, model, effort, examples, and factual constraints. Only the composition block differs.',
        'common_scope_change': 'Both arms adapt the parent chapter brief to a single scene and receive only the unchanged scene 5 extraction and scene 5 POV plan; character references and both prose examples are unchanged.',
        'treatment': 'Replaces generic composition paragraph with planning plus specific editorial direction about scene 5; these components are not separately isolated.',
        'limits': 'One pair; stochastic outputs; no exposed random seed; no repeated trials. Source selection is identical between arms, not identical to the preceding whole-chapter run. A/B labels randomly assigned before outputs. No raw response editing or automatic retries.',
    }
    save_new(ROOT / 'case.json', json_text(case))
    verify(case)
    print(json_text({'status': 'prepared', 'frozen_inputs': len(manifest),
                     'shared_user_words': len((ROOT / 'user_prompt.md').read_text().split()),
                     'changed_block_only': True}))


def render(arm):
    if arm not in ARMS:
        raise ValueError('Unknown arm')
    case = json.loads((ROOT / 'case.json').read_text())
    verify(case)
    target = ROOT / arm
    if (target / 'run.json').exists() or (target / 'response.md').exists():
        raise ValueError('Attempt already exists; preserve it')
    run = {'status': 'running', 'arm': arm,
           'started_at': datetime.now(timezone.utc).isoformat(),
           'case_sha256': sha((ROOT / 'case.json').read_bytes()),
           'system_sha256': sha((target / 'system_prompt.md').read_bytes()),
           'user_sha256': sha((ROOT / 'user_prompt.md').read_bytes()),
           'requested_model': MODEL, 'requested_reasoning_effort': EFFORT}
    save_new(target / 'run.json', json_text(run))
    sys.path.insert(0, str(CG))
    os.environ.setdefault('CG_CODEX_TIMEOUT', '1800')
    try:
        from campaignlib import make_client, call_api
        client = make_client(backend='codex-cli', model_override=MODEL,
                             reasoning_effort=EFFORT, reasoning_effort_source='cli')
        response = call_api(client, (target / 'system_prompt.md').read_text(),
                            (ROOT / 'user_prompt.md').read_text(), MODEL, max_tokens=32000)
        save_new(target / 'response.md', response)
        run['response_sha256'] = sha(response.encode())
        run['actual_identity'] = client.last_run_identity.as_dict()
        if run['actual_identity']['model'] != MODEL or run['actual_identity']['codex_reasoning_effort'] != EFFORT:
            raise ValueError('Actual selection differs from experiment')
        verify(case)
        headings = re.findall(r'^#{1,6} [^\r\n]+', response, re.M)
        if headings != ['## ' + TITLE]:
            raise ValueError('Unexpected output headings; raw response preserved')
        run['status'] = 'rendered'
    except BaseException as exc:
        run['status'] = 'failed'
        run['error'] = str(exc)
        raise
    finally:
        run['finished_at'] = datetime.now(timezone.utc).isoformat()
        (target / 'run.json').write_text(json_text(run))
    print(json_text({'arm': arm, 'status': run['status'], 'actual_identity': run['actual_identity']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'render'])
    parser.add_argument('arm', choices=ARMS, nargs='?')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    elif args.arm:
        render(args.arm)
    else:
        parser.error('render requires an arm')
