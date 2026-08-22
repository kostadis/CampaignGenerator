"""013 Phase 5 fidelity gate — compare a batched extraction against the per-scene baseline.

Reads two scene_extractions directories plus the two quote-verification
reports produced over them, and prints (a) the verdict-table deltas and
(b) per-scene moment/quote counts IN REQUEST ORDER so tail thinning is
visible as a shape, not just a total.

Deterministic. Reads only; writes nothing.
"""
import re
import sys
from pathlib import Path

VERDICTS = ("verified", "near", "unverified", "unscored", "exempt")


def parse_report(path: Path) -> dict:
    """Pull the verdict table out of a quote_report.md."""
    counts = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*\**(\w+)\**\s*\|\s*(\d+)\s*\|", line)
        if m and m.group(1) in VERDICTS:
            counts[m.group(1)] = int(m.group(2))
    return counts


def scene_counts(d: Path) -> dict:
    """Per-scene (moments, quotes) from the `## Verbatim moments` section only.

    `## Scene summary` is human-authored gm-assist content copied verbatim by
    `format_scene_output` — counting it would compare the input to itself.
    """
    out = {}
    for f in sorted(d.glob("[0-9][0-9]_*.md")):
        text = f.read_text(encoding="utf-8")
        _, _, moments = text.partition("## Verbatim moments")
        n_moments = len(re.findall(r"^\*\*.+?\*\*", moments, re.M))
        n_quotes = len(re.findall(r'^>\s*"', moments, re.M))
        out[f.name] = (n_moments, n_quotes)
    return out


def pct(n, d):
    return f"{n / d:.1%}" if d else "n/a"


def main(base_dir, new_dir, base_report, new_report):
    base_dir, new_dir = Path(base_dir), Path(new_dir)
    b_counts = parse_report(Path(base_report))
    n_counts = parse_report(Path(new_report))
    b_total = sum(b_counts.values()) or 1
    n_total = sum(n_counts.values()) or 1

    print("=" * 72)
    print("QUOTE VERDICTS  (per-scene baseline -> batched)")
    print("=" * 72)
    print(f"{'verdict':<12} {'baseline':>18} {'batched':>18} {'delta (pts)':>14}")
    for v in VERDICTS:
        b, n = b_counts.get(v, 0), n_counts.get(v, 0)
        bs, ns = b / b_total, n / n_total
        flag = ""
        if v == "verified" and (ns - bs) * 100 < -5:
            flag = "   <-- GATE FAIL (>5pt exact-rate drop)"
        print(f"{v:<12} {b:>6} ({pct(b, b_total):>7}) {n:>6} ({pct(n, n_total):>7}) "
              f"{(ns - bs) * 100:>+13.1f}{flag}")
    print(f"{'TOTAL':<12} {b_total:>6} {'':>9} {n_total:>6}")

    print()
    print("=" * 72)
    print("PER-SCENE MOMENTS  (request order — watch the TAIL)")
    print("=" * 72)
    b_scenes, n_scenes = scene_counts(base_dir), scene_counts(new_dir)
    names = sorted(set(b_scenes) | set(n_scenes))
    print(f"{'scene':<34} {'base m/q':>10} {'batch m/q':>10} {'moment Δ':>10}")
    worst = []
    for name in names:
        bm, bq = b_scenes.get(name, (0, 0))
        nm, nq = n_scenes.get(name, (0, 0))
        d = (nm - bm) / bm if bm else 0.0
        flag = "  <-- >20% LOSS" if d < -0.20 else ""
        worst.append((name, d))
        print(f"{name[:34]:<34} {f'{bm}/{bq}':>10} {f'{nm}/{nq}':>10} "
              f"{d:>+9.0%}{flag}")
    bm_tot = sum(v[0] for v in b_scenes.values())
    nm_tot = sum(v[0] for v in n_scenes.values())
    print(f"{'TOTAL':<34} {bm_tot:>10} {nm_tot:>10} "
          f"{((nm_tot - bm_tot) / bm_tot if bm_tot else 0):>+9.0%}")

    # Tail check: is loss concentrated in the last third of request order?
    if len(worst) >= 3:
        k = max(1, len(worst) // 3)
        head = sum(d for _, d in worst[:-k]) / max(1, len(worst) - k)
        tail = sum(d for _, d in worst[-k:]) / k
        print()
        print(f"head mean Δ (first {len(worst)-k}): {head:+.0%}   "
              f"tail mean Δ (last {k}): {tail:+.0%}")
        # Tail thinning means the tail is LOSING, not merely gaining less.
        # Firing on (tail < head) alone flags a run where every scene
        # improved — a false positive that reads as a gate failure.
        if tail < -0.05 and tail < head - 0.15:
            print("  <-- TAIL THINNING: loss is concentrated at the end of the "
                  "request. This indicts batching specifically (the model "
                  "rationed effort across scenes), unlike a uniform drop.")
        else:
            print("  no tail concentration — any loss is spread across the run.")


if __name__ == "__main__":
    main(*sys.argv[1:5])
