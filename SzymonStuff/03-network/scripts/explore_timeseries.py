"""
Assess the time-series sheets of the Ireland network model.

The model ships seven ts_* sheets covering July 2025 at half-hourly resolution.
This reports what is actually in them -- how much varies, how much is constant,
and what the wind fleet looks like -- so the simulation inputs are understood
before anything is built on them.

Writes a per-generator July summary to model-generators-july2025.csv.
"""
import csv
import sys
from pathlib import Path

# This script lives in <folder>/scripts/. Paths are built from the folder above
# it, so the script runs correctly from any working directory.
FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
DATA = FOLDER / "data"
OUT_DIR = FOLDER / "script-output"

import openpyxl

SRC = DATA / "ireland_case_july2025.xlsx"
OUT = OUT_DIR / "model-generators-july2025.csv"


def sheet_stats(ws, label):
    """Read a wide ts_ sheet and report variability per column."""
    it = ws.iter_rows(values_only=True)
    hdr = list(next(it))
    cols = hdr[1:]
    mins = [None] * len(cols)
    maxs = [None] * len(cols)
    sums = [0.0] * len(cols)
    n = 0
    for r in it:
        if r[0] is None:
            continue
        n += 1
        for j, v in enumerate(r[1:len(cols) + 1]):
            try:
                x = float(v)
            except (TypeError, ValueError):
                continue
            sums[j] += x
            if mins[j] is None or x < mins[j]:
                mins[j] = x
            if maxs[j] is None or x > maxs[j]:
                maxs[j] = x
    varying = sum(1 for a, b in zip(mins, maxs)
                  if a is not None and b is not None and b - a > 1e-9)
    print(f"  {label:<10} {n:>5} periods x {len(cols):>4} columns   "
          f"{varying:>4} vary, {len(cols)-varying:>4} constant")
    return hdr, mins, maxs, sums, n


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
    print("Time-series sheets (July 2025, half-hourly):")
    stats = {}
    for s in ("ts_PD", "ts_PGUB", "ts_PGLB", "ts_Lmax", "ts_TLmax", "ts_bid"):
        stats[s] = sheet_stats(wb[s], s)

    # Generator metadata, to interpret ts_PGUB.
    rows = list(wb["generator"].iter_rows(values_only=True))
    gh = list(rows[0])
    meta = {}
    for r in rows[1:]:
        meta[str(r[gh.index("name")]).strip()] = {
            "desc": " ".join(str(r[gh.index("description")] or "").split()),
            "fuel": str(r[gh.index("FuelType")]).lower(),
            "bus": str(r[gh.index("busname")] or ""),
            "groups": str(r[gh.index("prorata_groups")] or ""),
        }
    wb.close()

    hdr, mins, maxs, sums, n = stats["ts_PGUB"]
    out = []
    for j, name in enumerate(hdr[1:]):
        m = meta.get(str(name).strip())
        if not m:
            continue
        out.append({
            "gen_id": name, "description": m["desc"], "fuel": m["fuel"],
            "bus": m["bus"], "prorata_groups": m["groups"],
            "pmax_mw": round(maxs[j] or 0, 3),
            "mean_mw": round(sums[j] / n, 3) if n else 0,
            "capacity_factor": round((sums[j] / n) / maxs[j], 4) if maxs[j] else "",
        })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    wind = [r for r in out if r["fuel"] == "wind"]
    solar = [r for r in out if r["fuel"] == "solar"]
    print(f"\nwrote {OUT.name}: {len(out)} generators")
    print(f"\nJuly 2025 in the model:")
    for lab, grp in (("wind", wind), ("solar", solar)):
        if not grp:
            continue
        cap = sum(r["pmax_mw"] for r in grp)
        mean = sum(r["mean_mw"] for r in grp)
        print(f"  {lab:<6} {len(grp):>3} units   peak {cap:>7.0f} MW   "
              f"mean {mean:>6.0f} MW   fleet CF {mean/cap:.3f}")
    return out


if __name__ == "__main__":
    main()
