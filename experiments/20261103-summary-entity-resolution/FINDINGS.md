# Real summary context distinguishes orc groups and ogre individuals

Completed 2026-11-04 in the isolated experiment worktree. This extends the
synthetic bugbear trial to raw passages from seven authored Phandalin summaries.
The model was gpt-6.1-sol at medium effort through CampaignGenerator's Codex CLI
adapter. No registry or campaign source was changed.

## Result

There were 16 reference-pair comparisons: 13 clearer source-based expectations
and three exploratory continuity/membership cases. Expected answers were frozen
and withheld from the model. The model received raw prose and marked spans,
without hand-labeled location, identity or role features. This tests interpreting
known mention spans, not automatically finding every creature mention.

| Trial | Context: stricter expectations matched | Words-only control | Context evidence failures |
|---|---:|---|---:|
| Initial, offsets only | 12/13 | abstained on 16/16 | 6 under the strengthened exact-target check |
| Explicit targets, matched instructions | 13/13 | abstained on 16/16 | 0 |

The control's abstentions are appropriate: generic reference words alone do not
establish identity. The experiment demonstrates the value of source context;
it is not a statistical accuracy estimate. The expectations are researcher
interpretations of the supplied passages, not independent GM adjudications.

## What it distinguished

- Chapter 39's orcs at the Shrine of Savras and Falcon's Lodge received separate
  location scopes. The model did not claim the text proved disjoint membership
  or identify individual unnamed occupants.
- Chapter 4's earlier slain wandering ogre and the second ogre in the mountain
  pass remained different individuals. A reference to the earlier ammunition
  source inside the later encounter linked back to the earlier ogre.
- Repeated references to the same numbered orc within Chapter 4's battle linked;
  differently numbered combatants stayed separate.
- Chapter 46's allied and cultist orcs stayed separate despite sharing a battle
  location. Location alone would not have been enough.
- The three recruited orcs and the newly addressed stewards linked as the same
  small group despite the change in descriptive label.
- Chapter 42's three hesitant orcs were treated as a subset of the ten arrivals,
  not equated with the entire group, and remained distinct from the still-hostile
  orcs at that moment.
- Chapter 3's explicit correction of “ogres” to “oozes” prevented creating an
  ogre referent from the mistaken surface word.

## Two limitations exposed by the actual run

The initial presentation supplied character offsets into long paragraphs. The
model substituted the wrong numbered orc for a marked reference and quoted a
true sentence about that other orc. Checking that a quotation occurred anywhere
in the source paragraph did not detect the wrong subject.

The follow-up made each target visible and required evidence quotations to
cover the exact marked occurrence. Raw passages, reference spans, cases and
hidden expectations were unchanged. All final quotations passed that stronger
check. Both arms were rerun with the same revised system instructions; the
original responses and their failures are retained. This was one disclosed
protocol repair, not an untouched first-pass success or a held-out replication.

The final model still inferred that the three recruited stewards were selected
from the allied survivors. The selected passage does not explicitly establish
which three orcs were recruited. This was an exploratory ambiguity case and
remains unresolved. Exact quotation coverage cannot certify that membership
inference. The other two exploratory cases produced plausible continuity links
between the unfinished ogre fight and Chapter 5, and between the ranch corpses
and the account of the slain raiders; neither is treated as a new canon ruling.

## Implication

Context can separate location/encounter-scoped creature groups and support some
individual reference links. It cannot invent identifiers for each unnamed orc
in a collective description. Keep a distinction among individual, group, subset,
species, separate scope and unresolved identity.

Use model output as proposed relationships with source evidence, exact marked
spans, and independent review. Preserve scope separation without upgrading it
to proof that groups never share members. Membership and cross-session identity
links need particular care. The experimental graph preserves these relation
types and reports coidentity/distinctness conflicts; it publishes nothing.

This used a local experiment harness and the Codex model adapter. NVIDIA Auto
Ontology's runtime was not installed or evaluated. Production registry schema
and consumers remain unchanged.

## Evidence and reproduction

`results/summary.json` retains both trials' measurements, model record hashes,
registered input identities, per-case relations, and source reference metadata.
`results/validation.json` records tested code identities, source immutability,
the ten passed local tests and the four model calls. Full private passages,
prompts, verified system instructions, raw responses and detailed reports remain
in the two explicitly named `/tmp` run directories documented in the README.
The `prepare_cases.py` selectors reproduce the final target-marked payload from
the campaign sources without copying the full narrative into this repository.
