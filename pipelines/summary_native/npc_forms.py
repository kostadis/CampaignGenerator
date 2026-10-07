"""Name forms for NPC linking (spec 032 T013, research R2, R4, R5).

A *form* is an exact string that names an NPC: a heading in the NPC's corpus dossier,
or the registry entity's exact ``name`` / ``aliases`` when that entity is of type ``npc``.
Nothing is inferred: no first-token alias, no casefolded lookup, no similarity.

Three things decide whether a form may be linked:

* **ambiguous** - the exact string belongs to more than one ``(type, canonical)`` across
  the registry and every corpus heading of every category. Withheld, never rulable.
* **generic** - a single token found (casefolded) in the packaged word list. Withheld
  unless ``canon.yaml link_rulings`` says ``safe``; ``never`` keeps it withheld.
* otherwise **linkable**.

Ambiguous beats generic. ``explicit_aliases_by_type`` is not used: it casefolds and lets
the first entity win a collision, which is the silent decision FR-003 forbids.

No model call (guarded by ``tests/test_summary_native_no_llm.py``).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pipelines.summary_native import schema

WORDLIST_PATH = Path(__file__).resolve().parent / "data" / "english_words.txt"

LINKABLE = "linkable"
AMBIGUOUS = "ambiguous"
GENERIC = "generic"
GENERIC_SAFE = "generic-safe"
GENERIC_NEVER = "generic-never"
LINKABLE_STATUSES = frozenset({LINKABLE, GENERIC_SAFE})

Owner = tuple[str, str]  # (type, canonical)
PLAYER_CHARACTER_EXCLUSION = "player character (players.yaml)"


class LinkRefusal(Exception):
    """npc-link cannot proceed (CLI exit 2); the message is user-facing."""


@dataclass(frozen=True)
class NameForm:
    text: str
    owner: Owner | None  # set only when unambiguous
    sources: tuple[str, ...]  # "heading" and/or "registry"
    status: str
    collides_with: tuple[Owner, ...] = ()
    #: corpus stems of the NPC dossiers that carry this form (empty: a registry NPC with no dossier)
    stems: tuple[str, ...] = ()


@dataclass(frozen=True)
class CorpusDossier:
    stem: str
    type: str
    subject: str
    headings: tuple[str, ...]


def load_wordlist(path: Path | None = None) -> tuple[frozenset[str], str]:
    """The packaged word list and its sha256 (recorded with every link run, FR-003b)."""
    p = Path(path) if path is not None else WORDLIST_PATH
    raw = p.read_bytes()
    words = frozenset(w for w in raw.decode("utf-8").split("\n") if w)
    return words, hashlib.sha256(raw).hexdigest()


def read_corpus_dossiers(range_dir: Path) -> list[CorpusDossier]:
    """Every dossier the 031 build wrote, with the stem taken from its file name.

    The stem is read from the built corpus, never recomputed: a collision suffix needs
    the whole set of subjects, which only the build had.
    """
    out: list[CorpusDossier] = []
    ddir = Path(range_dir) / "dossiers"
    if not ddir.is_dir():
        return out
    for p in sorted(ddir.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
        meta = (yaml.safe_load(m.group(1)) if m else None) or {}
        out.append(
            CorpusDossier(
                stem=p.stem,
                type=str(meta.get("type", "")),
                subject=str(meta.get("subject", "")),
                headings=tuple(str(h) for h in (meta.get("headings") or [])),
            )
        )
    return out


def is_generic_token(form: str, wordlist) -> bool:
    return len(form.split()) == 1 and form.casefold() in wordlist


def _compile(forms) -> re.Pattern[str] | None:
    ordered = sorted(set(forms), key=lambda f: (-len(f), f))
    if not ordered:
        return None
    alt = "|".join(re.escape(f) for f in ordered)
    return re.compile(rf"(?<!\w)(?:{alt})(?!\w)")


def _fmt_owner(o: Owner) -> str:
    return f"{o[0]} {o[1]!r}"


@dataclass
class FormIndex:
    """Every NPC name form of one run, its status, and the single combined matcher."""

    forms: dict[str, NameForm]
    stem_forms: dict[str, tuple[str, ...]]  # stem -> form texts (any status)
    registry_scopes: dict[str, str]  # registry npc canonical -> scope
    registry_only: dict[str, tuple[str, ...]]  # registry npc canonical with no dossier -> form texts
    rulings: dict[str, str]
    ruled_ambiguity: dict[str, tuple[Owner, ...]] = field(default_factory=dict)
    #: registry npc canonical -> players.yaml player names whose ``plays`` resolves to it
    player_characters: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: ``plays`` names that resolve to no registry entity (reported, never guessed at)
    unresolved_players: tuple[tuple[str, str], ...] = ()  # (player, character)
    pattern: re.Pattern[str] | None = None

    # ── queries ────────────────────────────────────────────────────────────

    def forms_for(self, stem: str) -> tuple[NameForm, ...]:
        """Every form of one NPC dossier, any status, sorted by text."""
        return tuple(self.forms[t] for t in self.stem_forms.get(stem, ()))

    def linkable_for(self, stem: str) -> tuple[NameForm, ...]:
        return tuple(f for f in self.forms_for(stem) if f.status in LINKABLE_STATUSES)

    def withheld(self) -> tuple[NameForm, ...]:
        """Forms that will not be linked: ambiguous, generic unruled, generic ruled never."""
        return tuple(
            f for _, f in sorted(self.forms.items()) if f.status not in LINKABLE_STATUSES
        )

    def global_status(self, subject: str) -> tuple[bool, str | None]:
        """R1: ``(global, exclusion)`` for an NPC dossier's subject.

        Global means registry ``npc`` + ``persistent`` and not a player character.
        """
        scope = self.registry_scopes.get(subject)
        if scope is None:
            return False, "not in registry"
        if subject in self.player_characters:
            return False, PLAYER_CHARACTER_EXCLUSION
        if scope != "persistent":
            return False, f"registry scope {scope}: local (deferred to the local-NPC feature)"
        return True, None

    def match_line(self, line: str) -> list[tuple[int, int, NameForm]]:
        """Non-overlapping matches of every known form (longest first at a position).

        A form inside a longer form is not a separate occurrence: ``Sarith`` inside
        ``Sarith Kzekarit`` belongs to the longer name.
        """
        if self.pattern is None:
            return []
        return [(m.start(), m.end(), self.forms[m.group(0)]) for m in self.pattern.finditer(line)]

    def ruling_findings(self, occurring_forms) -> list[dict]:
        """``stale-link-ruling`` and ``link-ruling-unneeded`` findings, sorted by form.

        ``occurring_forms`` is the set of ruled forms found anywhere in the range
        (scene text, moment text, entity headings).
        """
        occurring = set(occurring_forms)
        out: list[dict] = []
        for form in sorted(self.rulings):
            ruling = self.rulings[form]
            if form not in occurring:
                out.append(
                    {
                        "code": schema.STALE_LINK_RULING,
                        "form": form,
                        "ruling": ruling,
                        "message": f"link ruling {ruling!r} for {form!r}: the form occurs nowhere in the range",
                    }
                )
            nf = self.forms.get(form)
            if nf is None or nf.status not in (GENERIC_SAFE, GENERIC_NEVER):
                out.append(
                    {
                        "code": schema.LINK_RULING_UNNEEDED,
                        "form": form,
                        "ruling": ruling,
                        "message": (
                            f"link ruling {ruling!r} for {form!r}: the form is neither generic "
                            "nor ambiguous in this run, so the ruling has no effect"
                        ),
                    }
                )
        return out


def build_form_index(registry, corpus_dossiers, wordlist, rulings, players=None) -> FormIndex:
    """Build the cross-type ambiguity index and the NPC form table.

    ``registry`` may be None (a campaign with no registry: forms are headings only).
    ``rulings`` is ``duplicates.Rulings`` or a plain ``{form: safe|never}`` dict.
    ``players`` is a ``campaignlib.players_config.PlayersConfig`` or None (no players.yaml:
    no declared PCs, nothing excluded). Each ``plays`` name is resolved to a registry
    entity by exact name or exact alias; one that resolves to none is recorded, not guessed.
    Raises ``LinkRefusal`` when a ruling names a form that is ambiguous in this run.
    """
    link_rulings: dict[str, str] = dict(getattr(rulings, "link_rulings", rulings) or {})
    dossiers = list(corpus_dossiers)

    owners: dict[str, set[Owner]] = {}

    def own(text: str, owner: Owner) -> None:
        if text:
            owners.setdefault(text, set()).add(owner)

    reg_npc_forms: dict[str, list[str]] = {}
    registry_scopes: dict[str, str] = {}
    if registry is not None:
        for e in registry.entities:
            names = [e.name, *e.aliases]
            for s in names:
                own(s, (e.type, e.name))
            if e.type == "npc":
                registry_scopes[e.name] = e.scope
                reg_npc_forms[e.name] = [s for s in names if s]
    for d in dossiers:
        own(d.subject, (d.type, d.subject))
        for h in d.headings:
            own(h, (d.type, d.subject))

    # Forms of NPCs: dossier headings, plus registry name/aliases of the matching npc entity.
    form_stems: dict[str, set[str]] = {}
    form_sources: dict[str, set[str]] = {}
    stem_forms: dict[str, set[str]] = {}
    dossier_subjects = set()
    for d in dossiers:
        if d.type != "npc":
            continue
        dossier_subjects.add(d.subject)
        texts = set(d.headings)
        sources = {h: {"heading"} for h in d.headings}
        if d.subject in reg_npc_forms:
            for s in reg_npc_forms[d.subject]:
                texts.add(s)
                sources.setdefault(s, set()).add("registry")
        for t in texts:
            form_stems.setdefault(t, set()).add(d.stem)
            form_sources.setdefault(t, set()).update(sources[t])
            stem_forms.setdefault(d.stem, set()).add(t)
    registry_only: dict[str, tuple[str, ...]] = {}
    for canonical, texts in sorted(reg_npc_forms.items()):
        if canonical in dossier_subjects:
            continue
        registry_only[canonical] = tuple(sorted(set(texts)))
        for t in texts:
            form_stems.setdefault(t, set())
            form_sources.setdefault(t, set()).add("registry")

    pcs: dict[str, set[str]] = {}
    unresolved: list[tuple[str, str]] = []
    if players is not None and registry is not None:
        by_string: dict[str, object] = {}
        for e in registry.entities:
            for t in [e.name, *e.aliases]:
                by_string.setdefault(t, e)
        for pl in players.players:
            for ch in pl.plays:
                ent = by_string.get(ch)
                if ent is None:
                    unresolved.append((pl.name, ch))
                elif ent.type == "npc":
                    pcs.setdefault(ent.name, set()).add(pl.name)

    ruled_ambiguity: dict[str, tuple[Owner, ...]] = {}
    for form in sorted(link_rulings):
        if form in form_stems and len(owners.get(form, ())) > 1:
            ruled_ambiguity[form] = tuple(sorted(owners[form]))
    if ruled_ambiguity:
        lines = [
            f"link ruling on {form!r}: the form is ambiguous (it names "
            + " and ".join(_fmt_owner(o) for o in collides)
            + "); an ambiguous form cannot be ruled - fix the summaries so each name "
            "belongs to one entity, then remove the ruling from canon.yaml"
            for form, collides in ruled_ambiguity.items()
        ]
        raise LinkRefusal("\n".join(lines))

    forms: dict[str, NameForm] = {}
    for text in sorted(form_stems):
        who = tuple(sorted(owners.get(text, ())))
        sources = tuple(sorted(form_sources[text]))
        stems = tuple(sorted(form_stems[text]))
        if len(who) > 1:
            forms[text] = NameForm(text, None, sources, AMBIGUOUS, who, stems)
        elif is_generic_token(text, wordlist):
            ruling = link_rulings.get(text)
            status = GENERIC_SAFE if ruling == "safe" else GENERIC_NEVER if ruling == "never" else GENERIC
            forms[text] = NameForm(text, who[0] if who else None, sources, status, (), stems)
        else:
            forms[text] = NameForm(text, who[0] if who else None, sources, LINKABLE, (), stems)

    index = FormIndex(
        forms=forms,
        stem_forms={s: tuple(sorted(t)) for s, t in sorted(stem_forms.items())},
        registry_scopes=registry_scopes,
        registry_only=registry_only,
        rulings=link_rulings,
        ruled_ambiguity=ruled_ambiguity,
        player_characters={c: tuple(sorted(n)) for c, n in sorted(pcs.items())},
        unresolved_players=tuple(sorted(set(unresolved))),
    )
    index.pattern = _compile(forms)
    return index
