# Step 3A — Multi-line conflict analysis — Harshitha

Case: WP2033, all-island (Person 1's `binding_lines.csv` case). 218 candidate
buses (wind/solar hosts, one row per bus not per generator — same convention
as Person 2's matrix) x 6 monitored lines from `binding_lines.csv`. Script:
`p_multi_line_conflicts.py`, one command, reproducible (see its own header
comment for the full method). Output: `multi_line_conflicts.csv`, two figures.

## What this step needed that wasn't in the hand-off files

Person 2's `shift_factor_matrix.csv` gives a signed shift factor per (node,
line) — positive means "more generation here increases flow toward bus1."
That tells you *how much* a node is electrically coupled to a line, and in
*which direction*. It does not by itself tell you whether that's good or bad
for that line, because that depends on which direction the line is actually
loaded when it binds. So before classifying anything, this script pulls
Person 1's `baseline_hourly_flows.csv` and checks the signed flow during each
monitored line's own binding hours (loading >= 99.9%, the same definition
`binding_lines.csv` itself uses). All six lines turned out to bind in one
consistent direction only — confirmed, not assumed, the script raises an
error if a line doesn't. That gives a real "worsens vs. relieves" label per
(node, line): same sign as the binding-hour flow = worsens it, opposite sign
= relieves it. Magnitude (|shift factor|) says how strongly a node is
coupled to a line; sign says which way — you need both, and using magnitude
alone is the same mistake already flagged twice elsewhere in this repo (Track
A's unsigned "Corderry offers 43 MW" line, and the abs-shift-factor
comparison in Alex's Q6 headline number). This step's classification uses
both throughout.

## Materiality and weighting choices

**Materiality: top 10% of |shift factor|, computed separately per line, not
one fixed cutoff across all six.** Mean |SF| ranges from 0.0046 on one line
to 0.060 on another — over 10x apart — so a single fixed threshold would
mostly just measure which lines happen to have larger shift factors, not
which nodes actually matter for each one. This matches the brief's own
"relative threshold ... often safer" guidance.

**Weighting: overload_hours, not total_overload_MWh.** `binding_lines.csv`'s
`total_overload_MWh` and `max_overload_MW` are ~0 for every line (1e-10 to
1e-13 MW — solver noise, not a data problem) — a DC-approximated network
with `n.optimize()`/`n.lpf()` can't produce flow past the rating, so "MW over
the limit" never has anything real to read off. Same trap already flagged in
this project's Q2/Q4 work on `hourly_flows.csv`. `overload_hours` is the only
one of the three ranking metrics that's actually nonzero and meaningful here,
so it's what weights the influence score below.

## Results

132 of 1,308 (node, line) pairs are material (10.1%, by construction of the
per-line 10% threshold). Classification of all 218 candidate nodes:

| classification | count |
|---|---:|
| low-influence node | 127 |
| single-line relief node | 30 |
| single-line worsening node | 23 |
| trade-off node | 20 |
| multi-line worsening node | 18 |
| **multi-line relief node** | **0** |

**The headline finding: zero nodes relieve two or more monitored lines
without also worsening at least one other.** Every node that materially
helps more than one binding line, in this dataset, also materially hurts at
least one other binding line. There is no free multi-line win available —
any node worth curtailing (or protecting) for one constraint needs checking
against the others before calling it a clean fix.

20 genuine trade-off nodes — material and opposite-effect on at least two
different monitored lines. The largest by influence score: Letterkenny,
Sorne Hill, and Trillick (all worsen `3581-89516-1`, the all-island system's
single worst line by overload hours, while relieving `1122-11260-1`), and
Cathaleen's Fall (worsens `3581-89516-1`, relieves both `1122-11260-1` and
`3691-4041-1` — the only node material on all three at once).

**Several names carry over directly from the north-west target line in
this project's earlier Q1–Q6 work** — Corderry, Glenree, Binbane,
Ardnagappary, Tievebrack, Croaghonagh all appear here too, now in the
all-island trade-off list, worsening `3581-89516-1` while relieving
`3691-4041-1` or `1122-11260-1`. That's worth a line in the deck: a
farm that looked like a clean "attractive for new wind" pick from the
north-west-only view (positive shift factor on the local target line, e.g.
Corderry/Glenree) can still be a trade-off node once the full-grid picture
is in view — the region-scoped and all-island-scoped answers aren't
interchangeable, and Section 3.2's whole point (non-local effects) shows up
concretely right here.

