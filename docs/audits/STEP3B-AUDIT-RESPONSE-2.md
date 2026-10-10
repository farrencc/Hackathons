# Response to a second round of audit findings (D01–D19, on the fixed step3b_group_generation.py)

A second, independent-style report (19 items, "D01"–"D19" numbering) was
checked the same way as the first: against the actual code and, where it
mattered, against the real `binding_lines.csv` / `baseline_hourly_flows.csv`
/ `shift_factor_matrix.csv`, not taken at face value. This report targeted a
different angle than the first — input-validation hardening rather than
calculation-logic correctness — and none of it overlaps with the three
genuine bugs the first audit found and fixed (NaN-direction handling, the
signed-relief field, and the trade-off-ratio scoping), which remain intact.

**Decision: implement only D06 and D09.** Everything else (D01–D05, D07,
D08, D17–D19) was empirically verified as already ruled out by Step 1/2's
own guarantees — adding runtime validation for them would be defensive
programming against input states this specific pipeline cannot currently
produce, not a fix for a live defect. The full breakdown, with the actual
numbers checked:

- **D01 (invalid ratings)** — zero bad ratings among the 6 selected binding
  lines' rows in `baseline_hourly_flows.csv` (checked: `rating_MW <= 0` or
  non-finite). Step 1 hard-aborts on this already.
- **D02 (duplicate node/line SF rows)** — zero duplicate `(node_id,
  monitored_line)` pairs in the real 1,308-row matrix.
- **D03 / D19 (SF signed/abs disagreement, non-finite values)** — max
  discrepancy between `shift_factor_abs` and `abs(shift_factor_signed)` is
  exactly `0.0` across all 1,308 rows; zero non-finite values in either
  column.
- **D04 (`selected` boolean brittleness)** — the actual column dtype is
  already a real pandas `bool`, not a string.
- **D05 (missing SF coverage)** — all 6 selected lines are present in the
  SF matrix.
- **D07 (non-renewable node contamination)** — the SF matrix's 218 nodes
  match `candidate_renewable_nodes.csv`'s 218 nodes exactly, zero set
  difference either direction.
- **D18 (node_id → conflicting node_name)** — zero conflicts across all 218
  nodes.
- **D08 (missing coverage counted as low influence)** — already correctly
  separated in the existing logic (`low_influence_nodes_excluded` only
  counts nodes present in the SF matrix); not miscounting anything given
  D05's confirmed complete coverage. The only improvement would be an
  explicit `missing_coverage` diagnostic, which has nothing to report on
  this data.
- **D16 (TAU transparency)** — already exactly as required: documented as
  a team placeholder in three places, with the actual data's percentiles
  cited, never claimed as validated. No change.
- **D17 (upfront schema validation)** — a missing column already produces
  a hard `KeyError` failure, not silent wrong output. A friendlier error
  message would be a usability improvement, not a correctness fix.

## Fixed: D06 — empty Method A output schema

`pd.DataFrame([])` on zero candidate rows has **no columns at all** —
confirmed directly (`empty_df["group_id"]` raises `KeyError: 'group_id'`).
This can't happen with the current real data (Method A produces 179 rows),
but it's a genuine fragility in the script's own code, not an "impossible
upstream input" case — zero candidates is a legitimate analytical outcome
that the code didn't actually handle.

Fixed by defining `METHOD_A_COLUMNS` as a single central schema list, and
returning `pd.DataFrame(columns=METHOD_A_COLUMNS)` instead of
`pd.DataFrame([])` when zero rows are generated. No placeholder rows are
manufactured — the analytical result (0 rows) is unchanged, only its shape
is now well-formed. The same fix was applied to Method B's
`tradeoff_detail` table (`TRADEOFF_DETAIL_COLUMNS`), since it has the exact
same failure mode when Method A produces zero candidates (an empty
`detail_rows` list also collapses to a columnless DataFrame otherwise).

Verified with a synthetic test (`TAU=999`, guaranteed to reject every real
shift factor): Method A returns 0 rows with all expected columns present;
`groups["group_id"]` no longer raises; Method B and
`build_comparison_summary()` both run to completion on the empty frame and
correctly report `number_of_groups = 0` and
`selected_lines_with_zero_candidates = 6` (all six lines, by name) instead
of crashing.

## Fixed: D09 — machine-readable `screening_mode`

Added a `screening_mode` column, set at the exact point Method A decides
between directional and magnitude-only screening (not inferred later from
`membership_reason` text): `"directional"` when the line's overload
direction was known and the signed SF was checked against it,
`"magnitude_only_ambiguous"` when direction was ambiguous/unavailable and
screening fell back to `abs(SF) >= tau` alone.

On the real data, all 179 rows are `"directional"` — none of your 6 binding
lines had an ambiguous overload direction, so this doesn't change any
real-data result, only makes the (currently unused) distinction queryable.
Verified with a synthetic test that forces one line's direction to
`"ambiguous"`: that line's rows are correctly labelled
`magnitude_only_ambiguous` while every other line's rows stay
`directional`.

## Regression testing — confirms nothing else changed

Froze the pre-fix `proposed_groups.csv`, `group_method_comparison.csv`, and
`multiline_tradeoff_analysis.csv` before making any change, then diffed
every shared column value after:

- `proposed_groups.csv`: same 179 rows; the only column difference is the
  new `screening_mode` column (179/179 = `"directional"`); every other
  column's values are byte-identical to the pre-fix run.
- `multiline_tradeoff_analysis.csv`: identical shape (163 rows) and
  identical values in every column.
- `group_method_comparison.csv`: identical values in every pre-existing
  column; the fix only adds no new columns here (the
  `selected_lines_with_zero_candidates` / `...ambiguous_direction` columns
  were already added in the first fix round).

Confirmed: Method B still produces `number_of_groups = 0` in both the real
run and the synthetic empty-Method-A test — it does not create groups
under any tested condition. The three previously-fixed correctness bugs
(NaN direction, signed relief field, trade-off scoping) are untouched by
this change; re-verified their outputs are byte-identical to the frozen
baseline. The 10 MW linear-sensitivity calculation and TAU's placeholder
status are unchanged.
