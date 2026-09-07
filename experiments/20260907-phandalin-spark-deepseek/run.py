"""Third renderer for the September 7 narration experiments: the DGX Spark.

Same three calls, same byte-identical messages as
../20260907-phandalin-adaptation, ../20260907-phandalin-scene-composition and
../20260907-phandalin-fable-medium. Only the renderer moves:

    codex-cli / gpt-6-astra / medium
    claude-code / claude-fable-5-1 / medium
 -> dgx / deepseek-ai/DeepSeek-V4-Flash-0731 / (no effort dial — see below)

THE EFFORT DIAL DOES NOT TRANSFER, and this experiment does not pretend it does.
The 0731 checkpoint introduced a reasoning_effort scheme of low/high/max — there
is no "medium" in it at all — and the deployed image's tokenizer wrapper predates
that scheme, so an explicit "low" is mis-mapped to "high" while an omitted value
passes through as None. campaignlib's DGX path sends no reasoning_effort, and the
dgxlib registry pins this model to thinking_default: false, so these calls run
with `chat_template_kwargs: {enable_thinking: False}` and no effort control
whatsoever. Read this arm as "the same prompts on the local box", never as
"the same prompts at medium".

prepare  freezes the copied messages and a blinding assignment. No model call.
render   makes exactly one call for one arm and preserves the raw response.
Reading is done by build_reader.py, not from here.

Never writes campaign or production files. Reads the sibling experiments only.
"""
import argparse
from datetime import datetime, timezone
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
CHAPTER_SRC = ROOT.parent / '20260907-phandalin-adaptation'
SCENE_SRC = ROOT.parent / '20260907-phandalin-scene-composition'

BACKEND = 'dgx'
ENDPOINT = 'http://192.168.1.147:8001/v1'   # plain HTTP; vLLM serves no TLS here
MODEL = 'deepseek-ai/DeepSeek-V4-Flash-0731'
MAX_TOKENS = 32000

ARMS = {
    'chapter': ('prompts/chapter_system.md', 'prompts/chapter_user.md'),
    'control': ('prompts/scene_control_system.md', 'prompts/scene_user.md'),
    'composition': ('prompts/scene_composition_system.md', 'prompts/scene_user.md'),
}
SCENE_ARMS = ('control', 'composition')

COPIES = [
    ('prompts/chapter_system.md', CHAPTER_SRC, 'system_prompt.md', 'system_prompt.md'),
    ('prompts/chapter_user.md', CHAPTER_SRC, 'user_prompt.md', 'user_prompt.md'),
    ('prompts/scene_user.md', SCENE_SRC, 'user_prompt.md', 'user_prompt.md'),
    ('prompts/scene_control_system.md', SCENE_SRC, 'control/system_prompt.md', 'control/system_prompt.md'),
    ('prompts/scene_composition_system.md', SCENE_SRC, 'composition/system_prompt.md', 'composition/system_prompt.md'),
]


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
    """Fold the typography a renderer is free to choose.

    The fable run emitted ASCII apostrophes in headings the plan spells with
    U+2019 and its structural check rejected a complete, correctly ordered
    chapter over two characters. A heading check is asking "are these the five
    planned sections, in order" — a question apostrophe style does not bear on.
    The raw headings are recorded verbatim alongside, so the difference stays
    visible rather than being normalized out of the record.
    """
    return (text.replace('’', "'").replace('‘', "'")
                .replace('“', '"').replace('”', '"'))


def verify(case):
    changed = [p for p, expected in case['input_sha256'].items()
               if sha((ROOT / p).read_bytes()) != expected]
    if changed:
        raise ValueError(f'Frozen inputs changed: {changed}')
    if sha((ROOT / 'assignment.json').read_bytes()) != case['assignment_sha256']:
        raise ValueError('Blinding assignment changed')


