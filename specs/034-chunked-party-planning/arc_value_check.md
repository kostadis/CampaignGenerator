# The "states a value" check (#526)

`pipelines/summary_native/arc_check.py` drops an arc-score candidate whose event text (citations stripped)
states a current value, a running total or a threshold crossed: the GM decides arc scores (research R10).
The first version was one regex (`\b(score|total|value|points?)\b[^.]{0,30}\d | \bnow (?:at )?\d | \bthreshold…`)
that had never been run against real output.

## Status: real-campaign measurement is still pending

The issue asks for the check to be measured on real Out of the Abyss output. That campaign's data was not
available when this change was made, so **nothing here was measured on real candidates**. The rules and the
table below come from the three false positives and three misses the issue names, a code review's probe set
(about 90 value phrasings and 30 ordinary sentences), and cases constructed in the same spirit (addresses,
times, ordinals, creature counts, gold). Run `synth` for party and planning on the real campaign and read
`arc_report.md`'s `states a value` drops (false positives) and the kept candidates (misses) before trusting
the rates.

## Rule

A miss is the worse failure (a number reaches the GM as if decided); a false positive costs one candidate,
which `arc_report.md` lists with its reason. So every rule errs towards dropping. `states_a_value(event, names)`
drops a line when any of these match, case-insensitively:

- a score word (`score`, `total`, `value(s)`, `point(s)`) with a number within 30 characters, where the number
  is not an ordinal (`3rd`), a unit amount (`500 gp`, `2 bells`, `10 feet`, `3 days`) or a house number (a
  capitalised name ending in a street suffix: `3 Waterdeep Lane`). A capitalised word alone is **not** an
  address: `score of 5 Doom` and `now at 3 Obsession` are values. Also a score word + number word at the end of
  the clause (`a score of seven`, not `a total of seven guards`); `N points` / `one point`; `arc|tally|count|
  meter` within 15 characters of a number (`the tally is 4`);
- `now` / `is at` / `stands at` / `sits at` / `reaches` / `totals` / `currently` plus a number that ends the
  clause (stop, comma, dash, `and`, `N of <digits>`, a counter noun, or a capitalised word), so `now at 3
  Waterdeep Lane`, `now sees 3 banners` and `now one of the Council` stay. `is at N` is not read after an
  appointment noun (`the meeting is at 9`);
- a counter-moving verb (`push`, `raise`, `bump`, `drop`, `climb`, `fall`, ...) a few words before `to N` or `by N`,
  or `bring/take/put/set ... it to N`; `from N to M`; `ticks up|down`;
- a signed delta: `+2` after a word, a stand-alone `-1`;
- a fraction `N/M`, or `strike|mark|tick|stage ... N of M`;
- a bare count of a counter noun: `N strikes|ticks|stacks|segments|boxes` (also `N more …`); `marks` only after
  `has|gains|earns|carries|bears|with|at` or before `now|so far`; an ordinal + `strike|tick|segment|box`
  (`his third strike`, not `the first strike on the ogre`; `second mark` is left out on purpose); `strike|tick N`;
- a meter, tracker, track, clock or gauge filling (`the meter fills`, `Daz's meter is full`, not `full of`);
- a threshold reached, crossed, met, exceeded, `crosses the threshold` (not `the threshold of the tower`),
  `one mark away from the threshold`;
