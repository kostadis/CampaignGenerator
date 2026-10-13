"""The one model step: play an NPC at a scene from what she could know.

Everything before this is deterministic and reviewed: who she is (:mod:`persona`),
what she could have witnessed (:mod:`horizon`), and which scene she must play. The
model only renders a short scene inside that structure, and what it writes is
checked afterwards by :mod:`leakcheck` and then by the GM. It decides nothing
that code or the GM could have decided.

This is the ONLY module of the package that talks to a model, and only through
``campaignlib`` (``client_from_args``, ``call_api``); retries are campaignlib's
job. ``cli.py`` reaches the model through :func:`play` so that it stays inside
the no-model guard (``tests/test_npc_agent_no_llm.py`` lists this module in
``MODEL_STEPS`` and nothing else).

The scene it is given is its ``####`` headline and nothing more. The rest of the
scene is the answer key a backtest compares against, so :func:`situation` never
includes it.
"""

from __future__ import annotations

from campaignlib import call_api, client_from_args
from campaignlib.api.client import add_backend_args, resolve_cli_model
from pipelines.npc_agent import corpus as corpus_mod
from pipelines.npc_agent.corpus import Corpus

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_MAX_TOKENS = 1500

SYSTEM_PROMPT = """You are playing {subject}, a non-player character in a tabletop role-playing campaign, at one scene.

You know only what is in the record you are given, which is everything {subject} could know. Do not use or hint at any event, person or fact that is not in it. If you lack something, act from character; do not invent things about other people.

Write what {subject} does and says in this scene, as the game master would run her. 150 to 300 words, in the present tense. Her actions are in the third person; her words are in quotation marks. Other characters appear only as brief prompts she reacts to. No preamble and no headings."""


def situation(corpus: Corpus, target_scene_id: str) -> str:
    """The scene to play: chapter title, scene title and its first beat's headline.

    Only the opening ``####`` headline is given. Everything after it is what
    happened, which a backtest holds back as the answer key. A scene that opens
    with a bullet rather than a headline has no headline to give, and says so
    rather than substituting a bullet.
    """
    scene = next((it for it in corpus.items() if it.item_id == target_scene_id and it.kind == corpus_mod.SCENE), None)
    if scene is None:
        raise KeyError(f"{target_scene_id}: not a scene in the summaries")
    chapter = next(ch for ch in corpus.chapters if ch.chapter == scene.chapter)
    bs = corpus_mod.beats(scene)
    first = bs[0].text if bs and bs[0].text.startswith("#### ") else ""
    lines = [f"# {chapter.title or f'Chapter {chapter.chapter}'}", "", f"## {scene.title}", ""]
    lines.append(first[len("#### "):].strip() if first else "(The summary gives no opening line for this scene.)")
    return "\n".join(lines) + "\n"


def build_prompt(subject: str, persona_md: str, horizon_md: str, situation_md: str) -> tuple[str, str]:
    """``(system, user)``; the user message is exactly the three inputs, in order."""
    system = SYSTEM_PROMPT.format(subject=subject)
    user = (f"## Who you are\n\n{persona_md.strip()}\n\n"
            f"## What you know\n\n{horizon_md.strip()}\n\n"
            f"## The scene\n\n{situation_md.strip()}\n")
    return system, user


REPLAY_SYSTEM = """You are playing {subject}, a non-player character in a tabletop role-playing campaign, at one moment of a scene.

You know only what is in the record you are given and in your private knowledge, which together are everything {subject} could know. Do not use or hint at any event, person or fact that is not in them. If you lack something, act from character; do not invent things about other people.

The scene so far is shown, including what you already said and did. Answer only the moment under "Now": what {subject} says and does next, as the game master would run her. 40 to 150 words, in the present tense. Her actions are in the third person; her words are in quotation marks. Do not speak for other characters. No preamble and no headings."""

FORWARD_SYSTEM = """You are playing {subject}, a non-player character in a tabletop role-playing campaign, between sessions.

You know only what is in the record you are given and in your private knowledge, which together are everything {subject} could know. Do not use or hint at any event, person or fact that is not in them.

Off-screen, {subject} acts on what she knows and wants. Propose 1 to 3 things she does before she next meets the party. Each is something she does, decides or arranges, not a thing that happens to her, with one line on why. Reply with JSON only, no other text: [{{"move": "...", "why": "..."}}]"""


def build_turn_prompt(subject: str, persona_md: str, horizon_md: str, sheet_md: str, situation_md: str,
                      so_far_md: str, now_md: str) -> tuple[str, str]:
    """``(system, user)`` for one turn of a replay; the user message is these six inputs, in order."""
    system = REPLAY_SYSTEM.format(subject=subject)
    user = (f"## Who you are\n\n{persona_md.strip()}\n\n"
            f"## What you know\n\n{horizon_md.strip()}\n\n"
            f"## Your private knowledge\n\n{sheet_md.strip() or '(nothing)'}\n\n"
            f"## The scene\n\n{situation_md.strip()}\n\n"
            f"## So far in this scene\n\n{so_far_md.strip()}\n\n"
            f"## Now\n\n{now_md.strip()}\n")
    return system, user


def build_forward_prompt(subject: str, persona_md: str, horizon_md: str, sheet_md: str,
                         standing_md: str) -> tuple[str, str]:
    """``(system, user)`` for a forward turn; the GM's plan is never an input."""
    system = FORWARD_SYSTEM.format(subject=subject)
    user = (f"## Who you are\n\n{persona_md.strip()}\n\n"
            f"## What you know\n\n{horizon_md.strip()}\n\n"
            f"## Your private knowledge\n\n{sheet_md.strip() or '(nothing)'}\n\n"
            f"## Where things stand\n\n{standing_md.strip() or '(nothing)'}\n")
    return system, user


def add_model_args(parser) -> None:
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"default: {DEFAULT_MODEL}")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help=f"default: {DEFAULT_MAX_TOKENS}")
    add_backend_args(parser)


def backend_name(args) -> str:
    """The backend a call would use, for the run record."""
    return resolve_cli_model(args, legacy_default=None).backend


def play(args, system: str, user: str) -> str:
    """One model call; the only one in the package."""
    client = client_from_args(args)
    return call_api(client, system, user, args.model, max_tokens=args.max_tokens)
