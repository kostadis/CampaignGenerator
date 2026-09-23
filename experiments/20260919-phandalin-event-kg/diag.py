import sqlite3, re, json, pathlib
from collections import defaultdict
db = sqlite3.connect(pathlib.Path(__file__).parent / "phandalin_kg.sqlite3")
R = lambda s,*a: db.execute(s,a).fetchall()
line = lambda t: print("\n" + "="*68 + f"\n{t}\n" + "="*68)

line("8.7  CHAPTER NUMBER IS NOT A KEY")
for s,o,c,t,d in R("SELECT sess,ord,chapter,title,date_raw FROM sessions WHERE chapter IN (SELECT chapter FROM sessions GROUP BY chapter HAVING COUNT(*)>1)"):
    print(f"  ord {o:>3}  file {s:<5} chapter {c:<3} {d!s:<14} {t}")
print(f"  distinct chapters {R('SELECT COUNT(DISTINCT chapter) FROM sessions')[0][0]} for {R('SELECT COUNT(*) FROM sessions')[0][0]} sessions")

line("8.6  DATE AXIS IS NOT SORTABLE")
for k,n in R("SELECT date_kind,COUNT(*) FROM sessions GROUP BY date_kind ORDER BY 2 DESC"):
    ex = R("SELECT date_raw,sess FROM sessions WHERE date_kind=? AND date_raw IS NOT NULL LIMIT 2",k)
    print(f"  {k:<10}{n:>3}   e.g. " + "; ".join(f"{d} ({s})" for d,s in ex))
print("\n  ordering by date_raw DESC (what a date-keyed KG would call 'most recent'):")
for d,s,o in R("SELECT date_raw,sess,ord FROM sessions ORDER BY date_raw DESC LIMIT 4"):
    print(f"    {d!s:<26} -> session {s} (ordinal {o} of 53)")
print("  ordering by ordinal DESC (correct):")
for s,o,t in R("SELECT sess,ord,title FROM sessions ORDER BY ord DESC LIMIT 2"):
    print(f"    session {s} (ordinal {o}) — {t}")

line("8.9  MONOLITHIC SECTIONS DEFEAT EMBEDDING LOOKUP")
tot = defaultdict(int); cnt = defaultdict(int)
for sess,sec,ch in R("SELECT sess,section,chars FROM snapshots"):
    tot[(sess,sec)] += ch; cnt[(sess,sec)] += 1
worst = sorted(tot.items(), key=lambda kv:-kv[1])[:5]
for (sess,sec),ch in worst:
    print(f"  {sess} ## {sec:<10}{ch:>7} chars across {cnt[(sess,sec)]:>3} entries  (one embedding per section if unsplit)")
whole = R("SELECT sess,SUM(chars) FROM snapshots GROUP BY sess ORDER BY 2 DESC LIMIT 1")[0]
print(f"  largest whole-session state block: {whole[0]} = {whole[1]:,} chars")

line("8.2  HEADING DRIFT (resolved vs raw)")
d = defaultdict(set)
for e,rh in R("SELECT entity,raw_head FROM snapshots"): d[e].add(rh)
multi = {k:v for k,v in d.items() if len(v)>1}
print(f"  entities whose snapshots arrive under >1 raw heading: {len(multi)}")
for k,v in sorted(multi.items(), key=lambda kv:-len(kv[1]))[:12]:
    print(f"    {k:<34} {sorted(v)}")
print(f"\n  raw distinct headings {len(set(x for v in d.values() for x in v))} -> resolved entities {len(d)}")

line("8.1  SNAPSHOT LAG — latest snapshot older than latest mention")
lastsnap = dict(R("SELECT entity,MAX(as_of_ev) FROM snapshots GROUP BY entity"))
lastment = dict(R("SELECT entity,MAX(ev) FROM mentions GROUP BY entity"))
both = [(e,lastsnap[e],lastment[e]) for e in lastsnap if e in lastment]
lag = sorted([(e,s,m,m-s) for e,s,m in both if m>s], key=lambda x:-x[3])
print(f"  {len(lag)} of {len(both)} entities with both ({100*len(lag)//max(len(both),1)}%) are stale")
print(f"  {'entity':<32}{'snap@ev':>8}{'ment@ev':>9}{'lag':>7}")
for e,s,m,g in lag[:15]:
    print(f"  {e:<32}{s:>8}{m:>9}{g:>7}")

line("8.3 / 8.5  REGISTRY NAMES THAT NEVER APPEAR IN PLAY")
ment = set(lastment)
import yaml
allents=[]
reg = open("/home/kostadis/phandalin/Phandalin/docs/entity_registry.yaml").read()
y = yaml.safe_load(reg)
for ent in y["entities"]:
    allents.append((ent["name"], ent.get("type"), ent.get("aliases") or []))
zero = [(n,t) for n,t,a in allents if n not in ment]
bytype = defaultdict(int)
for n,t in zero: bytype[t]+=1
print(f"  {len(zero)} of {len(allents)} registry entities have ZERO mentions in any scene")
for t,n in sorted(bytype.items(), key=lambda kv:-kv[1]): print(f"    {t:<12}{n:>4}")
print("  sample npc/faction with zero mentions (module or planning imports):")
for n,t in [z for z in zero if z[1] in ("npc","faction")][:14]: print(f"    [{t}] {n}")
