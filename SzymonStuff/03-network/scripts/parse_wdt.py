"""
Parse EirGrid's Wind Dispatch Tool Constraint Group Overview (1 Feb 2024, 74pp)
into a machine-readable group -> stations table.

The station tables in the PDF are laid out in two columns, so a station name
containing a space ("Sorne Hill") is indistinguishable from two names sitting
side by side ("Brockaghboy Lisaghmore") if you only have the text. We therefore
use word x-positions: words are grouped into rows by their y-centre, then split
into a left and right column at the midpoint of the observed x-range.

Output: constraint-groups-to-stations.csv  (one row per group-station pair)
"""

from pathlib import Path

# This script lives in <folder>/scripts/. Paths are built from the folder above
# it, so the script runs correctly from any working directory.
FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
DATA = FOLDER / "data"
OUT_DIR = FOLDER / "script-output"
import csv
import re
import pdfplumber

PDF = str(DATA / "WDT-Constraint-Group-Overview.pdf")
OUT = str(OUT_DIR / "constraint-groups-to-stations.csv")

# Group definitions run to page 65; Appendix 1 onward explains the WDT setpoint
# calculation and its worked tables leak words like "Permissible"/"Head Room".
FIRST_PAGE, LAST_PAGE = 9, 65

# Section headings that open a constraint group, e.g.
#   "2.1  Constraint Group number 1 - NW Northern"
#   "3.1  North West Constraint Group 1: Letterkenny A1 Busbar Flows"
HEAD = re.compile(r"^(\d+)\.(\d+)\s+(.*constraint\s+group.*)$", re.I)

# EirGrid numbers South West groups 1, 2, 3a, 3b, 3c, 4 ... 11, so the subsection
# index (5.4) is NOT the group number (3b). Always read the label from the title.
LABEL = re.compile(r"constraint\s+group\s+(?:number\s+)?([0-9]+[a-c]?)", re.I)

REGION = {2: "NI", 3: "ROI-NW", 4: "ROI-W", 5: "ROI-SW",
          6: "ROI-SE", 7: "ROI-NE", 8: "ROI-ALL"}

# Words that never appear in an Irish transmission station name, but do appear
# in the headings, figure captions and table titles that sit alongside them.
# Word-set membership rather than a regex: no escaping to get wrong.
STOP_WORDS = {
    "flow", "flows", "output", "group", "groups", "transformer", "available",
    "total", "active", "power", "ireland", "busbar", "line", "lines",
    "stability", "limit", "voltage", "kv", "farm", "wind", "generation",
    "constraint", "dispatch", "figure", "table", "section", "appendix", "of",
    "in", "the", "and", "to",
}


def is_stopword_fragment(cell):
    """True if any token is a heading word, so the cell is not a station name."""
    return any(t.strip(".,:;'").lower() in STOP_WORDS for t in cell.split())


# Lines that are structure, not station names.
# Words that never appear in an Irish transmission station name but do appear
# in the surrounding headings, figure captions and table titles.

NOISE = re.compile(
    r"^(station|wind dispatch tool|page \d+ of|figure \d+|table \d+|"
    r"intact network|temporary group|outage condition|sample outages|"
    r"this constraint group|under certain|.*constraint group.*)",
    re.I)


def rows_with_columns(page):
    """Yield text rows, splitting each into left/right column cells."""
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    if not words:
        return
    lines = {}
    for w in words:
        key = round(w["top"] / 4.0)          # ~4pt tolerance groups a visual row
        lines.setdefault(key, []).append(w)
    for key in sorted(lines):
        ws = sorted(lines[key], key=lambda w: w["x0"])
        yield ws


COL_GAP = 20.0   # pt; measured separation is 166-187 between columns, 3.1 within a name


def split_columns(ws):
    """Split one visual row into cells wherever a wide horizontal gap appears."""
    cells, cur = [], [ws[0]]
    for prev, w in zip(ws, ws[1:]):
        if w["x0"] - prev["x1"] > COL_GAP:
            cells.append(cur)
            cur = [w]
        else:
            cur.append(w)
    cells.append(cur)
    return [" ".join(x["text"] for x in c).strip() for c in cells]


def clean(s):
    s = s.replace("\u2019", "'").replace("\ufffd", "'").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def main():
    records = []          # (group_id, region, group_name, context, station)
    registry = {}         # every group heading seen, station table or not
    current = None        # dict describing the group we are inside
    context = "intact"

    with pdfplumber.open(PDF) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            if pno < FIRST_PAGE:               # front matter + contents
                continue
            if pno > LAST_PAGE:                # appendices, not group definitions
                break
            for ws in rows_with_columns(page):
                full = clean(" ".join(w["text"] for w in ws))
                if not full:
                    continue

                m = HEAD.match(full)
                if m:
                    chap = int(m.group(1))
                    if chap in REGION:
                        lm = LABEL.search(m.group(3))
                        label = lm.group(1) if lm else m.group(2)
                        current = {
                            "id": f"{REGION[chap]}/{label}",
                            "region": REGION[chap],
                            "name": clean(m.group(3)),
                            "page": pno,
                        }
                        # Register even if it turns out to have no station table
                        # ("All NI" and "All IE" cover every farm, so list none).
                        registry.setdefault(current["id"], current)
                        context = "intact"
                    continue

                if current is None:
                    continue

                low = full.lower()
                if low.startswith("outage condition") or "temporary group" in low:
                    context = "outage"
                    continue
                if low.startswith("intact network"):
                    context = "intact"
                    continue
                if NOISE.match(full):
                    continue

                for cell in split_columns(ws):
                    cell = clean(cell)
                    if not cell or NOISE.match(cell):
                        continue
                    # Station names: short, alphabetic, no sentence punctuation.
                    if len(cell) > 34 or cell.endswith((".", ":", ";", ",")):
                        continue
                    if not re.match(r"^[A-Z][A-Za-z'\- ]+$", cell):
                        continue
                    if len(cell.split()) > 3:
                        continue
                    # Heading and caption fragments that pass the shape tests
                    # ("Transformer Flows", "Total Output of", "Active Power").
                    if is_stopword_fragment(cell):
                        continue
                    records.append((current["id"], current["region"],
                                    current["name"], context, cell, current["page"]))

    # de-duplicate, preserving order
    seen, uniq = set(), []
    for r in records:
        k = (r[0], r[3], r[4])
        if k not in seen:
            seen.add(k)
            uniq.append(r)

    have = {r[0] for r in uniq}
    for gid, g in registry.items():
        if gid not in have:
            uniq.append((gid, g["region"], g["name"], "all-generation", "", g["page"]))

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group_id", "region", "group_name", "context", "station", "pdf_page"])
        w.writerows(uniq)

    groups = sorted({r[0] for r in uniq})
    print(f"wrote {OUT}: {len(uniq)} group-station pairs across {len(groups)} groups")
    return uniq, groups


if __name__ == "__main__":
    main()