def prepare():
    if (ROOT / 'case.json').exists() or (ROOT / 'prompts').exists():
        raise ValueError('Prepared case already exists; preserve it or use a fresh directory')
    manifest = {}
    for destination, source_dir, source_path, manifest_key in COPIES:
        source_case = json.loads((source_dir / 'case.json').read_text())
        data = (source_dir / source_path).read_bytes()
        expected = source_case['input_sha256'][manifest_key]
        if sha(data) != expected:
            raise ValueError(f'Source experiment evidence changed: {source_dir.name}/{source_path}')
        save_new(ROOT / destination, data)
        manifest[destination] = expected

    order = list(SCENE_ARMS)
    secrets.SystemRandom().shuffle(order)
    save_new(ROOT / 'assignment.json', json_text({'S1': order[0], 'S2': order[1]}))
    manifest['run.py'] = sha((ROOT / 'run.py').read_bytes())

    chapter_case = json.loads((CHAPTER_SRC / 'case.json').read_text())
    scene_case = json.loads((SCENE_SRC / 'case.json').read_text())
    served = json.loads(subprocess.check_output(
        ['curl', '-sS', '--max-time', '15', f'{ENDPOINT}/models'], text=True))
    live = [m['id'] for m in served['data']]
    if MODEL not in live:
        raise ValueError(f'{MODEL} is not served at {ENDPOINT}; live: {live}')
    context_len = next(m.get('max_model_len') for m in served['data'] if m['id'] == MODEL)

    sys.path.insert(0, str(CG))
    from campaignlib import make_client
    probe = make_client(backend=BACKEND, endpoint=ENDPOINT, model_override=MODEL)
    extra_body = probe.extra_body_for(MODEL, None)

    case = {
        'prepared_at': datetime.now(timezone.utc).isoformat(),
        'question': 'What do the same three messages produce on the local box?',
        'replays': {'chapter': str(CHAPTER_SRC), 'scene_ab': str(SCENE_SRC)},
        'also_compare_with': str(ROOT.parent / '20260907-phandalin-fable-medium'),
        'campaign_commit': chapter_case['campaign_commit'],
        'campaign_repository': 'https://github.com/kostadis/campaigns',
        'generator_commit': subprocess.check_output(
            ['git', '-C', str(CG), 'rev-parse', 'HEAD'], text=True).strip(),
        'backend': BACKEND, 'endpoint': ENDPOINT, 'model': MODEL,
        'served_context_length': context_len,
        'resolved_extra_body': extra_body,
        'effort_note': 'NOT a medium-effort arm. The 0731 reasoning_effort scheme is '
                       'low/high/max with no medium; the deployed image predates it and '
                       'mis-maps an explicit "low" to "high"; campaignlib sends no '
                       'reasoning_effort on this path; and dgxlib pins thinking_default '
                       'false. These calls have no effort control and no reasoning trace.',
        'deployment_note': 'One cross-box TP=2 endpoint (spark1 head + spark2 headless '
                           'worker) in throughput mode. Single-stream decode was spot-checked '
                           'at ~21-31 tok/s and cold prefill at ~1,000-1,200 tok/s, so these '
                           'are minutes-scale calls. Timing here is one uninstrumented '
                           'wall-clock number per arm, not a benchmark.',
        'max_tokens_argument': MAX_TOKENS,
        'token_limit_note': 'vLLM enforces this as a real output ceiling. The Codex adapter '
                            'ignored the same argument; the claude-code path enforced it. '
                            'Three renderers, three different treatments of one number.',
        'arms': list(ARMS), 'scene_arms': list(SCENE_ARMS),
        'scene_heading': scene_case['scene_heading'],
        'chapter_headings': chapter_case['scene_headings'],
        'input_sha256': manifest,
        'assignment_sha256': sha((ROOT / 'assignment.json').read_bytes()),
        'design': 'Three independent single-sample calls on messages byte-identical to the '
                  'archived Astra runs. Renderer is the only deliberate change, and it '
                  'changes more than the weights — see effort_note.',
        'limits': 'One sample per arm; stochastic; no seed; no repetition. Not an effort-'
                  'matched comparison. A local 284B/13B-active MoE at fp8 against two hosted '
                  'frontier models is not a like-for-like quality test and is not offered as '
                  'one. Nothing here revalidates the production narration path.',
    }
    save_new(ROOT / 'case.json', json_text(case))
    verify(case)
    print(json_text({'status': 'prepared', 'frozen_files': len(manifest),
                     'served_model': MODEL, 'context_length': context_len,
                     'extra_body': extra_body}))


def render(arm):
    case = json.loads((ROOT / 'case.json').read_text())
    verify(case)
    system_path, user_path = ARMS[arm]
    target = ROOT / arm
    if (target / 'run.json').exists() or (target / 'response.md').exists():
        raise ValueError('An attempt already exists for this arm; preserve it')
    run = {'status': 'running', 'arm': arm,
           'started_at': datetime.now(timezone.utc).isoformat(),
           'case_sha256': sha((ROOT / 'case.json').read_bytes()),
           'system_sha256': sha((ROOT / system_path).read_bytes()),
           'user_sha256': sha((ROOT / user_path).read_bytes()),
           'backend': BACKEND, 'endpoint': ENDPOINT, 'requested_model': MODEL}
    save_new(target / 'run.json', json_text(run))
    sys.path.insert(0, str(CG))
    started = datetime.now(timezone.utc)
    try:
        from campaignlib import make_client, call_api
        client = make_client(backend=BACKEND, endpoint=ENDPOINT, model_override=MODEL)
        run['resolved_extra_body'] = client.extra_body_for(MODEL, None)
        response = call_api(client, (ROOT / system_path).read_text(),
                            (ROOT / user_path).read_text(), MODEL, max_tokens=MAX_TOKENS)
        save_new(target / 'response.md', response)
        run['response_sha256'] = sha(response.encode())
        run['words'] = len(response.split())
        verify(case)
        run['headings_verbatim'] = re.findall(r'^#{1,6} .+$', response, re.M)
        if arm == 'chapter':
            found = re.findall(r'^## (.+)$', response, re.M)
            expected = case['chapter_headings']
        else:
            found = re.findall(r'^#{1,6} (.+)$', response, re.M)
            expected = [case['scene_heading']]
        run['headings_match_after_normalization'] = (
            [normalize(h) for h in found] == [normalize(h) for h in expected])
        run['headings_match_verbatim'] = found == expected
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
        (target / 'run.json').write_text(json_text(run))
    print(json_text({'arm': arm, 'status': run['status'], 'words': run['words'],
                     'wall_clock_seconds': run['wall_clock_seconds'],
                     'headings_match_verbatim': run['headings_match_verbatim']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'render'])
    parser.add_argument('arm', choices=sorted(ARMS), nargs='?')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    elif args.arm:
        render(args.arm)
    else:
        parser.error('render requires an arm')
