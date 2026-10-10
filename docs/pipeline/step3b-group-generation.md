# Step 3B — Candidate group generation (Method A + Method B validation layer)

Owner role: Person 4. Turns `shift_factor_matrix.csv` + `binding_lines.csv`
(+ `baseline_hourly_flows.csv`, used only to determine overload direction)
into `proposed_groups.csv`. Run end-to-end against the real Step 1/2 outputs
in this folder — not just syntax-checked.

Includes the fixes from an independent audit — see **AUDIT-RESPONSE.md** for
the full triage (23 findings, 20 defects: 3 genuine bugs fixed and
re-verified against real data, 1 defensive addition, everything else
already correct or already ruled out by Step 1/2's own guarantees).

```bash
python step3b_group_generation.py
```

## Method

- **Method A** answers "who could relieve this constraint?" — builds one
  candidate group per selected binding line from nodes whose shift factor
  passes a magnitude threshold (`TAU`, currently a placeholder — see
  sign-off note below) in the correct relief direction (determined from
  `baseline_hourly_flows.csv`'s near-binding snapshots).
- **Method B** answers "what else happens if we use that node?" — a
  validation/trade-off *layer* on top of Method A's rows, not a second
  group-generation method. For every node already in a Method A group, it
  checks every OTHER selected binding line that node materially affects,
  estimates the side-effect from a standard 10 MW hypothetical
  curtailment, and classifies it `relieves` / `worsens` / `undetermined`
  against that other line's own overload direction.

## What changed in the fixed version

- `target_line_relief_10MW_MW` (could be negative on 108/179 real rows) →
  split into `target_line_flow_change_10MW_MW` (signed) and
  `target_line_relief_magnitude_10MW_MW` (always ≥ 0 — the actual relief
  size).
- `tradeoff_ratio` (mixed beneficial and adverse effects into one number —
  145 of 160 flagged rows' reported ratio was actually driven by a
  *beneficial* effect) → split into
  `worst_case_material_other_line_impact_ratio` (any effect, magnitude
  only) and `worst_case_adverse_tradeoff_ratio` + `has_adverse_tradeoff`
  (restricted to genuinely adverse `worsens` effects — only 15 of 160 rows
  actually have one).
- An all-NaN near-binding line no longer silently defaults to "negative"
  overload direction — it's now explicitly `"ambiguous"` with a console
  warning (doesn't occur in this run's data; verified with a synthetic
  test).
- `group_method_comparison.csv` now records selected lines with zero
  Method A candidates or ambiguous overload direction directly in the
  persisted file, not only in the console log (not triggered on this
  run's data — all 6 selected lines got candidates — but the gap is
  closed for future runs).

## Team sign-off items (unchanged from the original script)

- **TAU = 0.05** is a placeholder, not a validated threshold. Reference:
  median |shift factor| ≈ 0.007, 90th percentile ≈ 0.073, 95th percentile
  ≈ 0.156 in your actual `shift_factor_matrix.csv`.
- The 10 MW figures are linear shift-factor estimates (`ΔF = SF × ΔP`),
  not AC power-flow results, and not a claim that 10 MW of curtailment
  headroom actually exists at any given node.
- Method B only examines nodes that already passed Method A for some
  target line — it is candidate-member cross-line validation, not a
  global "which nodes affect multiple lines" scan. Documented, not a
  defect.

## Results on your real data (WP2033, all-island, 6 binding lines, TAU=0.05)

- Method A: 6 groups (one per selected binding line), 179 node-membership
  rows total.
- Method B: 160 of those 179 rows flagged as materially affecting at least
  one other binding line, covering 87 unique nodes — of which only **15**
  rows have a genuinely adverse (worsening) side-effect on another line;
  the other 145 flagged rows only *relieve* other lines too.

## Files

- `step3b_group_generation.py` — the fixed script.
- `proposed_groups.csv` — Method A's 179 candidate rows, enriched by
  Method B (179 rows).
- `multiline_tradeoff_analysis.csv` — full node × target_line × other_line
  detail behind the flags (163 rows).
- `group_method_comparison.csv` — Method A/B summary stats, now including
  zero-candidate and ambiguous-direction line tracking.
- `group_map_readable.csv` — plain-English group map for non-technical
  judges (not authoritative — see AUDIT-RESPONSE.md, Finding 22).
- `binding_lines.csv`, `baseline_hourly_flows.csv`, `shift_factor_matrix.csv`
  — the Step 1/2 inputs this was run against.
