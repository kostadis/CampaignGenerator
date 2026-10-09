# The "states a value" check (#526)

`pipelines/summary_native/arc_check.py` drops an arc-score candidate whose event text (citations stripped)
states a current value, a running total or a threshold crossed: the GM decides arc scores (research R10).
The first version was one regex (`\b(score|total|value|points?)\b[^.]{0,30}\d | \bnow (?:at )?\d | \bthreshold…`)
that had never been run against real output.

## Status: real-campaign measurement is still pending

The issue asks for the check to be measured on real Out of the Abyss output. That campaign's data was not
available when this change was made, so **nothing here was measured on real candidates**. The rules and the
table below come from the three false positives and three misses the issue names, plus cases constructed in
the same spirit (addresses, times, ordinals, creature counts, gold). Run `synth` for party and planning on the
real campaign and read `arc_report.md`'s `states a value` drops (false positives) and the kept candidates
(misses) before trusting the rates.

## Rule

A miss is the worse failure (a number reaches the GM as if decided); a false positive costs one candidate,
which `arc_report.md` lists with its reason. So every rule errs towards dropping. `states_a_value(event, names)`
drops a line when any of these match, case-insensitively:

- a score word (`score`, `total`, `value(s)`, `points`) with a number within 30 characters, where the number is
  not an ordinal (`3rd`), a unit amount (`500 gp`, `2 bells`, `10 feet`, `3 days`) or a house number (a capitalised
  word follows: `3 Waterdeep Lane`); `N points` / `one point`;
- `now` / `stands at` / `sits at` / `reaches` / `totals` / `currently` plus a number that ends the clause (stop,
  comma, dash, `and`, `of`, or a counter noun such as `strikes`), so `now at 3 Waterdeep Lane` and `now sees 3
  banners` stay;
- a counter-moving verb (`push`, `raise`, `bump`, `drop`, `climb`, `fall`, ...) a few words before `to N` or `by N`,
  or `bring/take/put/set ... it to N`;
- a signed delta: `+2` after a word, a stand-alone `-1`;
- a fraction `N/M`, or `strike|mark|tick|stage ... N of M`;
- a threshold reached, crossed, met, exceeded, or `crosses the threshold` (not `the threshold of the tower`);
- the mechanic file's own score names (`score_names`: `Obsession` from `# Daz — Obsession arc`, `the Wrath score`)
  followed by filler (`is`, `now`, `at`, `to`, `level`, `:`) and a number, `+N`, or before a threshold.

Score names are read from free prose, so they are a hint: a wrong name can only cost a candidate. Number words
(`four`, `zero`) count only where a counter verb or `stands at` already says the sentence is about a counter.

## Verdicts

The table is the parametrised test `TestValueVerdictTable` in `tests/test_summary_native_arc.py`; a test checks
that every row appears below.

### States a value (dropped; zero misses on this table)

| Event text | Why |
|---|---|
| The score is now 3 | score word + number |
| SCORE stands at 3 | score word + number |
| Daz's value rises to 2 | value word + number |
| He gains points, bringing it to 6 | points word + 'bringing it to N' |
| Daz gains 2 points | a stated point count |
| Daz gains one point | a stated point count (number word) |
| The threshold is reached | threshold reached |
| The threshold was crossed | threshold crossed |
| Daz crosses the Obsession threshold | crosses 'the ... threshold' (no 'of') |
| Daz pushes it to 5 | counter verb + 'it to N' |
| Daz bumps it to a 4 | counter verb + 'it to a N' |
| Daz drops it to zero | counter verb + 'to <number word>' ending the clause |
| Daz raises the count by 2 | counter verb + 'by N' |
| Wrath +2 | signed delta after a word |
| Wrath -1 | signed delta, minus |
| Daz takes a second strike against him (2/3) | parenthesised fraction |
| Daz is on strike 2 of 3 | counter noun + 'N of M' |
| They are now at 3 | 'now at N' ending the clause |
| The count is now 3 | 'now N' ending the clause |
| Wrath, now 3, flares | 'now N' before a comma |
| The tally stands at four | 'stands at <number word>' |
| Obsession now at 4 | score name + now at N |
| Obsession climbs to 4 | score name + verb + N |
| Obsession rises by 1 | score name + verb + N |
| Obsession is at level 3 | score name + is at level N |
| Obsession: 4 | score name + colon + N |
| His Wrath 2 goes up | score name directly followed by N |
| Obsession total reaches 5 | total + number |

### Ordinary text (kept)

| Event text | Why |
|---|---|
| Total strangers at the 3rd gate | 'total' but the number is an ordinal |
| The point of no return at 2 bells | 'point' but 2 counts bells |
| They are now at 3 Waterdeep Lane | an address (capitalised street name follows) |
| Daz moves to 3 Waterdeep Lane | an address |
| Daz casts a level 3 spell | a number, no score word |
| Daz spends a 4th-level slot | an ordinal |
| Daz leaves three guards behind | a count of creatures |
| Daz meets 13 goblins at the pass | a count of creatures |
| Daz fights 4 orcs on the road | a count of creatures |
| Daz hits 3 guards | a count of creatures (hit is not a counter verb) |
| Daz kills 2 of the 5 guards | 'N of M' without a counter noun |
| Daz pays 500 gp to the guard | gold amount |
| Daz buys a ring worth 200 gp | gold amount |
| Daz gets 10 feet closer | a distance |
| They meet at 9 pm | a time of day |
| Daz arrives at 4 o'clock | a time of day |
| Daz raises the alarm at 2 bells | raise-verb, but no 'to N' and a time unit |
| Daz waits 3 days | a duration |
| Daz climbs to the 2nd floor | counter verb + 'to', but an ordinal |
| Daz is now at the gate | 'now at' + no number |
| He now sees 3 banners | 'now' + a word before the digit |
| Daz scores a hit on the second try | 'scores' is not 'score' |
| A valued ally gives him 2 maps | 'valued' is not 'value' |
| He reaches the threshold of the tower | a doorway, not a stated threshold |
| Daz reaches 3 Waterdeep Lane | 'reaches' + an address |
| Obsession flares at 3 gates | score name, but 'flares' is not a value connector |
| Daz's obsession leads him to the vault | score name, no number |

### Accepted false positives (dropped although ordinary)

| Event text | Why accepted |
|---|---|
| Daz wields a +1 longsword | a magic item's '+1' is indistinguishable from a signed delta |
| A total of 12 guards patrol the wall | 'total ... N' is the value shape; the idiom is not told apart |
| 2/3 of the guards flee | any bare 'N/M' is read as a fraction/score |
| Daz takes 3 points of damage | 'N points' is a point count; damage is not told apart |
| Daz is at 5/5 hp | any bare 'N/M' is read as a fraction/score |

## Known gaps (not in the table)

- A bare count of a counter noun with no score word, name or delta: `Daz has 3 strikes against him`. It reads
  like an ordinary count of events, and `hits 3 guards`-style text is far commoner; the prompt forbids it.
- Number words outside the shapes above: `a score of seven`, `the total is five` (the latter is caught only
  because `total` precedes a stop-ending number word; `score of seven` is not).
- A score name the mechanic file never writes beside `arc`/`score`/`meter`/`counter`/`clock`/`tally`/`track`/`pool`.
