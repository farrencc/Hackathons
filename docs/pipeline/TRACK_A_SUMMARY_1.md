# Track A — core engine + Q1 + Q5

Network: `WP2033` (2033 winter peak), scope: `north-west` (Donegal / Sligo / north Mayo, 15-node), unless stated otherwise. All scripts live in `participant-kit/examples/`, ready to run in VS Code exactly as-is — copy the whole `participant-kit` folder from this run, or re-run each script yourself; instructions for both are below.

---

## Step 1 — environment check

`python examples/a_dc_power_flow.py` (no arguments) ran clean in a fresh venv: ~75 seconds, wrote `figures/a_flow_map_WP2033_all-island.png`. No fixes needed — `gridkit.py` imports and runs as shipped.

## Step 2 — Q1: most-constrained lines

### Ranking, `north-west` (this is the scope everything downstream uses)

| line | max_loading | s_nom (MVA) | hours at rating (of 168) |
|---|---|---|---|
| **5041-17010-2** | **1.000** | **210** | **52** |
| 1631-5041-1 | 0.725 | 210 | 0 |
| 28710-51911-1 | 0.682 | 183 | 0 |
| 3581-5361-1 | 0.628 | 123 | 0 |
| 1931-4371-1 | 0.614 | 210 | 0 |

`5041-17010-2` is not a close call — it's the only circuit in the north-west that actually binds (reaches 100% loading), and it does so for nearly a third of the week (52/168 hours). **This is our target line** — the one Kanyisola's Q2 and everyone downstream should build on.

### Ranking, `all-island` (for context — is the national worst line the same as the regional one?)

| line | max_loading | s_nom (MVA) | hours at rating |
|---|---|---|---|
| 3581-89516-1 | 1.000 | 123 | 118 |
| 3691-4041-1 | 1.000 | 192 | 2 |
| 1122-11260-1 | 1.000 | 513 | 32 |
| 2781-4951-1 | 1.000 | 106 | 37 |
| 3082-3122-1 | 1.000 | 634 | 7 |

**No — the worst line nationally (`3581-89516-1`, 118 hours at rating) is a different circuit from the worst line regionally (`5041-17010-2`).** Worth flagging in the writeup: the north-west's own local bottleneck isn't even in the all-island top 5, because folding the region to 15 station-level nodes changes what's visible as a "circuit" — good context for why this project scoped down to north-west in the first place.

Run these yourself with:
```bash
python examples/a_dc_power_flow.py WP2033 north-west
python examples/a_dc_power_flow.py WP2033 all-island
```

### Thermal-rating sensitivity (new script: `g_thermal_rating_sensitivity.py`)

