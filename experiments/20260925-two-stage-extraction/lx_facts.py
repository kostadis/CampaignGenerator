#!/usr/bin/env python
"""Head-to-head: langextract vs the ensemble's own extract_facts, matched.

Controls, so the thing being measured is the HARNESS and not the Spark:

  same model      qwen3.8-flash-next, same endpoint
  same prompt     config/agents/extract_facts.md, verbatim, as prompt_description
  same chunk size 15,000 chars -- the ensemble's `large` lens
  same schema     extraction_class = fact type, extraction_text = source_quote
                  (the field that earns a char_interval), attributes = entity+fact

So this is langextract's single pass against the ensemble's single `large` pass.
The ensemble's production config is the 5-lens union, which is a separate axis
reported alongside rather than conflated with this one.

Both patches from extract_names.py still apply: the thinking kwarg has no
supported route through the provider, and the router must be overridden or
r'^qwen' sends the whole run to Ollama.
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

_orig_build = lx_openai.OpenAILanguageModel._build_chat_completions_params


def _build_with_thinking_off(self, prompt, config=None):
    params = _orig_build(self, prompt, config)
    params["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    return params


lx_openai.OpenAILanguageModel._build_chat_completions_params = _build_with_thinking_off

PROMPT_PATH = pathlib.Path(
    "/home/kostadis/src/CampaignGenerator/config/agents/extract_facts.md"
)

# The ensemble prompt's own illustrative rows, restated in langextract's shape.
# extraction_text is the source_quote, because that is the field langextract
# aligns -- putting the synthesised `fact` there would make every row
# ungrounded by construction and rig the comparison.
EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "Lyra slipped out the south gate and made for Ashwood. The vote came "
            "down five to three. When they opened the strongbox the seal was gone."
        ),
        extractions=[
            lx.data.Extraction(
                extraction_class="npc",
                extraction_text="Lyra slipped out the south gate and made for Ashwood",
                attributes={
                    "entity": "Lyra Vance",
                    "fact": "Lyra Vance fled toward the Ashwood ruins.",
                },
            ),
            lx.data.Extraction(
                extraction_class="event",
                extraction_text="The vote came down five to three",
                attributes={
                    "entity": "council vote",
                    "fact": "The council voted 5-3 to exile the Vance family.",
                },
            ),
            lx.data.Extraction(
                extraction_class="thread",
                extraction_text="the seal was gone",
                attributes={
                    "entity": "missing seal",
                    "fact": "The merchant's seal taken from the vault has not been recovered.",
                },
            ),
        ],
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--base-url", default="http://192.168.1.121:8001/v1")
    ap.add_argument("--model-id", default="qwen3.8-flash-next")
    ap.add_argument("--max-char-buffer", type=int, default=15000)
    ap.add_argument("--max-workers", type=int, default=8)
    ap.add_argument("--extraction-passes", type=int, default=1)
    args = ap.parse_args()

    text = args.chapter.read_text(encoding="utf-8")
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    cfg = factory.ModelConfig(
        model_id=args.model_id,
        provider="OpenAILanguageModel",
        provider_kwargs={
            "base_url": args.base_url,
            "api_key": "EMPTY",
            "temperature": 0.0,
            "max_workers": args.max_workers,
        },
    )

    t0 = time.time()
    result = lx.extract(
        text_or_documents=text,
        prompt_description=prompt,
        examples=EXAMPLES,
        config=cfg,
        fence_output=False,
        use_schema_constraints=False,
        max_char_buffer=args.max_char_buffer,
        max_workers=args.max_workers,
        batch_length=args.max_workers,
        extraction_passes=args.extraction_passes,
    )
    elapsed = time.time() - t0

    rows = []
    for e in result.extractions:
        ci = e.char_interval
        attrs = e.attributes or {}
        rows.append(
            {
                "type": e.extraction_class,
                "subject": attrs.get("entity"),
                "fact": attrs.get("fact"),
                "source_quote": e.extraction_text,
                "quote_offset": ci.start_pos if ci else None,
                "grounded": ci is not None,
                "alignment": getattr(e.alignment_status, "value", None),
            }
        )

    args.out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    grounded = sum(r["grounded"] for r in rows)
    has_fact = sum(1 for r in rows if r["fact"])
    print(f"[langextract] {args.chapter.name}  {len(text):,} chars  {elapsed:,.1f}s")
    print(f"  rows        : {len(rows):,}")
    print(f"  grounded    : {grounded:,}  ({100*grounded/max(len(rows),1):.1f}%)")
    print(f"  carry a fact: {has_fact:,}  ({100*has_fact/max(len(rows),1):.1f}%)")
    print(f"  types       : {dict(collections.Counter(r['type'] for r in rows))}")
    print(f"  alignment   : {dict(collections.Counter(r['alignment'] for r in rows))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