- the mechanic file's own score names (`score_names`: `Obsession` from `# Daz — Obsession arc`, `the Wrath
  score`) followed by filler (`is`, `now`, `at`, `to`, `level`, `:`) and a number, `+N`, or before a threshold;
  `N <name>` (`gains 1 Obsession`); `<name> point(s)` / `point(s) of <name>`; `<name> is full|maxed|at its max`,
  `<name> reaches its peak`, `<name> ticks`; `<name>, at 4,`.

Score names are read from free prose next to `arc|score|track|tracker|meter|counter|clock|tally|pool`, so they
are a hint: a wrong name can only cost a candidate. A capitalised word that starts a sentence (`Keep score`) and
common words are skipped; a player character's name next to "arc" is not told apart (the check is not given the
roster). Number words (`four`, `zero`) count only where a verb, `stands at`, `is at` or a score word already says
the sentence is about a counter, and the number word ends the clause.

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
| Daz now at 3 Obsession | value followed by a score name; a capital letter alone is not an address |
| Daz now at 4 Madness | value followed by a capitalised word |
| A score of 5 Doom | score word + number + capitalised word |
| Score 4 Obsession | score word + number + score name |
| The Madness score is now 3 Daz snaps | 'now 3' followed by a capitalised word |
| His point count is 4 | singular 'point' is a score word |
| Daz pushes it to 5 Wrath | counter verb + 'it to N' + score name |
| Daz raises it to 4 Corruption | counter verb + 'it to N' + score name |
| A score of seven | score word + number word |
| His score is seven | score word + number word |
| Daz's arc is at 3 | 'arc' near a number |
| The tally is 4 | 'tally' near a number |
| Daz is at 3 | 'is at N' ending the clause |
| Max is 6 and he is at 5 | 'is at N' before 'and' |
| Daz has 3 strikes against him | bare count of a counter noun |
| Daz needs two more strikes | 'N more' + counter noun |
| Daz has three marks | 'has N marks' |
| 4 marks now | 'N marks now' |
| A second strike against him | ordinal + strike |
| His third strike | ordinal + strike |
| Strike two | 'strike N' |
| Daz fills a third box | ordinal + box |
| The meter fills | a meter filling |
| Daz's meter is full | a meter full |
| Daz is one mark away from the threshold | 'away from the threshold' |
| Daz goes from 2 to 3 | 'from N to M' |
| Wrath ticks up | 'ticks up' |
| Wrath ticks up to 4 | 'ticks up' + 'to N' |
| Daz gains 1 Obsession | N + score name |
| Daz loses 2 Wrath | N + score name |
| Daz gains two Obsession | number word + score name |
| Daz gains 2 Corruption points | N + score name + points |
| Another point of Wrath | 'point of' + score name |
| Daz's first Obsession point | score name + point |
| Wrath is maxed out | score name maxed |
| Obsession is at its maximum | score name at its maximum |
| Obsession reaches its peak | score name reaches its peak |
| Daz's Obsession, at 4, flares | score name, at N, |

### Ordinary text (kept)

| Event text | Why |
|---|---|
| He is now one of the Council | 'now one' is not a count when 'of the' follows |
| The meeting is at 9 | 'is at N' after an appointment noun |
| Daz leaves two marks on the cell door | 'marks' counts only after a possessing verb or before 'now' |
| Daz bears a second mark from the ritual | ordinal + 'mark' is left out on purpose |
| Daz carries the mark of Demogorgon | 'mark' with no number |
| Daz lands the first strike on the ogre | ordinal + strike followed by 'on' |
| Daz travels from 3 to 4 days out | 'from N to M' where M carries a unit |
| The maximum depth is 300 feet | a unit amount; 'maximum' is not a rule here |
| The count of Gracklstugh offers him a deal | 'count' with no number |
| The clock tower strikes three | 'strikes' is a verb; the clock is not a meter |
| Daz counts 3 tracks in the mud | 'tracks' is not a counter noun |
| The party is at 3 days from the Underdark exit | 'is at N' where N carries a unit |
| Daz is at the 2nd gate | an ordinal |
| Daz drinks to the full | 'full' with no meter |
| Daz kills two more and flees | 'two more' with no counter noun |
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
| Daz lands 3 strikes on the ogre | a bare 'N strikes' is a count of the counter noun; combat prose is not told apart |
| Daz opens 3 boxes in the cellar | a bare 'N boxes' is a count of the counter noun |
| Daz wields a +1 longsword | a magic item's '+1' is indistinguishable from a signed delta |
| A total of 12 guards patrol the wall | 'total ... N' is the value shape; the idiom is not told apart |
| 2/3 of the guards flee | any bare 'N/M' is read as a fraction/score |
| Daz takes 3 points of damage | 'N points' is a point count; damage is not told apart |
| Daz is at 5/5 hp | any bare 'N/M' is read as a fraction/score |

## Known gaps (not in the table)

Misses left on purpose (rare, or not separable from ordinary prose without a model):

- A count with no digit-or-number-word shape: `two more and he breaks`, `one step from breaking`, `Wrath
  increases`, `Daz's Wrath is high`, `doubles his Wrath`.
- Em-dash deltas (`Wrath—2`), Roman numerals (`now at IV`), `Obsession x3`, `box 3 is checked`.
- `Daz is at 4 on the track`: `is at N` is not read when a noun follows the number.
- `three marks` with no possessing verb (`marks` is also ordinary prose), and `a second mark`.
- A score name the mechanic file never writes beside `arc`/`score`/`meter`/`counter`/`clock`/`tally`/`track`/`pool`.
