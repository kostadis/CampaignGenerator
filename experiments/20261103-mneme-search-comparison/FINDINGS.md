# mneme finds the right sources more reliably than the exact target chunks

All 18 fixed read-only searches completed successfully. No search results were repaired or rerun. A separate initial exploratory search verified connectivity before the fixed queries were frozen.

| Query style and top-k | Both required chapter sources | Both exact target neighborhoods in returned drawers | Both neighborhoods after opening returned source files |
| --- | ---: | ---: | ---: |
| Bare species, top 1 | 0/16 | 0/16 | 0/16 |
| Bare species, top 5 | 6/16 | 0/16 | 6/16 |
| Bare species, top 10 | 9/16 | 1/16 | 9/16 |
| Encounter context, top 1 | 11/16 | 1/16 | 11/16 |
| Encounter context, top 5 | 14/16 | 4/16 | 14/16 |
| Encounter context, top 10 | 14/16 | 5/16 | 14/16 |

The exact-neighborhood measure looks for up to 60 source characters on each side of each marked mention, with whitespace normalized. Missing that window does not imply that every returned chunk is useless: another description of the same event can help a reader. Conversely, returning the right chapter alone does not establish the relationship between the target mentions.

## What worked

For the whistling ogre and second hungry ogre, contextual search returned both target neighborhoods within the top ten. It also found the previous-ogre ammunition reference and current target, preserving the material needed for the same/different distinction. Context queries recovered the expected evidence for q01, q02, q03, q11 and q13 directly in displayed drawers.

Opening the source chapters named by contextual hits recovered both exact neighborhoods for 14/16 pairs using only the top five hits. This expansion did not use hidden relation answers or open the missing target chapters by hand.

## What was missed

- **q04:** the Chapter 4 mountain-pass ogre versus the Chapter 5 prone continuation. The contextual top ten did not reach Chapter 5. The bare `ogres` search did reach Chapter 5 but did not return the exact target context directly.
- **q12:** the Chapter 3 explicitly corrected “ogres”/“oozes” token versus the genuine whistling ogre in Chapter 4. The contextual top ten did not reach Chapter 3. This demonstrates a retrieval miss involving correction evidence, not a demonstrated wrong entity merge.

Neither search style returned a same-referent/distinct/membership answer. Mneme alone cannot be assigned Terra's identity-accuracy score. Terra's earlier 13/13 result came from being handed the selected passages, not from finding them in the full palace.

## Operational observations

Median fixed CLI latency was approximately 1.83 seconds, including process startup and the declared embedding guard/search path. This is an observation from one shared local installation, not a latency benchmark against hosted resolution or cached SQLite lookup. All 18 fixed requests emitted the unrecorded historical embedder-identity warning. Live status verified a matching 1024-dimensional embedder; it also reported global corpus staleness. All seven fixture chapter files matched their mined-record hashes, and the seven original raw summary files remained unchanged. No index refresh or service reconfiguration was performed.

The result favors using mneme to discover source material, then expanding context before identity resolution. It does not support replacing reviewed identity relationships with similarity scores. Remaining work is a matched downstream model trial on retrieved/expanded evidence and better handling of cross-chapter continuations and corrected terms.

See [retrieval.json](results/retrieval.json), [expanded.json](results/expanded.json), [environment.json](results/environment.json), and [validation.json](results/validation.json). The [design](DESIGN.md) documents the favorable hand-authored queries, chunk-window metric, index limitations, and separation from relation accuracy.
