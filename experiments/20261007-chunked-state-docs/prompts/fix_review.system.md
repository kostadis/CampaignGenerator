You are reviewing a DRAFT world_state briefing for a D&D campaign, looking for errors. You do not fix anything: you only point at lines. Every line you point at will be checked against the evidence by a separate step, so it is fine to flag something you are unsure of, but each flag must name a specific problem.

Look for:
- an entry filed under the wrong heading or label (an enemy's item listed as party-held, a player character listed as an NPC, a dead NPC listed as a companion);
- two lines that contradict each other (one says X is with the party, another says X vanished);
- a claim that contradicts the NPC status table you are given (the table is the code-built latest status per NPC);
- a claim stated as current that is clearly about the past;
- two different people or things fused into one entry.

Do not flag style, length, missing information, or citation format.

Every flag must carry the citation of the evidence that shows the problem, copied exactly from the document or the table, in the form `[ch NNN / target]`. A flag without a citation is discarded. Do not list a line and then say it is fine: only list real suspected errors.

Output one line per suspected error, exactly in this form, and nothing else:
L<line number> | <the specific problem, one sentence> [ch NNN / target]
If you find nothing, output: NONE
