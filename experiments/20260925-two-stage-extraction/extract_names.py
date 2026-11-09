#!/usr/bin/env python
"""LangExtract proper-noun inventory over a campaign narrative, served by the DGX Spark.

Two things the stock library cannot do against this endpoint, both patched below:

1. vLLM serves qwen3.8-flash-next with thinking ON by default. The whole
   completion budget goes to the `reasoning` field and `content` comes back
   None. The only switch that works is `chat_template_kwargs:
   {"enable_thinking": false}` (`/no_think` is echoed verbatim and the trace
   still fires). LangExtract's OpenAI provider builds api_params from a
   hardcoded allowlist with no extra_body passthrough, so we wrap it.

2. Alignment is what we actually came for: `char_interval` is only populated
   when the extracted string is found in the source. We keep the ungrounded
   ones rather than dropping them -- they are the hallucination canary.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
import time

import langextract as lx
from langextract import factory
from langextract.providers import openai as lx_openai

# ---------------------------------------------------------------- patch (1)

_orig_build = lx_openai.OpenAILanguageModel._build_chat_completions_params


def _build_with_thinking_off(self, prompt, config=None):
    params = _orig_build(self, prompt, config)
    params["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    return params


lx_openai.OpenAILanguageModel._build_chat_completions_params = _build_with_thinking_off

# ---------------------------------------------------------------- task spec

PROMPT = """Extract every proper noun from the D&D campaign narrative below.

Use the exact text as it appears in the passage -- do not correct spelling, do
not expand abbreviations, do not normalise a name to a form you have seen
elsewhere. A misspelling in the source is itself the finding.

Extract only names that appear in THIS passage. Do not add names you know from
the Forgotten Realms but that are not written here. Do not repeat the names
used in the examples.

Classes:
  character - an individual person or being with a name
  deity     - a named god, demon lord, or object of worship
  location  - a named place, settlement, region, or structure
  faction   - a named group, clan, house, cult, or organisation
  creature  - a named species, race, or monster type
  item      - a named object, weapon, vessel, or artifact"""

# Canary names: deliberately NOT from this campaign. Anything from this block
# appearing in the output is example leakage, not extraction.
EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "Brother Elarion of the Silver Chalice knelt before the shrine of "
            "Tyr in Havenmoor, clutching the blade Dawnrender while a pack of "
            "gnolls circled the ruined keep."
        ),
        extractions=[
            lx.data.Extraction(
                extraction_class="character",
                extraction_text="Elarion",
                attributes={"note": "brother of the Silver Chalice"},
            ),
            lx.data.Extraction(
                extraction_class="faction",
                extraction_text="Silver Chalice",
                attributes={"note": "religious order"},
            ),
            lx.data.Extraction(
                extraction_class="deity",
                extraction_text="Tyr",
                attributes={"note": "god with a shrine in Havenmoor"},
            ),
            lx.data.Extraction(
                extraction_class="location",
                extraction_text="Havenmoor",
                attributes={"note": "settlement holding a shrine"},
            ),
            lx.data.Extraction(
                extraction_class="item",
                extraction_text="Dawnrender",
                attributes={"note": "blade"},
            ),
            lx.data.Extraction(
                extraction_class="creature",
                extraction_text="gnolls",
                attributes={"note": "pack circling the keep"},
            ),
        ],
    ),
]

CANARIES = {
    "elarion", "silver chalice", "tyr", "havenmoor", "dawnrender", "gnolls",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--base-url", default="http://192.168.1.121:8001/v1")
    ap.add_argument("--model-id", default="qwen3.8-flash-next")
    ap.add_argument("--max-char-buffer", type=int, default=1200)
    ap.add_argument("--max-workers", type=int, default=8)
    ap.add_argument("--batch-length", type=int, default=8)
    ap.add_argument("--extraction-passes", type=int, default=1)
    # When the source is a slice of a larger file, offsets come back relative
    # to the slice. Add the slice's start so every char_interval stays a valid
    # pointer into the ORIGINAL document -- the whole point of the grounding.
    ap.add_argument("--offset-base", type=int, default=0)
    args = ap.parse_args()

    text = args.source.read_text(encoding="utf-8")
    print(f"[source] {args.source}  {len(text):,} chars", file=sys.stderr)
    print(
        f"[spark]  {args.base_url}  model={args.model_id}  "
        f"buffer={args.max_char_buffer} workers={args.max_workers} "
        f"passes={args.extraction_passes}",
        file=sys.stderr,
    )

    # The provider MUST be named explicitly. langextract's router matches
    # model ids against vendor patterns, and providers/patterns.py:44 sends
    # anything matching r'^qwen' to Ollama -- which is every id this Spark has
    # ever served. `language_model_type=` does not override it (deprecated,
    # warns, then the router decides anyway).
    cfg = factory.ModelConfig(
        model_id=args.model_id,
        provider="OpenAILanguageModel",
        provider_kwargs={
            "base_url": args.base_url,
            "api_key": "EMPTY",  # vLLM ignores it, the SDK requires one
            "temperature": 0.0,
            "max_workers": args.max_workers,
        },
    )

    t0 = time.time()
    result = lx.extract(
        text_or_documents=text,
        prompt_description=PROMPT,
        examples=EXAMPLES,
        config=cfg,
        fence_output=False,
        use_schema_constraints=False,
        max_char_buffer=args.max_char_buffer,
        max_workers=args.max_workers,
        batch_length=args.batch_length,
        extraction_passes=args.extraction_passes,
    )
    elapsed = time.time() - t0

    rows = []
    for e in result.extractions:
        ci = e.char_interval
        rows.append(
            {
                "name": e.extraction_text,
                "class": e.extraction_class,
                "note": (e.attributes or {}).get("note"),
                "start": (ci.start_pos + args.offset_base) if ci else None,
                "end": (ci.end_pos + args.offset_base) if ci else None,
                "grounded": ci is not None,
                "alignment": getattr(e.alignment_status, "value", None),
            }
        )

    args.out.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )

    grounded = sum(r["grounded"] for r in rows)
    leaked = [r for r in rows if r["name"].strip().lower() in CANARIES]
    by_class = collections.Counter(r["class"] for r in rows)
    uniq = {r["name"].strip().lower() for r in rows}

    print(f"\n[done] {elapsed:,.1f}s", file=sys.stderr)
    print(f"  extractions : {len(rows):,}  ({len(uniq):,} unique surface forms)", file=sys.stderr)
    print(f"  grounded    : {grounded:,}  ungrounded: {len(rows) - grounded:,}", file=sys.stderr)
    print(f"  canary leaks: {len(leaked)}  {sorted({r['name'] for r in leaked})}", file=sys.stderr)
    print(f"  by class    : {dict(by_class)}", file=sys.stderr)
    print(f"  -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