18 multi-line worsening nodes, topped by Arklow_Off (worsens all three of
`1122-11260-1`, `1122-1742-1`, and `3082-3122-1` at once — the only node
material and same-direction on three lines simultaneously). The rest of the
group worsens the same pair, `1122-1742-1` and `3082-3122-1` together — both
lines sit on the same corridor, so a cluster of Wicklow-area nodes (Arklow,
Banoge, Tullabeg, Castledockre, Lodgewood, Crory and others) shows up
worsening both together rather than just one.

## Files

- **`p_multi_line_conflicts_map.html`** — the map version: an island-of-
  Ireland map (React, all-island outline built from Natural Earth
  boundaries since the six monitored lines span both ROI and NI) where
  clicking any of the 6 monitored lines colors every wind/solar node by
  effect — red circle = worsens the line (curtailing it relieves the
  line), blue diamond = relieves it (curtailing it would make the line
  worse), small grey dot = below the materiality threshold for that line.
  Shape doubles the color coding so it isn't color-only. Marker size
  scales with effect strength; hovering or clicking a node opens a detail
  panel with its effect on all six lines at once (the trade-off view).
  166 of 218 candidate nodes have geocoded coordinates and are plotted;
  the other 52 are listed in an on-page panel, flagged when they're
  material to the selected line, rather than silently dropped. Two of the
  six lines (`1122-11260-1` at GLENART, `3691-4041-1` at LAGHTANVACK) have
  one ungeocoded endpoint — the map shows the known endpoint plus a "?"
  stub marker rather than failing to draw the line. Self-contained
  HTML, loads React/ReactDOM from cdnjs, no build step — opens in any
  browser or a GitHub Pages link. Published for live
  browsing/sharing at
  https://claude.ai/code/artifact/ea8a1a9d-2446-41cb-8a37-24d83bc949fe
  (republish that page if this file changes).
- `p_multi_line_conflicts_interactive.html` — the earlier bar-chart
  version of the same interaction (click a line, see a diverging bar
  chart of who worsens/relieves it, plus the sortable trade-off table)
  — kept in the repo since it's a faster way to compare exact shift-factor
  magnitudes across many farms than the map is. Same underlying data as
  the map version.
- `multi_line_conflicts.csv` — all 218 nodes: `node_id, node_name,
  material_line_count, lines_worsened, lines_relieved, tradeoff_flag,
  weighted_influence_score, classification`.
- `p_multi_line_conflicts_heatmap_WP2033_all-island.png` — the static
  version of the same signed shift-factor data, top 40 nodes x the 6
  monitored lines, diverging red/blue — kept for the deck/slides, where a
  static image is more practical than a live page. Use the interactive
  page above for exploring the data or for Q&A.
- `p_multi_line_conflicts_top20_WP2033_all-island.png` — ranked bar chart,
  top 20 nodes by weighted influence score, colored by classification.

## Quality gate (matches the checks the team has been running throughout)

- Every monitored line's binding-hour flow confirmed single-direction before
  any worsen/relieve label was assigned (script raises an error otherwise —
  none did).
- `node_id` unique in the output; every node has exactly 6 rows in the input
  matrix (one per monitored line) — no missing or duplicated bus-line pairs.
- Language: nodes are described as having "high modelled sensitivity" or
  "strong influence," never as "responsible" or "bad" for a constraint —
  this is a screening classification, not a judgment, per the brief's own
  guidance for this step.
- Not done here, flagged for Person 4 / Person 5: this step used a fixed 10%
  per-line materiality cutoff, chosen to match the brief's own "relative
  threshold" recommendation, not fitted or swept. Worth a quick sensitivity
  check (e.g. top 5% / top 20%) before the group-generation step locks in on
  a specific node list, since the trade-off count in particular could shift
  with the cutoff.
