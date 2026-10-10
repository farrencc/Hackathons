# Step 1 — Full-grid baseline and binding-line identification (complete summary)

Owner role: Person 1. This is the foundation step for the whole pipeline:
every later step (shift-factor matrix, candidate group generation) only
looks at the specific transmission lines this step identifies as
constrained, so its correctness and scope decisions shape everything built
on top of it.

## Purpose

Ireland's transmission grid has hundreds of lines, each with a maximum
safe carrying capacity (its "rating," in MVA/MW). On any given day, the
mix of generation and demand determines how much power flows down each
line. Most lines never come close to their limit; a small number
occasionally get pushed right up against it. This step's job is to run a
realistic full-grid simulation across an entire representative week, find
out which specific lines actually get constrained at some point during
that week, and rank them — producing the definitive list of "binding
lines" that the rest of the project's congestion-relief work targets.

Network: `WP2033` (2033 winter peak). Scope: **all-island** — every line
on the island, not just the 15-node `north-west` region the rest of this
project otherwise focuses on. That's a deliberate choice, not an
oversight: Track A's own earlier audit found that the north-west's own
target bottleneck line doesn't even appear in the all-island top-5 view,
so a full-grid pass needed its own independent run rather than assuming
the north-west line still mattered at a national level.

Script: `n_binding_lines_baseline.py`, run end-to-end against the real
`gridkit.py` and `networks/` data in the team repository — not just
syntax-checked.

```bash
python examples/n_binding_lines_baseline.py WP2033 all-island overload_hours 15
```

## Method

1. **Load the all-island network and apply the one real weather-derived
   rating that exists.** This project has a genuine, Met Éireann-derived
   seasonal Dynamic Line Rating (DLR) for exactly one line so far
   (`5041-17010-2`) — not for the other ~754 lines, since that would need
   a weather station mapped to every line, which hasn't been done. This
   script applies `gridkit.set_rating()` with that real rating (213.0 MVA,
   winter, versus the old static 210 MVA — corrected from a retracted
   301.9 MVA figure, see note below) **before** solving the
   network, not just relabelling the column afterward — a wider rating on
   one line can change what the optimiser dispatches everywhere else, so
   the order matters.
2. **Solve → freeze dispatch → run DC load-flow, in that exact order.**
   The network is first solved as a linear optimal power flow (LOPF),
   which chooses generator dispatch subject to every line's rating as a
   hard constraint. That exact dispatch is then frozen, and a DC
   load-flow is run on top of it. Skipping or misordering the
   freeze-dispatch step is a known failure mode (a line reading ~1600%
   "loaded" is the classic symptom), and this script checks for that
   explicitly before trusting anything downstream.
3. **Extract hourly flow data for every line, every snapshot** —
   `baseline_hourly_flows.csv`, 126,840 rows (755 lines × 168 hourly
   snapshots across the week), with columns `snapshot, line_id, bus0,
   bus1, flow_MW, abs_flow_MW, rating_MW, overload_MW`.
4. **Select and rank the binding lines** — the ones that actually
   constrain the system at some hour.

## The structural finding that shapes how "binding" is defined

`max_overload_MW` and `total_overload_MWh` come out essentially zero
(1e-10 to 1e-12 MW — floating-point noise) for every single line, every
hour. This is not a bug; it's a direct structural consequence of the
solve → freeze-dispatch → load-flow pipeline. The LOPF solve enforces
every line's rating as a hard constraint while choosing dispatch; freezing
that dispatch and re-running a deterministic DC load-flow on top of it
just reproduces the same flows the LOPF already computed internally —
flows that, by construction, can reach a line's rating but never exceed
it. A correctly-solved network literally cannot show a genuine MW-over-limit
"overload" in this sense; it can only reach 100% and stop. (This is the
same structural fact Harshitha's Q2 work ran into independently, reading
`hourly_flows.csv`'s flow/limit columns directly — an independent second
confirmation, not a new problem.)

**Practical consequence:** since `overload_MW > 0` is meaningless as a
selection criterion here, "binding" is instead computed from loading
reaching ≥ 99.9% of rating (`overload_hours`) — the same threshold
`gridkit.binding()` itself uses. This definition is stamped directly into
`binding_lines.csv` as a `binding_definition = "loading_ge_99.9pct"`
column, so the file stays self-describing even if separated from this
note. `overload_MW` is still reported in `baseline_hourly_flows.csv`
exactly as specified for anyone downstream who wants it — it just reads as
noise, not a real magnitude. Where a genuine MW/MWh magnitude is needed
for a binding line, the established approach elsewhere in this project is
generator-side dispatch-down (`gridkit.dispatch_down()`), not line-side
flow-vs-rating — the same substitution Harshitha already made for exactly
this reason.

## Results

### Binding lines found (6, all selected — well under the 5–15 target range)

| rank | line | rating (MVA) | overload_hours (of 168) |
|---|---|---|---|
| 1 | 3581-89516-1 | 123.0 | 118 |
| 2 | 2781-4951-1 | 106.0 | 37 |
| 3 | 1122-11260-1 | 513.0 | 32 |
| 4 | 1122-1742-1 | 513.0 | 9 |
| 5 | 3082-3122-1 | 634.0 | 7 |
| 6 | 3691-4041-1 | 192.0 | 2 |

