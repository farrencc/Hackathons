# Response to the Inspector's Report on `step3b_group_generation.py` (23 findings, 20 defects)

Every finding and defect was checked against the actual code and, where
possible, against your real `binding_lines.csv` / `baseline_hourly_flows.csv`
/ `shift_factor_matrix.csv` — not taken at face value. Three were genuine
bugs and are now fixed and re-verified against the real data. One more
(Finding 14 / Defect 07 — a selected line with zero Method A candidates)
was checked empirically and does **not** occur on this run's data, but a
cheap safety net was added anyway so it can never fail silently in a future
run. Everything else falls into two categories: already correctly handled
in the code/output as written, or hardening against inputs that Step 1 and
Step 2's own code already rule out by construction (same category the
Step 1/2 audits used for their own "not applicable to this pipeline"
findings).

## Fixed (3 genuine bugs, all re-verified against real data)

**Finding 09 / Defect 01 — NaN flow silently mislabeled "negative".**
`determine_overload_directions()` counted `pos = (flow_MW > 0).sum()` and
`neg = (flow_MW < 0).sum()`; if every near-binding snapshot's `flow_MW` was
NaN, both counts were 0, and the code fell straight through to
`else: "negative"` with no warning. Fixed by adding an explicit
`pos == 0 and neg == 0` branch that maps to `"ambiguous"` with a distinct
`[WARN]` message ("insufficient data to determine overload direction").
This case doesn't occur anywhere in your real `baseline_hourly_flows.csv`
(verified — no line has all-NaN flow at its near-binding snapshots), so a
synthetic test was used to confirm the fix: an all-NaN line now correctly
returns `"ambiguous"` instead of `"negative"`.

**Finding 03 — signed "relief" field could read as always-positive.**
`target_line_relief_10MW_MW = signed * DELTA_P` was negative for every
passing row on a positive-direction line (and positive for every passing
row on a negative-direction line) — real, not hypothetical: **108 of 179**
rows in your actual `proposed_groups.csv` had a negative value in that
column. Only the readable map took `abs()` of it before display; the
authoritative CSV field was signed but named like a magnitude. Fixed by
splitting it into two columns: `target_line_flow_change_10MW_MW` (signed,
for anyone tracing the arithmetic) and `target_line_relief_magnitude_10MW_MW`
(always ≥ 0 — what "MW of relief" actually means, now that Method A has
already screened for the correct direction). Re-run confirms
`target_line_relief_magnitude_10MW_MW` is non-negative for all 179 rows.

**Finding 04 — `tradeoff_ratio` didn't check whether it was actually a trade-off.**
The ratio was computed from every materially-affected other line
regardless of whether Method B classified it `relieves`, `worsens`, or
`undetermined`. This was the highest-impact finding once checked against
real data: of the **160 rows** flagged multi-line, **145** had their
reported worst-case ratio driven by a `relieves` (beneficial) effect, not
an adverse one — the field was calling 90% of genuinely helpful
interactions "trade-offs." Fixed by splitting into
`worst_case_material_other_line_impact_ratio` (unchanged calculation,
renamed — a magnitude comparison only) and
`worst_case_adverse_tradeoff_ratio` + `has_adverse_tradeoff` (computed only
over other-lines actually classified `worsens`). Re-run: only 15 of the 160
flagged rows now show `has_adverse_tradeoff = True` — that's the real
number of node/line rows with a genuine adverse side-effect, versus the
previous ratio field implying all 160 might have one.

Column renames this required, everywhere they're consumed
(`multiline_tradeoff_analysis.csv`'s `tradeoff_ratio` → `impact_to_relief_ratio`,
same reasoning): the readable map and `membership_reason` text were updated
to say "ADVERSE tradeoff, worst-case Nx" vs "no adverse effect among them"
per row, instead of one ambiguous ratio number.

## Added defensively, though not triggered by this run's data

**Finding 14 / Defect 07 + Finding 23 — zero-candidate lines / ambiguous
lines only visible in console output, not the persisted summary.**
Checked empirically first: all 6 selected binding lines produced at least
one Method A candidate on your real data (`method_a_groups['group_id'].nunique() == 6`),
so this was not live for this run. Added anyway, since it's cheap and
closes the exact gap the report describes: `group_method_comparison.csv`
now carries `selected_lines_with_zero_candidates` /
`...ids` and `selected_lines_with_ambiguous_direction` / `...ids` columns,
so a future run where a line silently drops out (TAU raised, new data,
etc.) would show up in the persisted file, not just a scrollable console
log.

## Checked and left unchanged — already correct or already stated

