"""Replay the September 7 narration experiments on claude-fable-5-1 / medium.

Nothing here is new prompt design. Every system and user message is copied
byte-for-byte from the two frozen Astra experiments in this directory's
siblings and verified against their own recorded hashes before any model call.
The only deliberate difference from the archived runs is the renderer:

    codex-cli / gpt-6-astra / medium   ->   claude-code / claude-fable-5-1 / medium

That is the whole point. Holding the messages fixed is what makes the model
the variable; if a prompt were touched here the comparison would answer a
different question, so `prepare` refuses to run when a copied file's hash does
not match the source experiment's manifest.

prepare  freezes the copied messages, the archived Astra responses used as the
         reference column, and a randomized blinding assignment. No model call.
render   makes exactly one call for one arm, through CampaignGenerator's own
         claude-code adapter, and preserves the raw response unedited.
reader   builds offline metrics and two blind HTML readers. No model call.

Never writes campaign or production files. Reads the sibling experiments only.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import secrets
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CG = ROOT.parents[1]
CHAPTER_SRC = ROOT.parent / '20260907-phandalin-adaptation'
SCENE_SRC = ROOT.parent / '20260907-phandalin-scene-composition'

MODEL = 'claude-fable-5-1'
EFFORT = 'medium'
BACKEND = 'claude-code'
# The archived Codex runs passed source='cli'. ClaudeCodeRunIdentity.banner()
# renders only explicit/environment/clamp and falls through to "inherited —
# CampaignGenerator sent no override" for any other string, so 'cli' printed a
# banner that contradicted the identity it was describing. The command line is
# the same either way (override_sent is True whenever an effort is supplied);
# 'explicit' is chosen so the printed banner and the recorded identity agree.
EFFORT_SOURCE = 'explicit'
MAX_TOKENS = 32000

# Arm -> (system prompt, user prompt) inside this experiment.
ARMS = {
    'chapter': ('prompts/chapter_system.md', 'prompts/chapter_user.md'),
    'control': ('prompts/scene_control_system.md', 'prompts/scene_user.md'),
    'composition': ('prompts/scene_composition_system.md', 'prompts/scene_user.md'),
}
SCENE_ARMS = ('control', 'composition')
SCENE_HEADING = 'Soma — Harpers Behind the Wall'

# What gets copied in, and where its authoritative hash lives.
# (destination, source experiment, path within it, manifest key or None for a response)
COPIES = [
    ('prompts/chapter_system.md', CHAPTER_SRC, 'system_prompt.md', 'system_prompt.md'),
    ('prompts/chapter_user.md', CHAPTER_SRC, 'user_prompt.md', 'user_prompt.md'),
    ('prompts/scene_user.md', SCENE_SRC, 'user_prompt.md', 'user_prompt.md'),
    ('prompts/scene_control_system.md', SCENE_SRC, 'control/system_prompt.md', 'control/system_prompt.md'),
    ('prompts/scene_composition_system.md', SCENE_SRC, 'composition/system_prompt.md', 'composition/system_prompt.md'),
    ('reference/historical_chapter.md', CHAPTER_SRC, 'baseline.md', 'baseline.md'),
]
# Archived Astra outputs, hashed in each experiment's run.json rather than case.json.
RESPONSE_COPIES = [
    ('reference/astra_chapter.md', CHAPTER_SRC, 'response.md', 'run.json'),
    ('reference/astra_control.md', SCENE_SRC, 'control/response.md', 'control/run.json'),
    ('reference/astra_composition.md', SCENE_SRC, 'composition/response.md', 'composition/run.json'),
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_text(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + '\n'


def save_new(path, value):
    """Write once. An existing artifact is evidence, not a scratch file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value.encode() if isinstance(value, str) else value
    with path.open('xb') as handle:
        handle.write(data)


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
    for destination, source_dir, source_path, run_path in RESPONSE_COPIES:
        run = json.loads((source_dir / run_path).read_text())
        data = (source_dir / source_path).read_bytes()
        if run['status'] != 'rendered' or sha(data) != run['response_sha256']:
            raise ValueError(f'Archived response missing or edited: {source_dir.name}/{source_path}')
        save_new(ROOT / destination, data)
        manifest[destination] = run['response_sha256']

    # Blinding. The user judges prose, so neither the renderer nor the prompt
    # arm may be legible from the label. Scene labels cover all four single-scene
    # drafts (two models x two arms); chapter labels cover the two generated
    # chapters. The edited historical chapter stays openly labelled: it is the
    # known baseline and its length and quote density give it away anyway.
    scene_drafts = [f'{model}:{arm}' for model in ('astra', 'fable') for arm in SCENE_ARMS]
    chapter_drafts = ['astra:chapter', 'fable:chapter']
    rng = secrets.SystemRandom()
    rng.shuffle(scene_drafts)
    rng.shuffle(chapter_drafts)
    assignment = {
        'scene': dict(zip(('W', 'X', 'Y', 'Z'), scene_drafts)),
        'chapter': dict(zip(('P', 'Q'), chapter_drafts)),
    }
    save_new(ROOT / 'assignment.json', json_text(assignment))
    manifest['run.py'] = sha((ROOT / 'run.py').read_bytes())

    chapter_case = json.loads((CHAPTER_SRC / 'case.json').read_text())
    scene_case = json.loads((SCENE_SRC / 'case.json').read_text())
    case = {
        'prepared_at': datetime.now(timezone.utc).isoformat(),
        'question': 'Does the renderer change the result the archived Astra runs produced, '
                    'with every message held byte-identical?',
        'replays': {
            'chapter': str(CHAPTER_SRC),
            'scene_ab': str(SCENE_SRC),
        },
        'campaign_commit': chapter_case['campaign_commit'],
        'campaign_repository': 'https://github.com/kostadis/campaigns',
        'generator_commit': subprocess.check_output(
            ['git', '-C', str(CG), 'rev-parse', 'HEAD'], text=True).strip(),
        'model': MODEL, 'claude_code_effort': EFFORT, 'claude_code_effort_source': EFFORT_SOURCE,
        'backend': BACKEND,
        'compared_against': {
            'model': chapter_case['model'],
            'reasoning_effort': chapter_case['reasoning_effort'],
            'backend': chapter_case['backend'],
        },
        'effort_note': 'The operator\'s ~/.claude/settings.json pins effortLevel=xhigh, so '
                       '--effort medium is sent explicitly. A run recording source '
                       '"inherited" would not be this experiment. Note that the adapter\'s '
                       'startup banner mis-renders any source string outside '
                       'explicit/environment/clamp as "inherited ... sent no override"; the '
                       'recorded identity, not the banner, is the record. See aborted/README.md.',
        'thinking_note': 'The Fable family runs adaptive thinking unconditionally; the '
                         'adapter\'s MAX_THINKING_TOKENS=0 is a no-op there. Astra\'s trace '
                         'behaviour under codex-cli is not equated with it.',
        'max_tokens_argument': MAX_TOKENS,
        'token_limit_note': 'Forwarded as CLAUDE_CODE_MAX_OUTPUT_TOKENS, which the CLI does '
                            'enforce as a ceiling. The Codex adapter accepted but ignored the '
                            'same argument, so this is one uncontrolled difference between '
                            'the two renderers rather than a matched setting.',
        'arms': list(ARMS), 'scene_arms': list(SCENE_ARMS),
        'scene_heading': scene_case['scene_heading'],
        'chapter_headings': chapter_case['scene_headings'],
        'input_sha256': manifest,
        'assignment_sha256': sha((ROOT / 'assignment.json').read_bytes()),
        'design': 'Three independent single-sample calls. Every system and user message is '
                  'byte-identical to the archived Astra run it replays. Renderer is the only '
                  'deliberate change.',
        'limits': 'One sample per arm; stochastic outputs; no exposed seed; no repeated trials. '
                  'A single pair of chapters cannot separate model quality from run-to-run '
                  'variance, and neither can a single A/B pair. Attestation is what the '
                  'adapter sent (--model / --effort), not a provider echo of what served the '
                  'request. The output ceiling differs in enforcement between the two '
                  'backends. Nothing here revalidates the production narration path.',
    }
    save_new(ROOT / 'case.json', json_text(case))
    verify(case)
    print(json_text({'status': 'prepared', 'frozen_files': len(manifest),
                     'chapter_user_words': len((ROOT / 'prompts/chapter_user.md').read_text().split()),
                     'scene_user_words': len((ROOT / 'prompts/scene_user.md').read_text().split())}))


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
           'backend': BACKEND, 'requested_model': MODEL,
           'requested_claude_code_effort': EFFORT,
           'requested_effort_source': EFFORT_SOURCE}
    save_new(target / 'run.json', json_text(run))
    sys.path.insert(0, str(CG))
    try:
        from campaignlib import make_client, call_api
        client = make_client(backend=BACKEND, model_override=MODEL,
                             claude_code_effort=EFFORT, claude_code_effort_source=EFFORT_SOURCE)
        response = call_api(client, (ROOT / system_path).read_text(),
                            (ROOT / user_path).read_text(), MODEL, max_tokens=MAX_TOKENS)
        save_new(target / 'response.md', response)
        run['response_sha256'] = sha(response.encode())
        identity = client.last_run_identity.as_dict()
        run['actual_identity'] = identity
        if (identity['model'] != MODEL
                or identity['claude_code_effort'] != EFFORT
                or identity['claude_code_effort_source'] != EFFORT_SOURCE
                or not identity['claude_code_effort_override']):
            raise ValueError('Actual selection differs from the experiment')
        verify(case)
        run['all_headings'] = re.findall(r'^#{1,6} .+$', response, re.M)
        if arm == 'chapter':
            # An H1 chapter title sits above the five H2 sections, so match H2 only —
            # the same check the archived chapter run made.
            run['headings'] = re.findall(r'^## (.+)$', response, re.M)
            expected = case['chapter_headings']
        else:
            run['headings'] = re.findall(r'^#{1,6} (.+)$', response, re.M)
            expected = [case['scene_heading']]
        if run['headings'] != expected:
            raise ValueError('Output headings differ from the fixed plan; raw response preserved')
        run['words'] = len(response.split())
        run['status'] = 'rendered'
    except BaseException as exc:
        run['status'] = 'failed'
        run['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        run['finished_at'] = datetime.now(timezone.utc).isoformat()
        (target / 'run.json').write_text(json_text(run))
    print(json_text({'arm': arm, 'status': run['status'], 'words': run['words'],
                     'actual_identity': run['actual_identity']}))


def metrics(text):
    text = re.sub(r'\A---\n.*?\n---\n', '', text, flags=re.S)
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text)
                  if p.strip() and not p.strip().startswith(('#', '---'))]
    quotes = [p for p in paragraphs if p.startswith(('"', '“', '‘'))]
    return {'words': len(text.split()), 'paragraphs': len(paragraphs),
            'median_paragraph_words': statistics.median(len(p.split()) for p in paragraphs),
            'quote_led_paragraphs': len(quotes),
            'quote_led_at_most_5_words': sum(len(p.split()) <= 5 for p in quotes)}


