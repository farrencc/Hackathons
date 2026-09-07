"""
Flatten EirGrid's quarter-hourly all-island system data.

The useful structure in this file is that it carries wind AVAILABILITY and wind
GENERATION separately. Their difference is dispatch-down, at 15-minute
resolution -- far finer than the monthly reason-code tables, though without the
reason attached. It also carries the live SNSP series and interconnector flows.

Output: system-state-15min-2026.csv  (a straight tidy dump, one row per timestamp)
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

SRC = DATA / "System-Data-Qtr-Hourly-2026-V7.xlsx"
OUT = OUT_DIR / "system-state-15min-2026.csv"

KEEP = ["DateTime", "IE Demand", "IE Wind Availability", "IE Wind Generation",
        "NI Wind Availability", "NI Wind Generation",
        "AI Demand", "AI Wind Availability", "AI Wind Generation",
        "AI Solar Availability", "AI Solar Generation",
        "Moyle I/C", "EWIC I/C", "Greenlink I/C",
        "AI Oversupply", "SNSP"]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
    it = wb["System Data"].iter_rows(values_only=True)
    hdr = list(next(it))
    idx = {c: hdr.index(c) for c in KEEP if c in hdr}

    rows = []
    for r in it:
        if not r[0] or not str(r[0]).startswith("20"):
            continue
        rec = {}
        for c, j in idx.items():
            v = r[j]
            if c == "DateTime":
                rec[c] = str(v)
            else:
                try:
                    rec[c] = float(v)
                except (TypeError, ValueError):
                    rec[c] = ""
        rows.append(rec)
    wb.close()

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(idx))
        w.writeheader()
        w.writerows(rows)

    def col(c):
        return [r[c] for r in rows if isinstance(r.get(c), float)]

    ai_av, ai_gen = col("AI Wind Availability"), col("AI Wind Generation")
    dd = [a - g for a, g in zip(ai_av, ai_gen) if a >= g]
    snsp = col("SNSP")

    print(f"wrote {OUT.name}: {len(rows)} rows, {rows[0]['DateTime']} to {rows[-1]['DateTime']}")
    print(f"\nAll-island wind, Jan-Jul 2026 (quarter-hourly):")
    print(f"  availability mean : {sum(ai_av)/len(ai_av):>8.0f} MW")
    print(f"  generation   mean : {sum(ai_gen)/len(ai_gen):>8.0f} MW")
    print(f"  implied dispatch-down : {100*sum(dd)/sum(ai_av):>5.1f}% of available wind")
    # SNSP is stored as a fraction (0.6375), not a percentage.
    snsp = [x * 100 for x in snsp]
    s = sorted(snsp)
    print(f"\nSNSP (operational limit is 75%):")
    print(f"  mean {sum(snsp)/len(snsp):.1f}%   median {s[len(s)//2]:.1f}%"
          f"   min {s[0]:.1f}%   max {s[-1]:.1f}%")
    for t in (60, 65, 70, 74):
        print(f"  periods above {t}% : {100*sum(1 for x in snsp if x > t)/len(snsp):>5.1f}%")

    for ic in ("Moyle I/C", "EWIC I/C", "Greenlink I/C"):
        v = col(ic)
        if v:
            print(f"\n{ic}: mean {sum(v)/len(v):+.0f} MW, range {min(v):+.0f} to {max(v):+.0f} MW"
                  f"  ({100*sum(1 for x in v if abs(x) > 1)/len(v):.0f}% of periods active)")
    return rows


if __name__ == "__main__":
    main()
