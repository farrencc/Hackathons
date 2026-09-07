"""
Extract EirGrid's dispatch-down reason codes into a tidy table.

The source sheet is laid out for humans: three side-by-side regional blocks
(All Island / Ireland / Northern Ireland), each split into volumes and
percentages, with the year written only on the first row it applies to. This
flattens all of that into one row per (year, month, region, metric).

Quarterly subtotal rows (Qtr1..Qtr4) are kept but flagged, so they can be
excluded from any sum -- adding them to the months would double-count.

Output: dispatch-down-by-reason-monthly.csv
"""
import csv
import re
import sys
from pathlib import Path

# This script lives in <folder>/scripts/. Paths are built from the folder above
# it, so the script runs correctly from any working directory.
FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
DATA = FOLDER / "data"
OUT_DIR = FOLDER / "script-output"

import openpyxl

SRC = DATA / "DD-Summary-Report-V21.xlsx"
OUT = OUT_DIR / "dispatch-down-by-reason-monthly.csv"
SHEET = "Wind & Solar Monthly Detailed"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
    rows = list(wb[SHEET].iter_rows(values_only=True))
    wb.close()

    region_row, header_row = rows[2], rows[3]

    # Region blocks start where row 3 names one, and run to the next such column.
    starts = [(j, clean(v)) for j, v in enumerate(region_row)
              if v and "Wind" in str(v)]
    bounds = []
    for k, (j, name) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(header_row)
        bounds.append((name, j, end))

    # Within a block, volume columns precede the "Percentages" marker.
    cols = []           # (region, metric, column index)
    for name, j0, j1 in bounds:
        pct = next((j for j in range(j0, j1)
                    if clean(region_row[j]).startswith("Percentages")), j1)
        for j in range(j0, pct):
            metric = clean(header_row[j])
            if metric:
                cols.append((name, metric, j))

    out, year = [], None
    for r in rows[4:]:
        if r[0] not in (None, ""):
            m = re.search(r"(19|20)\d{2}", str(r[0]))
            if m:
                year = m.group(0)
        label = clean(r[1])
        if not label or year is None:
            continue
        is_month = label in MONTHS
        if not (is_month or label.startswith("Qtr")):
            continue
        for region, metric, j in cols:
            v = r[j] if j < len(r) else None
            if v in (None, ""):
                continue
            try:
                val = float(v)
            except (TypeError, ValueError):
                continue
            out.append({
                "year": year,
                "period": label,
                "is_month": "yes" if is_month else "no",
                "region": region,
                "metric": metric,
                "mwh": round(val, 3),
            })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["year", "period", "is_month",
                                          "region", "metric", "mwh"])
        w.writeheader()
        w.writerows(out)

    years = sorted({r["year"] for r in out})
    regions = sorted({r["region"] for r in out})
    metrics = [m for _, m, _ in cols if _ == bounds[0][0]]
    print(f"wrote {OUT.name}: {len(out)} rows")
    print(f"years   : {years[0]} to {years[-1]} ({len(years)})")
    print(f"regions : {regions}")
    print(f"metrics : {sorted(set(m for _, m, _ in cols))}")
    return out


if __name__ == "__main__":
    main()
