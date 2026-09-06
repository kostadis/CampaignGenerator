"""Three plans for a scene nobody can narrate.

When Filter B leaves a scene with no eligible narrator — a stretch of pure GM
narration, or a scene the party's characters sat out — there is no honest
first-person answer. The planner does not pick one anyway. It writes three
plans that differ in how that scene is *treated* and lets the GM choose.

**Constructed, not sampled.** Three independent planner runs on the session
behind #385 produced a byte-identical narrator distribution while rewording
every title, so re-running the planner diversifies nothing. Instead one call
plans the coverable scenes, a second small call proposes three treatments for
the disputed one, and the three files are assembled here deterministically.
Two model calls rather than three full plans, and the alternates are
comparable because everything else is identical.

**The choice is the absence of plan.md.** The alternates are written as
``plan.a.md`` / ``plan.b.md`` / ``plan.c.md`` and no ``plan.md``, so the gate
that already refuses to narrate without one (``server/routers/scene_editor.py``)
does the blocking. ``sd_plan --choose b`` writes the pick, and is equivalent to
``cp plan.b.md plan.md`` — the GM is never trapped in a UI (Constitution IX).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The three alternates' file suffixes, and the values ``--choose`` accepts.
ALTERNATE_KEYS = ("a", "b", "c")

#: `## Scene 3` / `## Section 3` — the same headings ``parse_plan`` splits on.
_BLOCK_RE = re.compile(r"(?m)^## (?:Section|Scene) \d+[^\n]*$")


@dataclass(frozen=True)
class Treatment:
    """One proposed way to handle a scene no character can narrate."""

    label: str
    rationale: str
    body: str

    def render(self, header: str) -> str:
        return f"{header}\n{self.body.strip()}\n"


def split_plan_blocks(plan_text: str) -> list[tuple[str, str]]:
    """``[(header, body), …]`` in order, preserving the headers as written.

    ``parse_plan`` throws the headers away because it only needs the fields.
    Assembling an alternate needs the document back, so this keeps them.
    """
    headers = list(_BLOCK_RE.finditer(plan_text))
    blocks: list[tuple[str, str]] = []
    for i, m in enumerate(headers):
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(plan_text)
        blocks.append((m.group(0), plan_text[start:end].strip("\n")))
    return blocks


def plan_preamble(plan_text: str) -> str:
    """Anything before the first scene header.

    The prompt says "no preamble", but that is an instruction, not a guarantee.
    Dropping it would make the alternates path lose content the ordinary path
    preserves byte-for-byte, so the two would not round-trip the same document.
    """
    first = _BLOCK_RE.search(plan_text)
    return plan_text[: first.start()] if first else ""


def parse_treatments(text: str) -> list[Treatment]:
    """Read the treatment call's output.

    Expected shape, one per treatment::

        ## Treatment A
        label: fold into the previous scene
        rationale: nobody speaks here, and the beat belongs to what precedes it
        narrator: Vukradin
        chunks: 5
        scene: Three Days on the Road
        treatment: absorbed-into "The Dead Drop"
        pov: reported by the scene he does narrate
        focus: the road as the gap between two investigations

    ``label`` and ``rationale`` are for the GM's choice and are stripped from
    the plan body; everything else is the replacement block.
    """
    out: list[Treatment] = []
    parts = re.split(r"(?m)^## Treatment [A-Za-z]+[^\n]*$", text)
    for part in parts[1:]:
        label = rationale = ""
        body: list[str] = []
        for line in part.strip().splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("label:"):
                label = stripped.split(":", 1)[1].strip()
            elif stripped.lower().startswith("rationale:"):
                rationale = stripped.split(":", 1)[1].strip()
            elif stripped:
                body.append(stripped)
        # A block without `narrator:` and `chunks:` is one `parse_plan` will
        # drop, which shifts every later scene onto the wrong entry. Rejecting
        # it here turns a silent off-by-one into a loud parse failure.
        joined = "\n".join(body)
        has = lambda k: any(  # noqa: E731
            ln.lower().startswith(k) for ln in body
        )
        if body and has("narrator:") and has("chunks:"):
            out.append(Treatment(label=label or "(unlabelled)",
                                 rationale=rationale, body=joined))
    return out


def assemble_alternates(
    plan_text: str,
    *,
    scene_indexes: list[int],
    treatments: list[Treatment],
    uncoverable_names: list[str],
) -> dict[str, str]:
    """``{"a": plan_text, "b": …, "c": …}`` — identical but for the disputed scene.

    ``scene_indexes`` are zero-based positions of the uncoverable scenes in the
    plan. Each alternate replaces those blocks with one treatment's body and
    carries a header naming what was disputed and how this plan answers it, so
    the GM can choose without opening the extractions.

    A treatment that folds the scene into a neighbour necessarily changes that
    neighbour's entry too; the invariant is therefore "identical except the
    uncoverable scene and any scene a treatment explicitly absorbs it into",
    not "identical except one block".
    """
    blocks = split_plan_blocks(plan_text)
    alternates: dict[str, str] = {}
    for key, treatment in zip(ALTERNATE_KEYS, treatments):
        rebuilt: list[str] = []
        for i, (header, body) in enumerate(blocks):
            if i in scene_indexes:
                rebuilt.append(treatment.render(header))
            else:
                rebuilt.append(f"{header}\n{body}\n")
        preamble = (
            plan_preamble(plan_text)
            + f"<!-- plan {key.upper()} — treatment: {treatment.label}\n"
            f"     uncoverable scene(s): {', '.join(uncoverable_names)}\n"
            f"     no player character speaks in "
            f"{'them' if len(uncoverable_names) > 1 else 'it'}, so no honest "
            f"first-person narrator exists.\n"
            f"     rationale: {treatment.rationale or '(none given)'}\n"
            f"     Choose one: sd_plan --choose {key}  (or cp plan.{key}.md plan.md) -->\n\n"
        )
        alternates[key] = preamble + "\n".join(rebuilt)
    return alternates
