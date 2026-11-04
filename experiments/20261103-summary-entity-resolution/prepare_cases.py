"""Freeze real summary references and draft gold separately from model input.

This reads an explicit source allowlist. It does not alter summaries or resolve
canon. Gold is a researcher's source-based expectation, not a GM ruling.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path


SOURCES = {
    "c03": "summaries/2025-05-28-chapter_03/session-summary.md",
    "c04": "summaries/2025-06-03-chapter_04/session-summary.md",
    "c05": "summaries/2025-06-18-chapter_05-to-find-a-shapeshifter/session-summary.md",
    "c18": "summaries/2025-10-01-chapter_18-freeing-big-al-petunia-and-watching-a-ranch-burn/session-summary.md",
    "c39": "summaries/2026-04-07-chapter_39-a-dragon-defeated-a-bard-tempted-a-barbarians-vengeance/session-summary.md",
    "c42": "summaries/2026-04-29-chapter_42-the-charge-of-the-light-brigade/session-summary.md",
    "c46": "summaries/2026-05-26-chapter_46-the-aasimar-has-landed/session-summary.md",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def explicit_targets(payload):
    """Render exact spans for models without asking them to count characters."""
    result = deepcopy(payload)
    for reference in result['references']:
        text = result['passages'][reference['passage']]['text']
        start, end = reference['start'], reference['end']
        reference['surface'] = text[start:end]
        reference['marked_excerpt'] = (text[max(0,start-160):start] + '[[TARGET]]' +
                                       text[start:end] + '[[/TARGET]]' + text[end:end+160])
    return result


def prepare(campaign_root):
    texts = {key: (campaign_root / path).read_text() for key, path in SOURCES.items()}
    hashes = {path: sha((campaign_root / path).read_bytes()) for path in SOURCES.values()}
    refs, passages, cases, gold = [], {}, [], []

    def ref(key, anchor, surface):
        text = texts[key]
        pos = text.index(anchor)
        offset = anchor.index(surface)
        start, end = pos + offset, pos + offset + len(surface)
        # Raw surrounding paragraph/block. No hand-labeled location or identity features.
        before = text.rfind("\n\n", 0, pos)
        pstart = 0 if before == -1 else before + 2
        after = text.find("\n\n", pos + len(anchor))
        pend = len(text) if after == -1 else after
        pid = "p" + sha(f"{key}:{pstart}:{pend}".encode())[:10]
        passages[pid] = {"chapter": int(key[1:]), "text": text[pstart:pend]}
        rid = "r" + sha(f"{key}:{start}:{end}".encode())[:10]
        item = {"id": rid, "passage": pid, "start": start-pstart, "end": end-pstart}
        if not any(r["id"] == rid for r in refs):
            refs.append(item)
        assert passages[pid]["text"][item["start"]:item["end"]] == surface
        return rid, {"id": rid, "path": SOURCES[key], "source_sha256": hashes[SOURCES[key]],
                     "source_start": start, "source_end": end,
                     "source_line": text.count("\n", 0, start)+1, "surface": surface,
                     "passage_start": pstart, "passage_end": pend}

    evidence = {}
    def R(key, anchor, surface):
        rid, provenance = ref(key, anchor, surface)
        evidence[rid] = provenance
        return rid

    hills = R("c04", "The source turned out to be a wandering ogre.", "ogre")
    pass_ogre = R("c04", "A second ogre blocked their path", "ogre")
    previous = R("c04", "loads the walloping ammunition recovered from the previous ogre and fires", "ogre")
    current = R("c04", "the ogre must make a DC 10 strength save", "ogre")
    sequel = R("c05", "The ogre is prone on the ground under the sun.", "ogre")
    orc_two_a = R("c04", "Soma retaliates by using Thorn Whip on orc two", "orc two")
    orc_two_b = R("c04", "Orc two, now prone, stands and charges Brewbarry", "Orc two")
    orc_one = R("c04", "Orc one swings a greataxe at point-blank range", "Orc one")
    canyon = R("c04", "The group loots the fallen orcs:", "orcs")
    ranch = R("c18", "fresh wounds on the orc bodies were ripped and mangled", "orc")
    allied = R("c46", "The allied orcs, inspired by the turning tide", "orcs")
    enemy = R("c46", "overwhelmed several of the cultist orcs in brutal melee", "orcs")
    hired = R("c46", "convinced three orcs to start working for Falcon at the lodge", "orcs")
    stewards = R("c46", "Falcon immediately addressed them as stewards", "stewards")
    three = R("c42", "while the three orcs influenced by Vukradin remained neutral and hesitant", "orcs")
    hostile = R("c42", "Yargath and the still-hostile orcs into attacking", "orcs")
    approaching = R("c42", "ten hulking orcs crested the opposite ridge", "orcs")
    garbled = R("c03", "clearing out these ogres [transcript garble for “oozes”]", "ogres")
    ranch_ogres = R("c18", "three large figures lumbered out of the farmhouse: rot-tusk ogres", "ogres")
    dead_orcs = R("c18", "orcs raided the farm first, and then the rot-tusk ogres", "orcs")
    lodge_scope = R("c39", "orcs at the Shrine of Savras and Falcon’s Lodge", "Falcon’s Lodge")
    shrine_scope = R("c39", "orcs at the Shrine of Savras and Falcon’s Lodge", "Shrine of Savras")

    def case(a, b, relation, rationale, *, strict=True, focus=None):
        qid = f"q{len(cases)+1:02}"
        item = {"id": qid, "left": a, "right": b}
        if focus:
            item["focus"] = focus
        cases.append(item)
        gold.append({"id": qid, "relation": relation, "rationale": rationale,
                     "strict_source_expectation": strict})

    case(hills, pass_ogre, "distinct_referents", "A killed wandering ogre and an explicitly second ogre are distinct individuals.")
    case(hills, previous, "same_referent", "The previous ogre is the earlier ammunition source, not the current target.")
    case(previous, current, "distinct_referents", "One sentence refers both to the prior ammunition donor and the current living target.")
    case(pass_ogre, sequel, "same_referent", "The prone unfinished mountain-pass fight resumes with Valphine's next action; cross-chapter continuity is strongly supported but not an explicit stable ID.", strict=False)
    case(orc_two_a, orc_two_b, "same_referent", "Same numbered combatant within the same encounter.")
    case(orc_one, orc_two_a, "distinct_referents", "Different numbered combatants within the same encounter.")
    case(canyon, ranch, "separate_scope", "Different encounter/location scopes; this alone is not a universal proof of disjoint tribe membership.")
    case(allied, enemy, "distinct_referents", "Explicit opposing sides in the same battle; location alone does not separate them.")
    case(hired, stewards, "same_referent", "The three recruited orcs are immediately addressed as stewards.")
    case(three, approaching, "overlap_or_membership", "Three hesitant orcs are a subset of the ten arrivals, not the whole group.")
    case(three, hostile, "distinct_referents", "The three hesitant orcs are contrasted with still-hostile orcs at this moment.")
    case(garbled, hills, "corrected_nonreferent", "The source explicitly corrects ogres to oozes; do not create an ogre entity from the mistaken surface.")
    case(ranch_ogres, hills, "distinct_referents", "Living ogres seeking revenge for earlier slain ogres are not the earlier slain individual.")
    case(ranch, dead_orcs, "same_referent", "The observed mangled orc corpses and Big Al's account concern the same ranch raid group.", strict=False)
    case(shrine_scope, lodge_scope, "separate_scope", "Two explicitly coordinated location scopes; individual identities or shared tribal membership are not supplied.", focus="Compare the respective orc occupants associated with these two marked locations, not the locations as entities.")
    case(hired, allied, "ambiguous", "The passage does not enumerate exactly which three orcs were recruited or prove identity with the entire allied group; avoid equality.", strict=False)
    return {"passages": passages, "references": refs, "cases": cases}, gold, evidence, hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--offset-only", action='store_true', help='reproduce the initial weaker target presentation')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    payload, gold, evidence, hashes = prepare(args.campaign_root)
    if not args.offset_only:
        payload = explicit_targets(payload)
    for name, value in (("payload.json", payload), ("gold.json", gold),
                        ("reference_provenance.json", evidence), ("input_hashes.json", hashes)):
        (args.out/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n")
    (args.out/'registration.json').write_text(json.dumps({
        'gold_sha256': sha((args.out/'gold.json').read_bytes()),
        'payload_sha256': sha((args.out/'payload.json').read_bytes()),
        'input_hashes_sha256': sha((args.out/'input_hashes.json').read_bytes()),
        'status': 'draft source-based expectations frozen before model calls; not GM rulings',
    }, indent=2)+'\n')
    print(json.dumps({"source_files": len(hashes), "passages": len(payload['passages']),
                      "references": len(payload['references']), "cases": len(gold),
                      "payload_characters": len(json.dumps(payload, ensure_ascii=False)),
                      "gold_sha256": sha((args.out/'gold.json').read_bytes())}))


if __name__ == "__main__":
    main()
