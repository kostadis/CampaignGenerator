TABLE-SPEECH AUDIT — the one permitted non-narration output.

A quoted span's speaker label can be wrong: upstream extraction sometimes
attributes the GM's table narration to a character. Judge the content, not the
label. A span is out-of-fiction table speech rather than in-fiction dialogue when
it:
  (a) addresses a player in the second person;
  (b) is stage direction describing its own speaker in the third person;
  (c) embeds a speech tag inside the quotation marks;
  (d) names the point-of-view character in the third person inside that
      character's own quote;
  (e) is, by the brief's rule, a table instruction, mechanical procedure, or
      editorial note rather than spoken dialogue.
Render that beat as narration instead. Never invent an in-fiction reason the line
could have been said, and never keep it as a whisper, an aside, or a thought.

When and only when you do that, append after the narration, on its own final
line, one HTML comment quoting each reclassified span verbatim, in the order the
spans appeared in the source:

<!-- table-speech reclassified: "...span..." | "...span..." -->

Exactly one comment, listing every span; omit the line entirely when you
reclassified nothing. Nothing else may follow the prose.

This comment records that judgment ONLY. Condensing a fragment, conveying it
through narration, or omitting an incidental acknowledgment or a redundant
clarification is ordinary editorial work the brief already licenses — those are
never listed here.

The comment is the GM's review queue, not a correction and not a claim of
completeness: it exists so a human can check the calls you did make. Record what
you actually reclassified. Do not hunt for more, and do not add an entry to look
thorough.