**Headline finding: `5041-17010-2` — the north-west line the rest of this
project has focused on — does not appear in this list at all.** With its
real-weather DLR rating applied (210 → 213 MVA — the corrected figure;
see note below), it drops out of the national binding-lines set entirely
under this scenario. This is a second, independent confirmation of the
earlier finding that winter DLR removes this line's own constraint at
national scale, and it holds at the corrected, smaller DLR uplift too —
not just at the retracted 301.9 MVA figure this document originally
quoted (re-run and confirmed directly, 2026-09-11).

**CORRECTION (2026-09-11):** this document originally quoted a 301.9 MVA
DLR rating for `5041-17010-2` and reported the top binding line
(`3581-89516-1`) at 123 hours. Both numbers were computed against a
since-retracted DLR figure (29-year weather archive, no solar term,
perpendicular-wind assumption — see `dlr-2024-real-weather-rewrite.md`).
Re-run at the corrected 213.0 MVA figure: the top line reverts to 118
hours — matching the original *static*-rating baseline almost exactly,
because the smaller, more realistic DLR uplift barely perturbs the rest
of the network's dispatch. The table above and the side-effect note below
now reflect the corrected 213 MVA run.

**A smaller, expected side effect:** the composition and hour-counts of
the *other* binding lines can shift slightly versus the pure static-rating
baseline, because widening one line's rating changes what the optimiser
dispatches elsewhere. At the corrected 213 MVA uplift this effect is
negligible — the top line's hour count (118) now matches the static-210
baseline exactly, unlike the larger, since-retracted 301.9 MVA figure
which had pushed it up to 123. Anyone comparing this list against an
earlier static-rating
version should expect small differences for exactly this reason.

## Quality gate

- **No impossible-flow signature**: worst line loading came out at exactly
  100.0%, not the ~1600%+ symptom of a skipped/misordered freeze-dispatch.
- **Overload uses `|flow| > rating`**, not signed flow — a line can bind
  in either direction and both count.
- **Every selected line has a real, finite, positive rating**, checked in
  code; the run aborts otherwise rather than shipping a bad list.
- **Ranking metric stated explicitly**: `overload_hours`, not
  `total_overload_MWh` — a poor ranking choice given the structural
  finding above, even though it's still computed and reported.
- **`binding_lines.csv` carries its own provenance**: `scenario` and
  `scope` columns on every row, so a downstream reader can verify the file
  matches the case it's meant to be used with, rather than trusting a
  filename or memory.

## Independent audit — what was checked, what was changed

A second round of external review (4 issues on this script, numbered 6–9
in sequence with an earlier general audit) was checked against the actual
code rather than taken at face value:

- **Applied (Issue 9):** the real "binding" definition (loading ≥ 99.9%)
  was only documented in the script's docstring, not carried in the data
  itself — a genuine self-describing-data gap. Fixed by adding the
  `binding_definition` column described above.
- **Considered and deliberately left unchanged (Issues 6–8):** a wording
  tweak to the sanity-check error message (the check's logic was never
  wrong, only its phrasing overclaimed certainty); validating `n_select`
  as positive (flagged by the report itself as "not relevant to the
  current run, trivial to harden" — i.e. hardening, not a fix for
  anything broken); and an explicit empty-result guard for zero lines
  binding (doesn't apply here — 6 lines do bind — and the downstream
  script already fails clearly if it ever received an empty file). All
  three are reasonable hardening for a more defensive future version, not
  corrections to this deliverable.

Re-ran the full pipeline end-to-end after the one applied change:
`binding_lines.csv` regenerated with the same 6 lines and the same
numbers, now with the `binding_definition` column; Step 2's shift-factor
script was re-run against the updated file to confirm it still reads
cleanly and its own quality gate still passes.

## Scope limitation (stated, not fixed)

Covers `n.lines` only, not `n.transformers` — the same gap flagged
elsewhere in this project's earlier audit work; the stock kit doesn't
check transformer loading either, so a transformer-bound constraint
elsewhere in the all-island grid would not show up here.

## Open items

- This run is `WP2033` (winter) only. An `SV2033` (summer) run would use
  the summer DLR rating (231.1 MVA) for `5041-17010-2` via the same
  `DLR_LINES` mapping in the script — one command, not done here since
  WP2033 matches what the rest of the project has defaulted to.
- `DLR_LINES` in the script is a single, extensible mapping — if any
  other line gets a real weather-derived rating later, add it there and
  this whole pipeline picks it up automatically, no other code changes
  needed.

## Files

- `n_binding_lines_baseline.py` — the script.
- `baseline_hourly_flows.csv` — every line, every snapshot (126,840 rows).
- `binding_lines.csv` — the 6 binding lines, self-describing (`scenario`,
  `scope`, `binding_definition` columns included).
- `n_binding_lines_WP2033_all-island.png` — horizontal bar chart, top
  binding lines by `overload_hours`.

## Downstream

This step's two outputs — `binding_lines.csv` and
`baseline_hourly_flows.csv` — are the direct inputs to Step 2 (the
shift-factor matrix, which computes each renewable node's sensitivity to
each of these 6 lines) and, via Step 2, to Step 3B (candidate group
generation for relieving each of these 6 lines). Every later step in the
pipeline is scoped to exactly these 6 lines; nothing downstream re-derives
or re-checks which lines are binding.