def _rendered(arm):
    run = json.loads((ROOT / arm / 'run.json').read_text())
    text = (ROOT / arm / 'response.md').read_text()
    if run['status'] != 'rendered' or sha(text.encode()) != run['response_sha256']:
        raise ValueError(f'No completed unchanged response for {arm}')
    return text


def _page(title, intro, body):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>'
            'body{max-width:1600px;margin:2rem auto;padding:0 1.5rem;background:#faf8f3;'
            'color:#292825;font:17px/1.55 system-ui,sans-serif}'
            'a{color:#285666}h1{line-height:1.2}'
            '.columns{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:1.5rem}'
            'article{min-width:0;background:#fff;padding:1.5rem;border:1px solid #ddd8cc}'
            '.prose{white-space:pre-wrap;overflow-wrap:anywhere;font:19px/1.65 Georgia,serif}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 system-ui,sans-serif}'
            'section{margin-top:3rem;scroll-margin-top:2rem}'
            'details{margin:1.5rem 0}summary{cursor:pointer}'
            '.note{background:#fff6e0;border:1px solid #e6d9b0;padding:1rem}'
            '</style></head><body>'
            f'<h1>{html.escape(title)}</h1>{intro}{body}</body></html>')


def reader():
    case = json.loads((ROOT / 'case.json').read_text())
    verify(case)
    assignment = json.loads((ROOT / 'assignment.json').read_text())
    texts = {
        'astra:chapter': (ROOT / 'reference/astra_chapter.md').read_text(),
        'astra:control': (ROOT / 'reference/astra_control.md').read_text(),
        'astra:composition': (ROOT / 'reference/astra_composition.md').read_text(),
        'fable:chapter': _rendered('chapter'),
        'fable:control': _rendered('control'),
        'fable:composition': _rendered('composition'),
        'historical:chapter': (ROOT / 'reference/historical_chapter.md').read_text(),
    }
    save_new(ROOT / 'metrics.json', json_text({k: metrics(v) for k, v in sorted(texts.items())}))

    def panel(label, text):
        return (f'<article><h3>Draft {html.escape(label)}</h3>'
                f'<div class="prose">{html.escape(text.strip())}</div></article>')

    scene_source = (SCENE_SRC / 'inputs/source.md').read_text()
    panes = ''.join(panel(label, texts[draft])
                    for label, draft in sorted(assignment['scene'].items()))
    body = (f'<section><div class="columns">{panes}</div>'
            f'<details><summary>Reviewed source extraction for this scene</summary>'
            f'<pre>{html.escape(scene_source)}</pre></details></section>')
    save_new(ROOT / 'scene_blind.html', _page(
        f'Blind read: {case["scene_heading"]}',
        '<p class="note">Four unedited single-scene drafts. Two renderers x two prompt arms, '
        'randomly labelled. Same source extraction, same POV plan, same examples. '
        'The label reveals nothing; <code>assignment.json</code> holds the key. '
        'Read first, then reveal.</p>', body))

    panes = ''.join(panel(label, texts[draft])
                    for label, draft in sorted(assignment['chapter'].items()))
    panes += panel('— the edited historical chapter (known baseline)', texts['historical:chapter'])
    save_new(ROOT / 'chapter_blind.html', _page(
        'Blind read: Chapter 51 — five scenes',
        '<p class="note">Two unedited generated chapters from identical messages, randomly '
        'labelled P and Q, beside the edited chapter that actually shipped. The baseline is '
        'openly labelled; its length and quote density identify it regardless.</p>',
        f'<section><div class="columns">{panes}</div></section>'))
    print(json_text({'status': 'built', 'metrics': 'metrics.json',
                     'readers': ['scene_blind.html', 'chapter_blind.html']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'render', 'reader'])
    parser.add_argument('arm', choices=sorted(ARMS), nargs='?')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    elif args.action == 'reader':
        reader()
    elif args.arm:
        render(args.arm)
    else:
        parser.error('render requires an arm')