- **Finding 01 (TAU=0.05)** — already labeled a "TEAM SIGN-OFF PLACEHOLDER...
  NOT a validated value" in both the docstring and the runtime print, citing
  the same percentiles the report cites.
- **Finding 02 (sign convention)** — stated explicitly in the docstring, and
  actually *verified* one step upstream: Step 2's own audit proved the
  matrix matches `flowmath.shift_factors(reference="load")` to machine
  precision on all 1,308 pairs.
- **Finding 06 ("validation" overstated)** — every user-facing string
  already says "flagged... requiring manual cross-line validation," never
  "validated." Only the internal function name (`method_b_multiline_validation_layer`)
  is loosely worded; no output overclaims.
- **Finding 07 (10 MW is hypothetical)** — stated four separate times
  (docstring, code comments, `membership_reason` text, runtime print) as a
  linear estimate, not a claim of available headroom.
- **Finding 15 / Defect 08 (ambiguous vs directional candidates)** — already
  recorded per-row in `membership_reason` and per-line in
  `group_map_readable.csv`'s `overload_direction` column; not a dedicated
  boolean, but not hidden either.
- **Finding 21 (empty strings for "no other lines")** — already
  disambiguated by the `multi_line_flag` boolean; `""` only ever means
  "checked, found none," never "analysis failed."
- **Finding 22 (readable map not authoritative)** — already true by
  construction: `proposed_groups.csv` and `multiline_tradeoff_analysis.csv`
  are the real outputs; `group_map_readable.csv` is explicitly commented as
  being for non-technical judges only.
- **Defect 15 (zero target-relief denominator)** — already guarded with an
  explicit `impact_to_relief_ratio_note`, not a crash.
- **Defect 19 (Method B coverage completeness)** — traced by hand against
  the code; it already includes every other line with `abs(SF) >= tau`
  regardless of sign. Already correct.
- **Finding 05 (Method B only examines Method A members)** — the report
  itself says this isn't a defect against the stated design; it's the
  documented architecture.
- **Defect 14 (floating-point threshold boundary)** — inherent to any hard
  cutoff, not a bug; no team-specified tolerance exists to encode.
- **Defect 18 (simultaneous curtailment isn't additive)** — the code never
  sums multiple nodes' relief into a combined claim; every figure is
  single-node.
- **Defect 20 (classification wrong if direction is wrong)** — correctly
  identifies that Method B inherits whatever `determine_overload_directions()`
  produced, i.e. it inherits Finding 09/Defect 01. Not a separate defect —
  fixing 09 also fixes this.

## Checked and left unchanged — hardening against inputs ruled out by construction

Same category as the last two audit rounds: these assume upstream
conditions that Step 1 or Step 2's own code already prevents, so they're
legitimate general hardening for a future standalone version of this
script, not live bugs in this deliverable.

- **Finding 08 / Defect 02 (zero rating)** — Step 1 hard-aborts on any
  selected line without a finite, positive rating.
- **Finding 11 / Defect 03 (duplicate node×line rows)** — Step 2's matrix is
  exactly 218 nodes × 6 lines = 1,308 rows by construction.
- **Finding 12/13 / Defect 12/13 (non-renewable contamination, missing-vs-zero SF)** —
  matrix is built only from `candidate_renewable_nodes.csv` and is dense
  (every node × every line).
- **Finding 16 / Defect 05 (`selected == True` string brittleness)** —
  `binding_lines.csv` is written and read by the same pandas process; real
  bools round-trip correctly.
- **Finding 18 / Defect 04 (`shift_factor_abs` vs `abs(signed)` disagreement)** —
  computed from each other in the same Step 2 line; can't diverge.
- **Finding 19 (identifier drift across files)** — all three CSVs come from
  the same automated pipeline.
- **Finding 20 / Defect 06 (incomplete SF coverage)** — Step 2 hard-fails if
  any selected line lacks full SF coverage.
- **Defect 16 (mixed units, MW vs GW)** — same "trust upstream" class;
  nothing feeding this script produces GW-scaled values.
- **Defect 17 (mixed-magnitude overload snapshots)** — already the same
  code path as the mixed-direction case; handled.

## Re-run confirmation

Full pipeline re-run end-to-end against your real files after all changes:
same 6 groups, same 179 node-membership rows, same 160 rows flagged
multi-line as before the fix (the fix changes *what the numbers mean*, not
which rows are included) — `proposed_groups.csv`, `multiline_tradeoff_analysis.csv`,
`group_method_comparison.csv`, and `group_map_readable.csv` all regenerated
cleanly with the new columns.
