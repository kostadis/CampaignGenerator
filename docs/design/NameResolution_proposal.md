# Name Resolution: making the canon chain a call instead of a paragraph

> **Status:** implemented. Written 2026-09-21 as a proposal; §7 records what building
> it changed, and was appended the same day. Original read of the Out-of-the-Abyss canon
> chain (five files, four formats) against `entity_registry/registry.py` and
> `entity_registry/registry_mcp.py` as they stand at `67db6db`.
> **Scope:** a read-only `resolve_name` that walks the chain and returns a ruling —
> where a name resolves, on whose authority, and whether writing it would change
> anything. It reads and reports; it never writes.
> **Tracked by:** [#477](https://github.com/kostadis/CampaignGenerator/issues/477).
> **Landed by:** PR against #477 — `entity_registry/resolve.py`, `registry resolve`,
> `registry_resolve_name_tool`, `tests/test_resolve_name.py` (26 tests).
> **Prompted by:** [EvoOntology, arXiv 2609.15779](https://arxiv.org/abs/2609.15779) — see §6.
> **Related:** `registry_check` / `registry_triage_candidates` are the existing
> read-only surfacing tools; this is the third, and the only one that fires
> *before* the write rather than after it.

## 1. The problem: a hard rule with no mechanism

Every campaign's `CLAUDE.md` states the rule plainly:

> **Before you write any proper noun — or change one — resolve it against the
> canonical source. If what you are about to write deviates from canon, stop and
> ask the GM. Every time.**

and fixes the chain, first hit wins:

| Tier | Source | Authority |
|---|---|---|
| 1 | `config/party.yaml` | PC names, over any filename, dossier, or prose usage |
| 2 | `notes/vtt_transcription_corrections.md` | the spell-pass glossary; the **bolded** right-hand column is canon |
| 3 | `docs/entity_registry.yaml` | canonical names and approved aliases for everything else |
| 4 | `docs/npcs/<name>.md` | a dossier's own stated ruling, when it cites one |
| 5 | `notes/vtt_known_additions.md` | confirmed real, not yet promoted |

Absent from all five, the name **is not canon**: surface it as a candidate and wait.

The rule is correct. The mechanism is a paragraph. Five files in four different
formats, consulted by a language model across a sixty-scene pass, with nothing
that can tell afterwards whether the lookup actually happened. The rule is
enforced by the model remembering to enforce it.

### 1.1 What that costs, concretely

Four failure modes, all of which the prose rule names and none of which it can catch:

- **Silent normalisation.** `Lucius Graham` → `Lucius Graeme` is the *right* fix and
  still a name change. The glossary justifies the direction, not skipping the GM's
  eyes. The GM is dyslexic; transposed-letter pairs are precisely the ones that do
  not get caught on visual review, so a change that ships unshown ships unreviewed.
- **Invented spelling.** A name in no tier gets the transcript's majority spelling
  carried forward as though the transcript were an authority. It is not.
- **Silent adjudication.** Two tiers disagree; the model picks. The rule says show
  the GM each source and wait.
- **Buried rulings.** A bulk rename presents as twenty edits in a diff instead of
  one ruling on a card.

`registry_triage_candidates` covers a slice of the second case, but it sweeps proper
nouns out of *finished session output* — by then the write has happened and the
document is the thing being reviewed.

## 2. The tool

`resolve_name(campaign_dir, surface_form) -> dict`. One job: walk the chain, report
what it found and who said so. **Read-only, by construction** — it shares no code
path with the five identity-mutating verbs.

### 2.1 Return shape

```json
{
  "surface_form": "Gurrigam",
  "status": "resolved",
  "canonical": "Gyrgum",
  "tier": 2,
  "authority": "notes/vtt_transcription_corrections.md:14 (PCs table)",
  "evidence": "| Grygum, …, Gurrigam | **Gyrgum** |",
  "is_change": true,
  "entity_type": "pc",
  "parenthetical": null,
  "also_found_in": [{"tier": 1, "source": "config/party.yaml", "value": "Gyrgum"}],
  "conflicts": [],
  "near_misses": []
}
```

Three statuses. The two that are not `resolved` are the whole point of the design.

**`resolved`** — one tier ruled; lower tiers agree or are silent. `is_change` is true
when `canonical` differs from `surface_form`. That flag is the machine-readable form
of "this is a ruling the GM has to see" — a caller that applies an `is_change: true`
result without surfacing it is violating the rule in a way that is now *detectable*,
because the call happened and the flag was set.

**`ambiguous`** — two tiers disagree. Returns every source and its spelling, plus
which the chain favours and why, and deliberately **no `canonical` field at all**.
There is nothing for a caller to apply. Adjudication is not the tool's to do, and
the absent field makes that structural rather than advisory.

**`not_canon`** — absent from all five tiers. Returns `near_misses` from the existing
`_near_misses()`, explicitly labelled as *candidates to ask the GM about*, never as
a resolution. This is the case where the current pipeline quietly guesses.

### 2.2 Chain implementation

| Tier | Parse | Reuse | Note |
|---|---|---|---|
| 1 | `characters[].name` from `config/party.yaml` | — | surname-tolerant; see §3.2 |
| 2 | markdown tables; left cell split on `,`, right cell `**X**` | — | see §3.1 |
| 3 | `load_registry()` then `_find_owner(norm_subject(s))` | exact reuse | already correct; no new matching logic |
| 4 | dossier's own stated ruling, **only when it cites one** | — | weakest positive tier |
| 5 | `- **Name** — …` bullets | — | resolves with `promoted: false` |

Tier 3 is the one that already works, and the tool must not reimplement it. Every
normalisation goes through `registry.norm_subject`; every fuzzy match goes through
`registry._near_misses` at `NEAR_MISS_THRESHOLD`. A second normalizer in the codebase
is a second opinion about identity, which is exactly the thing the registry exists
to prevent.

### 2.3 Skeleton

```python
TIERS = [_t1_party, _t2_glossary, _t3_registry, _t4_dossier, _t5_known_additions]

def resolve_name(campaign_dir: Path, surface: str) -> dict:
    key = norm_subject(surface)
    hits = [h for t in TIERS if (h := t(campaign_dir, key, surface))]
    if not hits:
        reg = load_registry(find_registry(campaign_dir))
        return _not_canon(surface, _near_misses(surface, reg, NEAR_MISS_THRESHOLD))
    ruling, *lower = hits                 # first hit wins — chain order IS the authority
    conflicts = [h for h in lower
                 if norm_subject(h["value"]) != norm_subject(ruling["value"])]
    if conflicts:
        return _ambiguous(surface, ruling, conflicts)   # no `canonical` key emitted
    return _resolved(surface, ruling, lower)
```

Pure functions, no I/O beyond reading the five files, so the hazards in §3 are unit
-testable without a campaign on disk.

## 3. Hazards found in the real files

These are not hypothetical. Each was found reading the live OOTA corpus.

### 3.1 The glossary's parenthetical is overloaded

```
| Ebum Mir, Ebonir, Princess Ebonir, … | **Ebonmire** (Princess Ebonmire) |
| Zuggtomy, Zugtmoy, Zugtomy, …        | **Zuggtmoy** (confirmed via 5etools: MTF + OotA) |
```

Identical syntax. The first parenthetical is an alias; the second is a provenance
note. **Do not heuristic these apart.** Return the bold form as `canonical` and the
parenthetical raw in `parenthetical`, unclassified, for the GM to read. A classifier
here is a small convenience that eventually promotes "confirmed via 5etools" into a
name — and a fabricated canonical name is the most expensive error in this system,
because everything downstream trusts the glossary.

### 3.2 Tier 1 and tier 2 legitimately differ in length

`config/party.yaml` carries `Thorin Giantfriend`; the glossary rules on `Thorin`.
Matching must tolerate the surname, and this pair must **not** be reported as a
conflict — a spurious `ambiguous` on a PC name every time one is resolved would
train the GM to dismiss the status, which destroys its value on the cases that are
real.

### 3.3 A filename is not evidence

`docs/party/sequioa.md` does not make `Sequioa` canonical — `config/party.yaml` says
**Sequoia** and the file is simply named wrong. Tier 4 reads a dossier's *stated*
ruling, never its path.

## 4. Surfaces

Two thin wrappers over the same pure function:

- **CLI** — `registry resolve <name> [--json]`, a new subcommand in `registry.py`,
  so bash-driven skills (`/vtt-spell-pass`, `/consistency-check`, `/voice-smooth`,
  `/entity-triage`) can call it without an MCP round-trip.
- **MCP** — `registry_resolve_name_tool` in `registry_mcp.py`, through the existing
  `_run_main` in-process runner. It belongs in the server `instructions` beside
  `registry_check` and `registry_triage_candidates` as read-only "start here", and
  explicitly **not** beside `registry_add` / `alias` / `merge` / `mark_distinct` /
  `mark_rejected`.

That placement is documentation doing real work: the tool listing is where a session
learns which calls decide identity and which only report on it.

## 5. What this does and does not change

**Does:** turns the canon rule from an instruction into a call with three outcomes,
two of which cannot proceed without the GM. Gives bulk renames a countable list of
*distinct rulings* rather than a diff of occurrences. Makes "did the lookup happen"
answerable.

**Does not:** decide anything. No status resolves a contested name, no code path
writes to the registry or the glossary, and the glossary-inversion rule is untouched
— inverting a row remains a thing only the GM does, after seeing a diff.

## 6. On the paper that prompted this

EvoOntology (arXiv 2609.15779, Renmin University, Sept 2026) addresses the
"agent-data gap": agents reaching heterogeneous sources through generic tools with
no semantics. Its architecture is an ontology served as an **MCP server** with
schema / content / tool layers, which the agent *queries at runtime* rather than
receiving pre-baked in a prompt; a builder agent constructs it, and a self-evolution
loop proposes **typed edits** driven by **failure attribution**, accepted when a
backbone-conditional paired evaluation shows improvement.

Three pieces map onto this repo, with sharply different value:

1. **Ontology as runtime query, not prompt context** — the part worth taking, and
   what this proposal is. The registry is already served over MCP; the glossary and
   the rest of the chain are prose files read wholesale into a context window and
   hoped over. `resolve_name` finishes the job.
2. **Typed edits** — we already have these, and in better shape than the paper's:
   `registry_alias` / `merge` / `mark_distinct` / `mark_rejected` *are* the typed
   edit vocabulary, with anti-merge guards the paper has no equivalent of.
3. **Failure attribution as the trigger** — worth stealing later, separately.
   Today a gap surfaces as a *string* signal (`triage-candidates` sweeping proper
   nouns out of finished output). The paper's move is to attribute a downstream
   failure back to the missing entry and propose the edit that would have prevented
   it. Left out of scope here; noted for its own issue.

**The self-evolution loop closing itself is the part to leave on the page.** The
paper's gate is an automated paired eval, which is sound when edits are scored
against benchmark accuracy. Our edits are canon rulings — which letters go in what
order, whether two names are one entity — and "the eval improved" is not a ruling on
`Sequoia` vs `Sequioa`. This repo's own LLM Pipeline Design Rule names scope,
ordering and attribution as precision decisions requiring a human checkpoint; a
metric is not a checkpoint. Take the proposal machinery, keep the GM as the gate.

## 7. What building it changed

Three things the design above got wrong or left out, all found by writing the tests
and then running the result over the live Out-of-the-Abyss corpus. The design is left
standing as written and corrected here, because the corrections are the interesting
part.

### 7.1 Exact-key matching cannot see the case that motivated the whole thing

The `ambiguous` status as designed compares tiers that each matched **the same surface
form**. Two tiers holding two *spellings* of one name never both match, so `ambiguous`
would almost never have fired — and worse, the motivating example fails open. Resolving
`Sequioa` hits the dossier that states `Sequioa`, stops, and answers **resolved, no
change**, while `config/party.yaml` sitting one tier above says `Sequoia`. The tool
would have waved through precisely the transposed-letter pair the canon rule exists to
catch.

Fixed with `higher_authority_drift()`: after a tier rules, tiers that **outrank** it are
scanned for a near-identical but incompatible canonical form, and any hit makes the
result `ambiguous` with the higher tier favoured. Restricted to *outranking* tiers on
purpose — comparing every tier against every other fires on any two similarly-named
distinct entities and buries the signal, whereas a lower-trust source disagreeing with a
higher-trust one is always worth stopping for.

### 7.2 A leading article is not a spelling difference

`Overbright` came back `ambiguous` on the live corpus: the registry carries
**the Overbright**, known-additions carries **Overbright**. That is one name and one
article. Flagging it would fire on every article-prefixed entity in the campaign, and a
status that cries wolf is a status the GM learns to dismiss — which is the same failure
as not having it. `compatible()` now forgives a leading `the`/`a`/`an` for
**comparison only**; nothing rewrites a stored name, and `the Overbright` stays
`the Overbright` in the output.

### 7.3 The tiers have to forgive the same things

Tier 1 was specified as surname-tolerant and the rest as exact-key. That splits the
chain: the same name resolves at a different tier depending on which form you happened
to type. All five tiers now match on `compatible()`, so the two forgiven differences —
a trailing surname, a leading article — are forgiven uniformly.

### 7.4 Exit codes

Not in the design, added because a shell caller needs to branch without parsing: the CLI
exits **0** resolved, **3** ambiguous, **4** not_canon. Nonzero means *stop and ask the
GM*, which is the correct reflex for a script and the correct reflex for a person.

The MCP wrapper deliberately does **not** propagate those as errors — it returns the
JSON body in all three cases. A tool that looks broken invites being worked around, and
the two statuses it would break on are the two that require the GM.

### 7.5 What the live corpus says now

Against `out-of-the-abyss/`, with its 500-line glossary and 122KB registry:
`Gurrigam` → `Gyrgum` (tier 2, `is_change: true`); `Gladwell` and `Bernie Gutton` both
→ `Glabbagool`; `Ebonir` → `Ebonmire` with `(Princess Ebonmire)` returned raw and
unclassified; `Zugtmoy` → `Zuggtmoy` with `(confirmed via 5etools: MTF + OotA)` likewise
raw; `Thorin` → `Thorin Giantfriend` with `is_change: false`; `Sequioa` → `not_canon`,
no near miss, ask the GM.
