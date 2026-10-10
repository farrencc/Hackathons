# Shift-factor matrix - technical note

**Reconstruction note (2026-09-11):** the script that built the files
below (`o_shift_factor_matrix.py`) was never committed to this branch —
only its outputs were, which meant the matrix couldn't be regenerated or
independently checked (Track A audit F-06). It's now committed. Running
it reproduces every one of the 1,308 already-committed rows to machine
precision (max difference 9.9e-17), confirmed directly rather than
assumed. As a side effect, this also empirically confirms the "DLR
rating has zero effect on shift factors" claim below: the committed file
was originally built with 5041-17010-2 at the since-retracted 301.9 MVA
DLR rating, and this rebuild uses the corrected 213.0 MVA rating instead
— the two ratings differ by 89 MVA, and the resulting shift factors are
identical to 1e-16, exactly as the PTDF-is-topology-only claim predicts.
`candidate_renewable_nodes.csv` was also missing and has been added.

- Case name: WP2033 all-island (Step 1's binding_lines.csv case,
  provenance-checked - this run refused to proceed if binding_lines.csv
  didn't carry matching scenario/scope columns)
- Network scope: all-island
- Candidate unit: bus (not individual generator - co-located
  generators share one row since a shift factor is a property of WHERE
  power is injected; this is stated explicitly here and in a
  `candidate_unit` column in both CSVs, not left implicit)
- Sign convention: positive = effect of INCREASING generation at that
  node on the monitored line's flow in PyPSA's bus0->bus1 direction
  (same convention as flow_MW throughout this project)
- Reference convention: load-weighted (flowmath.shift_factors'
  reference="load") - chosen because it already
  matches this project's Q5/f_/i_ shift-factor work, and because
  ranking (not magnitude) was already shown to be robust to the choice
  of reference in that earlier work. The reference load is the MEAN
  demand across all snapshots (not the perturbed snapshot's own load) -
  this is not a choice unique to this script, it's exactly what
  flowmath.shift_factors(reference="load") itself does internally, and
  this run independently verified the two implementations agree to
  machine precision (see verify_reference_equivalence() in the script,
  and the reference-equivalence line in the run log).
- Perturbation size: 10 MW (used for quality-gate
  verification only - the matrix itself is built analytically via
  flowmath.ptdf(), exact under DC power flow, not subject to solver
  tolerance)
- METHOD NOTE: the brief's Work section describes perturb-rebalance-
  resolve as the method itself; this script instead computes the matrix
  analytically (exact under linear DC power flow) and uses the literal
  perturbation method as an independent quality-gate check on a sample
  of the matrix, not as how every row was produced. Mathematically
  equivalent under DC linearity, verified above - but this is a
  deviation from a literal reading of the brief, and per Step 2's own
  "team decisions" framing, should be explicitly noted as accepted by
  the team, not treated as automatic compliance.
- Candidate nodes: 218 unique buses hosting wind/solar
  generators (aggregated from 603
  individual generators; gas/hydro/unknown/biomass/import/export/load
  shedding excluded). p_nom_total_MW_nameplate is NAMEPLATE capacity,
  not available/dispatchable output - don't use it directly for
  curtailment calculations without applying p_max_pu/availability.
- Monitored lines: 3581-89516-1, 2781-4951-1, 1122-11260-1, 1122-1742-1, 3082-3122-1, 3691-4041-1 (from binding_lines.csv,
  selected=True)
- DLR note: WP2033 uses the real-weather DLR rating on 5041-17010-2
  where applicable - has no effect on this file's values (PTDF depends
  on reactance/topology, not rating), included for case consistency only.
  Decoupled from the shift-factor calculation: a DLR lookup failure
  downgrades to a warning and continues on the static rating rather than
  aborting the matrix build.
- Quality gate: 31 (node, line) pairs verified by literal
  10 MW perturbation + rebalance + re-solve (at least
  1 per monitored line, stratified, not just 3 total regardless of line
  count); worst analytic-vs-empirical difference
  0.000000 MW/MW (seed=42).
  15 of 31 checks
  perturbed a generator beyond its available headroom at that snapshot -
  those are valid PTDF-verification tests, not claims of operational
  feasibility.
- Run: 2026-09-10T10:34:35.977840+00:00