For the top 3 north-west lines, widened the rating by 0%, 10%, 20%, 30% (a stand-in for reconductoring / dynamic line rating / an uprated future rating), re-solving fresh each time (`solve → freeze_dispatch → lpf`, exactly in that order, per the kit's own warning) and re-reading `hours_at_rating`:

| line | +0% | +10% | +20% | +30% |
|---|---|---|---|---|
| **5041-17010-2** | **52** | **39** | **19** | **13** |
| 1631-5041-1 | 0 | 0 | 0 | 0 |
| 28710-51911-1 | 0 | 0 | 0 | 0 |

Only the target line moves — the other two never bind in this scenario at all, so widening them changes nothing (expected: a line has to actually be constrained before its rating matters). A 30% rating uprate on `5041-17010-2` cuts its hours-at-rating from 52 to 13 (a 75% reduction) but doesn't eliminate the constraint — worth a line in the writeup on diminishing returns.

Run:
```bash
python examples/g_thermal_rating_sensitivity.py WP2033 north-west 3
```
Full long-form results: `figures/g_thermal_sensitivity_WP2033_north-west.csv` (also delivered as a standalone file).

## Step 3 — `hourly_flows.csv` (shared file — this is what Kanyisola and Chibuikeim need)

New script: `h_export_hourly_flows.py`. Columns: `hour, line_id, flow_MW, limit_MW`. 3,024 rows = 18 north-west lines × 168 hours. `flow_MW` is signed exactly as PyPSA returns it (positive = flow from bus0 to bus1); `limit_MW` is each line's static `s_nom` rating.

```bash
python examples/h_export_hourly_flows.py WP2033 north-west
```
**This file is attached and ready to share now.**

## Step 4 — Q5: shift factor per wind farm via nearest substation

Ran `python examples/f_shift_factors.py WP2033 north-west 5041-17010-2`. As the task brief said, the output is already indexed by generator with a `bus` column (each generator's own connecting substation) — no extra mapping needed.

**Primary answer (load-weighted reference):**

| generator | bus | shift factor on 5041-17010-2 |
|---|---|---|
| Corderry wind | Corderry | +0.579 |
| Glenree wind | Glenree | +0.579 |
| Sligo wind | Sligo | +0.579 |
| Ardnagappary wind | Ardnagappary | −0.238 |
| Tievebrack wind | Tievebrack | −0.238 |
| … (14 wind farms total) | | |

**Robustness check — three reference conventions** (load-weighted / uniform / single-bus at the biggest load, Letterkenny): the *values* differ (e.g. Corderry wind: 0.579 / 0.584 / 0.817) but the **rank correlation between all three is 1.0000** — the ordering never changes. This is exactly the robustness property the Wind Dispatch Tool relies on, and it's worth stating explicitly in the presentation.

**Constraint group** (≥5% shift factor, wind/solar only): 13 instructable generators, 1,010 MW combined capacity. At the peak-loading hour (17 Jan 2030, 16:00), the circuit sits exactly at its 210 MVA rating with 185.6 MW of total relief available across the group if fully dispatched down — Corderry wind alone offers 43 MW.

`shift_factors.csv` (new script: `i_export_shift_factors.py`) — rows = wind farm, one column per monitored line (built as `shift_factor_5041-17010-2`; pass more line names on the command line to add columns for Harshitha's and Kanyisola's target lines too). **14 rows** — filtered to `carrier == "wind"` only; see the audit section below for why that filter matters:
```bash
python examples/i_export_shift_factors.py WP2033 north-west 5041-17010-2
```
**This file is attached and ready to share now (corrected version — see audit note 1 below if you already grabbed the first one).**

## Step 5 — sanity check (`d_ptdf.py`)

```bash
python examples/d_ptdf.py WP2033 north-west 5041-17010-2
```
Max discrepancy between the PTDF reconstruction and the actual `n.lpf()` solve: **2.7 × 10⁻¹³ MW** — squarely in the expected e-10-to-e-13 range, no phase-shifting transformers flagged in this scope. **Everything upstream checks out; safe to build on.**

(One incidental note from this run: the north-west Laplacian has a nullspace dimension of 2, i.e. 2 connected components rather than 1 — the pseudoinverse handles this correctly and the check still passes to machine precision, but if a boundary-condition question comes up in the presentation, that's where to look.)

## Audit — bugs found, fixed, and open gaps (re-tested after delivery, 2026-09-08)

I went back and stress-tested this rather than just eyeballing it: reran the solver twice for bit-identical reproducibility, ran the full `test_kit.py` suite (22/22 pass, kit untouched), and ran a counterfactual on the sensitivity script. One real bug, found and fixed below; three things that are correct but need to be said out loud so nobody downstream gets caught out; one thing that's fine.

**1. Bug, fixed — `shift_factors.csv` originally included 14 rows that are not wind farms.** The north-west network's generator list is 14 wind + 10 "boundary" equivalencing injections (artifacts of folding the region to 15 nodes — names like `boundary Corderry - ARIGNA_T 1`, easy to mistake for a real line or plant) + 2 hydro + 2 "unknown"-carrier (mostly conventional thermal) + 7 load-shedding (already excluded). The first version of `i_export_shift_factors.py` only excluded load-shedding, so the delivered CSV had 28 rows, 14 of which weren't wind farms at all — if Harshitha or Kanyisola had pulled `p_nom` or `shift_factor` for e.g. `boundary Corderry - ARIGNA_T 1` believing it was a wind farm, that's a factual error a judge could catch on sight. **Fixed**: the script now filters to `carrier in ("wind", "solar")` by default (14 rows, verified above), prints what it excluded and why, and takes `--all-generators` if a later question genuinely needs the boundary/hydro/unknown rows too. The corrected CSV is attached above; if you already sent the first version to teammates, tell them to re-pull it.

**2. Real gap, not fixable by me — the kit's own "most-loaded circuits" table (and `gridkit.line_loading()`) only looks at lines, never transformers.** I checked: in `all-island`, three transformers reach 100% loading at some hour, one of them (`T3662-36671-1`, 582 MVA) for **75 hours** — more than all but one of the lines in my Q1 all-island table. This means the Q1 "most constrained circuits, nationally" answer, and `a_dc_power_flow.py`'s figure, are both silently incomplete for `all-island` — a transformer could plausibly be the single worst-constrained piece of hardware on the island and nothing in the stock kit would surface that. It doesn't affect `north-west` (that scope has zero transformers, confirmed), so the target-line pick and everything built on it are unaffected — but if anyone on the team (Kanyisola's Q2, or anyone presenting the all-island context) says "the most constrained circuit in Ireland is X," that claim should be caveated as "the most constrained *line*," not circuit, unless someone separately checks `n.transformers_t.p0`. Worth a one-line caveat in the presentation, and worth flagging to whoever owns the all-island framing.

**3. Design choice, verified not to matter here but could bite on a different network — the thermal-rating sensitivity script widens all 2–3 lines together at each factor, not one at a time.** The task brief is genuinely ambiguous about whether "loop over factors on your top 2–3 lines" means widen them jointly or test each independently. I tested both: since the other two candidate lines never actually bind in this dispatch (0 hours at rating at every factor), widening them alongside the target line makes exactly zero difference — confirmed bit-for-bit, both approaches give hours=52/39/19/13 and identical hourly flow on the target line. **This is a coincidence of this dataset, not a property of the method** — on a network where two lines both bind, jointly widening them would conflate each line's individual effect with the interaction between them, and the current script would silently give you the joint number while looking like an individual sensitivity. If anyone repurposes `g_thermal_rating_sensitivity.py` on a scope/scenario where multiple lines actually constrain simultaneously, they should know it's testing "these lines widened together," not "each line widened alone."

**4. Not fixed, worth deciding as a team — `hourly_flows.csv` is `north-west`-only, lines-only.** The task brief doesn't say which scope this shared file should cover, and I defaulted to `north-west` to match the target-line work. That's complete for `north-west` (0 transformers, 0 links there, confirmed) but there's no `all-island` version, and if anyone needs national-scale hourly flow data for their own question, this file won't have it — say so before someone assumes it does. `h_export_hourly_flows.py` takes a scope argument, so producing an `all-island` version is one command away, but note it would also need transformers and links added (currently lines only) to be a complete picture at that scope, per finding 2.

**5. Checked and fine — reproducibility.** Reran the full solve twice from a fresh network load: bit-identical dispatch (`max diff = 0.0`) and identical `hours_at_rating`. HiGHS is behaving deterministically here, so re-running these scripts on the same machine/environment should reproduce the same numbers exactly. The one caveat I can't rule out without another machine to test on: many generators here share identical marginal costs (all wind at −1 EUR/MWh, for instance), which is the classic setup for LP degeneracy — multiple equally-optimal dispatches with different flows on *non-binding* lines. If a teammate reruns this on a different HiGHS version or a different platform and gets slightly different numbers on lines that never bind anyway (not the target line, which is pinned at its rating and has no such ambiguity), that's why — not a sign anything is broken.

## What's next (Step 6)

Files are ready to hand off to the team now (shift_factors.csv corrected — see audit note 1). From here, shift into pulling Q1–Q6 into one narrative for the panel — claim time for that deliberately, per the brief, since it's the piece most likely to get squeezed. Worth putting findings 2 and 4 above in front of whoever owns the all-island framing before the presentation is locked, since both are things a sharp judge could ask about directly.
