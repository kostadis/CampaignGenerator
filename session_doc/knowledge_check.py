"""Post-narration check: names the party has no shared record of (#223, A.3).

This is the OTHER half of #223, and it is a different bug from the quote
guard that fixed defects A/B. That one stops the pipeline rewriting what
somebody actually said. This one flags names the narration introduces into
*prose* that appear nowhere in the campaign's shared record — module knowledge
the model already has, registry alias expansions, or ``--reflections`` context
bleeding into a narrator's head.

The two are orthogonal. The Phandalin ch.47 finding that motivated this passed
the quote guard cleanly: the scene extractions say ``Aldus`` fifteen times and
never ``Aldus Hern``, the bible has neither ``Aldus`` nor ``Hern``, and the
narration says ``Aldus Hern`` nine times — a surname nobody at the table ever
spoke, introduced in prose by a registry alias expansion.

## Why this is computable without a schema change

The GM's assertion is the whole trick:

    Everything in the campaign bible is known to the entire party.

That makes the bible an **allowlist**. It is emphatically NOT a denylist — it
is a narrative document, not a census, so plenty of NPCs the party knows well
never appear in it (Phandalin's registry has 119 NPCs absent from the bible,
including shopkeepers the party has dealt with for thirty sessions). Union the
bible with the session's own scene extractions — anyone on stage is in the
source text by definition — and what is left over is short enough to read.
Measured on Phandalin ch.47: 212 candidates, 8 flagged.

So this **warns**. It never edits, and it never gates. Suppressing a name for
being missing from a narrative document would silently delete NPCs the party
has known for years, which is a worse failure than the one being caught: a
leaked name is visible in the output, a suppressed one is not.

It also checks the OUTPUT rather than gating an input, which is what makes it
channel-agnostic. A registry-side gate would miss a name that arrived via
``--reflections`` injecting ``world_state.md``; this catches it wherever it
came from.
"""

import re

from campaignlib import strip_protected_spans

# A candidate is a capitalised word, optionally followed by a second one (with
# an intervening "of"/"the" allowed, so "Lords of Waterdeep" survives as a
# unit). Deliberately crude: the allowlist does the real work, and a candidate
# that is already known costs nothing.
_CANDIDATE_RE = re.compile(
    r"\b[A-Z][a-z]{2,}(?:\s+(?:of\s+|the\s+)?[A-Z][a-z]{2,})?\b"
)

_HEADING_RE = re.compile(r"(?m)^#.*$")
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)

_SENTENCE_END = ".!?\n"


def _is_sentence_initial(text: str, start: int) -> bool:
    i = start - 1
    while i >= 0 and text[i] in " \t>-*_":
        i -= 1
    return i < 0 or text[i] in _SENTENCE_END


def extract_candidate_names(narration: str) -> dict[str, bool]:
    """Capitalised names in NARRATION PROSE → ``True`` if EVERY occurrence of
    that name starts a sentence.

    Quoted and italic spans are removed first: a speaker may call anyone
    anything, and #223 established that what is inside quotation marks is a
    record rather than the pipeline's prose. (A *fabricated* quote is a real
    problem, but it is ``sd_verify_quotes``'s, not this check's.) Headings and
    YAML frontmatter go too — ``assemble.py`` mints those.
    """
    prose = _FRONTMATTER_RE.sub("", narration)
    prose = _HEADING_RE.sub("", prose)
    # Replace with a TERMINATOR, not a space. A removed quote is a complete
    # utterance, and blanking it merges the words either side into one
    # sentence: `Soma said, "..." Then, "..."` collapsed to `Soma said,   Then,`,
    # which promoted "Then" to a mid-sentence capital and made every subsequent
    # `Then <Name>` look like a name.
    prose = strip_protected_spans(prose, ". ")

    out: dict[str, bool] = {}
    for m in _CANDIDATE_RE.finditer(prose):
        initial = _is_sentence_initial(prose, m.start())
        name = m.group(0)
        out[name] = out.get(name, True) and initial
    return out


def find_unknown_names(narration: str, known_texts) -> list[str]:
    """Names in ``narration``'s prose that appear in none of ``known_texts``.

    ``known_texts`` is what the party is assumed to share: the campaign bible
    (per the GM's assertion) plus this session's own scene extractions. Match
    is whole-word and case-insensitive; a name is known if ANY known text
    carries it.

    Returns a sorted list. Empty means nothing to look at.
    """
    candidates = extract_candidate_names(narration)
    if not candidates:
        return []
    corpus = "\n".join(t for t in known_texts if t)

    def known(term: str) -> bool:
        return bool(re.search(r"\b" + re.escape(term) + r"\b", corpus, re.IGNORECASE))

    unknown = []
    for name, always_initial in candidates.items():
        if known(name):
            continue
        # A two-word candidate that ONLY ever starts a sentence, and whose tail
        # is already known, is a sentence opener glued to a known name — "Then
        # Aldus", "Said House", "For Meliamne". Dropping those costs no recall,
        # because a genuinely leaked two-word name has an UNKNOWN tail
        # ("Kazneporium Ketternopappux"). Bare single words are never dropped
        # this way: a leak that only ever appears sentence-initially still has
        # to be reported, and a few ordinary words slipping through ("Nostalgia")
        # is the correct trade for a warning whose whole job is not missing one.
        if always_initial and " " in name and known(name.split(None, 1)[1]):
            continue
        unknown.append(name)
    return sorted(unknown)


def format_warning(scene_label: str, unknown: list[str]) -> str:
    """Render the stderr warning for one scene. Empty string when clean."""
    if not unknown:
        return ""
    return (
        f"Warning: {scene_label} — {len(unknown)} name(s) in narration prose appear "
        f"in neither the known-lore documents nor this session's scene extractions:\n"
        + "".join(f"    - {n}\n" for n in unknown)
        + "  -> the party may have no shared record of these. Check for module "
        "knowledge, a registry alias expansion, or --reflections context leaking "
        "into the narrator (#223 A.3). This is a warning only; nothing was changed."
    )
