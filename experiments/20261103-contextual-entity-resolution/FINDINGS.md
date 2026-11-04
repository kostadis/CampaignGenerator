# Context distinguishes instances without unique names

The controlled experiment demonstrates useful contextual disambiguation beyond
global name lookup. All four creature labels are `bugbear`; opaque persistent
IDs distinguish the instances. Removing context produces no unique identity
proposals. Adding supported location, time and descriptive constraints produces
15 correct unique-candidate proposals in the 26 base cases. Two additional
missing/conflicting-evidence cases also behave as expected. All 28 designed
cases pass, with no unsupported unique proposal in this fixture.

The 40 tests include those cases plus identity relabeling, input-order changes,
campaign boundaries, missing evidence, future-information leakage, source
validation, cycles, input mutation and the current registry's collision rule.
These are synthetic regression results, not an accuracy estimate for arbitrary
campaign prose or an NVIDIA Auto Ontology runtime benchmark.

## The user's three-level case

At the first observation, the same reference has different candidates according
to scene context:

| Reference | Context | Result |
|---|---|---|
| the bugbear | first dungeon, level one | `e_7c2f` |
| the bugbear | first dungeon, level two | `e_91d0` |
| the bugbear | first dungeon, level three | `e_a340` |
| the bugbear | no location | ambiguous among all four |
| the bugbear | other dungeon, level one | `e_6f18` |

The names are genuinely identical. The resolver does not secretly rename them
“level-one bugbear,” use level as an entity key, or receive a gold entity ID in
the mention. Replacing all opaque IDs and replacing the label with another
generic term preserve the answers under the corresponding ID mapping.

## Why a location/name key is insufficient

The first individual moves from level one to the stairs on level two. A
time-bounded location relationship changes while its entity ID remains
`e_7c2f`. The original level-two individual is still there, guarding a different
room. Consequently:

- “the bugbear on level two” becomes ambiguous between two individuals;
- the stairs, the guarded room, or a supported torn-ear description separates them;
- referring back to the level-one encounter uses that encounter's time;
- the later corpse remains the same individual rather than a new entity;
- expired observations do not silently persist forever.

The initial `(level, name)` lookup returns the wrong individual for the moving
bugbear and invents a unique answer when two bugbears share level two. These
two failures are recorded as explicit baselines in the report.

## Abstention is part of identity handling

A missing location fact keeps an individual possible. An observation stating
only the level cannot establish a particular room on that level. Conflicting
location observations block a unique proposal, even when only one individual
remains possible. Future rank information cannot identify a past encounter.

The referent's explicit location takes precedence over the speaker's current
scene location: a party on level two can discuss the level-three bugbear.
That is reference scope, not a global assertion that everyone mentioned in a
scene is present there. Incompatible explicit referent scopes cause a conflict.

## What this proves, and what it does not

It establishes that a small relationship model can maintain distinct same-label
instances and generate evidence-backed mention candidates using context and
time. Names alone are not necessary as unique keys. It also makes clear that
“unknown,” “multiple possible,” and “one supported known candidate” are distinct
outcomes.

The world facts, continuity links and mention constraints are hand-annotated.
This experiment does not show an LLM reliably extracting them from a transcript,
determining whether two encounters concern the same unnamed creature, resolving
pronouns, or proving that an unseen creature is not the referent. It neither
creates canonical identities nor changes the current registry. A successful
candidate proposal still needs the existing human review boundary.

## Architecture implication and next test

Represent instance identity with a stable ID and let display names, aliases,
species terms and descriptions retrieve multiple candidates. Store location,
role and distinguishing observations as sourced relationships with effective
intervals. Keep mention-to-entity links separate, evidence-backed and reviewable.
The production registry currently enforces globally unique names/aliases and
would need an explicit schema/consumer migration or a separate instance layer.

The next useful evaluation is a small GM-labeled set of actual repeated unnamed
creatures. Have a context-extraction stage produce constrained observations and
reference features without seeing the gold IDs, then run this resolver and
measure extraction errors, false merges, false splits, ambiguity retention and
human-review load. That would test the difficult prose-to-evidence step that
this controlled experiment deliberately isolates.
