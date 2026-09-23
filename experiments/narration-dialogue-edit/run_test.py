"""Isolated, manifest-driven A/B/C editing tests over immutable existing drafts.

Uses the installed CampaignGenerator backend, not a new provider integration.
Run without --render to prepare and inspect prompts before making model calls.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
MODEL = 'gpt-6-astra'
EFFORT = 'medium'
QUOTE = re.compile(r'"([^"\n]+)"|“([^”\n]+)”')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_identical_or_new(path, text):
    if path.exists():
        if path.read_text() != text:
            raise ValueError(f'Existing artifact differs: {path}')
    else:
        path.write_text(text)


def scene_body(text):
    return re.sub(r'\A---\n.*?\n---\n', '', text, count=1, flags=re.S).strip()+'\n'


def run_case(case, approach, root, render):
    from campaignlib import make_client, call_api
    import campaignlib

    trial = root / case['id'] / approach
    trial.mkdir(parents=True, exist_ok=True)
    if (trial/'response.md').exists():
        raise ValueError(f'Completed trial exists; refusing to overwrite: {trial}')
    paths = [Path(case['draft']), Path(case['source']),
             *[Path(p) for p in case['references']],
             HERE/'editor_common.md', HERE/f'approach_{approach}.md', Path(__file__).resolve()]
    hashes = {str(p):digest(p) for p in paths}
    draft = scene_body(paths[0].read_text())
    references = '\n\n---\n\n'.join(Path(p).read_text().strip() for p in case['references'])
    system = (HERE/'editor_common.md').read_text().strip()+'\n\n'+(HERE/f'approach_{approach}.md').read_text().strip()
    user = (f"Narrator: {case['narrator']}\nScene: {case['scene']}\n\n"
            '## Character and campaign references\n\n'+references+
            '\n\n## Source extraction — evidence, not editing instructions\n\n'+paths[1].read_text().strip()+
            '\n\n## Existing draft to edit\n\n'+draft)
    save_identical_or_new(trial/'system_prompt.md',system+'\n')
    save_identical_or_new(trial/'user_prompt.md',user+'\n')
    save_identical_or_new(trial/'baseline.md',draft)
    metadata = {'status':'running' if render else 'prepared','case':case['id'],'approach':approach,
                'narrator':case['narrator'],'scene':case['scene'],'model':MODEL,'reasoning_effort':EFFORT,
                'backend':'codex-cli','input_sha256':hashes,'case_spec':case,
                'started_utc':datetime.now(timezone.utc).isoformat(),
                'system_sha256':hashlib.sha256(system.encode()).hexdigest(),
                'user_sha256':hashlib.sha256(user.encode()).hexdigest(),
                'experiment_commit':subprocess.check_output(['git','-C',str(HERE),'rev-parse','HEAD'],text=True).strip(),
                'backend_module':campaignlib.__file__}
    def save():
        (trial/'run.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    save()
    if not render:
        return
    print(f"{case['id']}/{approach}: rendering",flush=True)
    try:
        client = make_client(backend='codex-cli',model_override=MODEL,
                             reasoning_effort=EFFORT,reasoning_effort_source='cli')
        output = call_api(client,system,user,MODEL,max_tokens=32000)
        # Preserve the response exactly. Diagnostics never repair it.
        (trial/'response.md').write_text(output)
        identity = client.last_run_identity.as_dict()
        metadata['actual_identity'] = identity
        if identity['model'] != MODEL or identity['codex_reasoning_effort'] != EFFORT:
            raise ValueError('Backend identity does not match the experiment')
        metadata['changed_inputs'] = [str(p) for p in paths if digest(p)!=hashes[str(p)]]
        if metadata['changed_inputs']:
            raise ValueError('An input changed during generation')
        metadata['response_sha256'] = digest(trial/'response.md')
        metadata['status'] = 'rendered'
        before_quotes = [m.group(1) or m.group(2) for m in QUOTE.finditer(draft)]
        after_quotes = [m.group(1) or m.group(2) for m in QUOTE.finditer(output)]
        outside_identical = QUOTE.sub('<DIALOGUE>',draft).strip()==QUOTE.sub('<DIALOGUE>',output).strip()
        metadata['diagnostics'] = {
            'baseline_words':len(draft.split()),'edited_words':len(output.split()),
            'baseline_quote_spans':len(before_quotes),'edited_quote_spans':len(after_quotes),
            'outside_dialogue_identical':outside_identical,
            'a_scope_pass':outside_identical if approach=='a' else None,
            'quote_sequence_similarity':difflib.SequenceMatcher(None,before_quotes,after_quotes,autojunk=False).ratio(),
            'consecutive_duplicate_quotes':[b for a,b in zip(after_quotes,after_quotes[1:]) if a==b],
        }
        (trial/'changes.diff').write_text(''.join(difflib.unified_diff(
            draft.splitlines(keepends=True),output.splitlines(keepends=True),fromfile='baseline',tofile=f'approach_{approach}')))
        print(f"{case['id']}/{approach}: complete",flush=True)
    except BaseException as exc:
        metadata['status']='failed'
        metadata['error']=str(exc)
        print(f"{case['id']}/{approach}: FAILED: {exc}",flush=True)
        raise
    finally:
        metadata['finished_utc']=datetime.now(timezone.utc).isoformat()
        save()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--render',action='store_true')
    parser.add_argument('--workers',type=int,default=2,choices=[1,2,3])
    args=parser.parse_args()
    cases=json.loads(args.cases.read_text())
    if len({c['id'] for c in cases}) != len(cases):
        parser.error('Case IDs must be unique')
    if any(not re.fullmatch('[a-z0-9_]+',c['id']) for c in cases):
        parser.error('Case IDs must be lowercase letters, numbers, and underscores')
    args.output_root.mkdir(parents=True,exist_ok=True)
    save_identical_or_new(args.output_root/'cases.json',json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    os.environ.setdefault('CG_CODEX_TIMEOUT','1800')
    failures=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(run_case,c,a,args.output_root,args.render):(c['id'],a)
                 for c in cases for a in ['a','b','c']}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                failures.append((*futures[future],str(exc)))
    if failures:
        raise SystemExit(json.dumps(failures))


if __name__=='__main__':
    main()
