# Q3 — Dynamic Line Rating (DLR), now with real weather

Network: `WP2033` (2033 winter peak) **and** `SV2033` (2033 summer valley)
— this redo covers both seasons, not just winter. Scope: `north-west`.
Target line: **`5041-17010-2`** (the Q1 target line; also confirmed the
most-constrained north-west line under SV2033 — 89/168 hours at rating in
the unmodified summer baseline, vs 52/168 in winter). New scripts:
`examples/j_seasonal_weather_rating.py`, `examples/j_apply_seasonal_dlr.py`,
`examples/j_thermal_rating_chart.py` — same folder as the rest of the kit,
same run-anywhere pattern as the original `j_dlr_rating_sensitivity.py`.

---

## What changed from the original version of this section

The original `j_dlr_rating_sensitivity.py` (still on this branch, not
deleted) tested "what if the rating were permanently raised by X%" —
0/10/20/30% — as an explicitly-stated proxy for DLR, because
`gridkit.set_rating()` can only set one fixed value per run, not an
hour-by-hour weather series. That caveat was the main thing flagged for
the panel Q&A.

This redo answers the follow-up question directly: **what uplift would
real weather actually justify, rather than a round guessed number?** It
pulls 29 years of real hourly wind speed and air temperature from Met
Éireann (Finner Camp, Co. Donegal — station 104, the nearest synoptic
station to this line's endpoints), runs it through a physics-based
thermal model, and produces one representative rating multiplier per
season — still a single constant per run (the network's 168 snapshots are
a modelled scenario week, not real consecutive hours, so there's no
honest way to vary the rating hour-by-hour against them), but now a
number with real data behind it instead of a round guess.

**The original script's numbers aren't being thrown away — they're the
cross-check this redo relies on.** Every arbitrary-sweep number below
(52/39/19/13 hours; 3,660.6/3,232.8/3,076.8/3,072.0 MWh) is
`j_dlr_rating_sensitivity.py`'s own real output, reused directly by
`j_thermal_rating_chart.py` rather than recomputed. They match this redo's
own static-baseline run to the first decimal, which is the confirmation
that both scripts are solving the same network the same way.

## Method

1. **Weather → rating multiplier** (`j_seasonal_weather_rating.py`, no
   PyPSA involved at all): loads 173,818 real hourly observations
   (1997–2026) from Met Éireann's Finner Camp archive, filters to the
   requested season (winter = Dec/Jan/Feb, summer = Jun/Jul/Aug), computes
   a thermal rating multiplier for every individual observation using a
   Hilpert-correlation convective heat-loss model plus Stefan-Boltzmann
   radiative loss (an IEEE738-style simplified thermal model — conductor
   diameter, emissivity, absorptivity etc. are stated engineering
   assumptions, not this line's real TYTFS conductor spec, which isn't
   published), then takes the **P10** (10th percentile) of that
   per-observation distribution as the representative seasonal multiplier
   — the rating that would hold in all but the worst 10% of that season's
   weather, the same exceedance logic as a P90 wind-resource estimate in
   project finance. This is deliberately not a naive average of raw
   weather (physically wrong — averaging wind speed first and modelling
   second doesn't equal modelling first and taking a percentile of the
   result).
2. **Apply it** (`j_apply_seasonal_dlr.py`): multiplies the line's static
   rating by that one number via `gridkit.set_rating()` — the same
   mechanism the original script and Q1's own sensitivity sweep both use
   — then re-solves fresh (`solve → freeze_dispatch → lpf`, same order,
   same warning) and reports `gridkit.line_loading()` and
   `gridkit.dispatch_down()` before/after. **Season picks the network
   too**: winter weather pairs with `WP2033`, summer weather with
   `SV2033`, because those are genuinely different generation scenarios
   (winter peak vs. summer valley), not the same scenario at two points
   in the year — this redo's static baselines (210 MVA/52h winter vs.
   178 MVA/89h summer) confirm that directly.
3. **Chart it** (`j_thermal_rating_chart.py`): combines the original
   arbitrary sweep with this redo's weather-derived point on one figure,
   two panels (hours-at-rating, dispatch-down-MWh), stars for the
   weather-derived points, kept strictly to one scenario per chart so
   WP2033 and SV2033 numbers are never plotted on the same axis.

```bash
python examples/j_apply_seasonal_dlr.py north-west 5041-17010-2 winter 10
python examples/j_apply_seasonal_dlr.py north-west 5041-17010-2 summer 10
python examples/j_thermal_rating_chart.py WP2033 north-west 5041-17010-2
python examples/j_thermal_rating_chart.py SV2033 north-west 5041-17010-2
```

All four commands run end-to-end against the real `gridkit.py` and the
real `networks/` folder in this repo — not just syntax-checked.

## Results

### Winter (WP2033) — real weather justifies a bigger uplift than the sweep tested

| | static (as shipped) | real-weather DLR (P10) |
|---|---|---|
| rating | 210.0 MVA | **301.9 MVA (+43.7%)** |
| hours at rating (of 168) | 52 | **1** |
| dispatch-down (week) | 3,660.6 MWh | **3,072.0 MWh** |

+43.7% is past the top of the original 0/10/20/30% sweep — and the result
lands almost exactly on the sweep's own plateau: dispatch-down at +20% was
already 3,076.8 MWh and at +30% was 3,072.0 MWh, both essentially
identical to the weather-derived point. **In other words: real winter
weather at this station justifies a rating high enough to all but
eliminate this line's constraint for this scenario week** — not "DLR
helps a bit," but "DLR, backed by real data, gets you to the same place
as fully relieving the line," at least in winter.

### Summer (SV2033) — a smaller, still real, uplift — and a much bigger baseline problem

| | static (as shipped) | real-weather DLR (P10) |
|---|---|---|
| rating | 178.0 MVA | **231.1 MVA (+29.8%)** |
| hours at rating (of 168) | 89 | **54** |
| dispatch-down (week) | 21,813.6 MWh | **19,701.3 MWh** |

Summer's baseline constraint is far larger than winter's (89 hours and
21,813.6 MWh vs. 52 hours and 3,660.6 MWh) — SV2033 is a much higher-wind,
lower-demand scenario, so more wind is trying to move through a
lower-rated line (178 vs. 210 MVA, since summer conductors run hotter to
start with). The weather-derived uplift is real (+29.8%, backed by the
same 29-year archive) but recovers a much smaller share of a much bigger
problem: 2,112.3 of 21,813.6 MWh, versus winter's near-total relief.

**This is the headline finding for the panel: DLR and battery storage
read as complementary, not competing, once you split by season.** Winter
DLR alone gets close to fully solving this line's constraint; summer DLR
helps but leaves the large majority of the constraint in place — that's
where storage (see Harshitha's Q2 battery siting) has the stronger case.
Flagged directly to her — see `claude/dlr-cross-team-impact.md` in the
shared project for the full cross-check, since her battery sizing was
done on the winter (WP2033) baseline, which turns out to be the season
real DLR handles best on its own.

## Data and assumptions — stated explicitly, not fabricated

- **Weather source:** Met Éireann's public Finner Camp hourly archive
  (`data.gov.ie/dataset/finner-hourly-data`), station 104, the nearest
  synoptic station to this line's endpoints (Ballyshannon / Cathaleen's
  Fall / Srananagh). 173,818 hourly rows, Oct 1997–Sept 2026. No gust
  column in this archive (older Met Éireann live feed has one; the
  historical archive doesn't) — not needed for the thermal model used
  here, which is driven by mean wind speed and air temperature.
- **Thermal model parameters** (conductor diameter 0.0286 m, emissivity
  0.5, absorptivity 0.5, max conductor temperature 75°C, reference wind
  speed 0.6 m/s, reference ambient 20°C): standard engineering
  assumptions for this conductor class, not this specific line's real
  TYTFS spec — the kit's own README states line lengths are placeholders
  and true operational ratings aren't published, so these are stated
  assumptions, not invented facts about this line.
- **WIND GENERATION != WIND WEATHER**, restated because it's the easiest
  thing to get wrong here: the network's own modelled wind-farm output
  (WP2033/SV2033's generation scenario) is completely untouched by this
  work. Nothing here recalculates generation from Met Éireann wind speed
  — only this one line's thermal rating changes.
- **This is still a representative seasonal rating, not genuine
  hour-by-hour DLR** — one constant multiplier per season, same
  limitation the original script had, just now grounded in real
  observations instead of a round guess. The network's 168 snapshots are
  a modelled scenario week (confirmed in the kit's own README: "no
  individual hour in them ever happened"), so there's no honest way to
  align real calendar hours against them.
- **"Dispatch-down" is not curtailment** in the SEM/EirGrid sense (no
  SNSP constraint, no inertia constraint, no unit commitment in this
  model) — straight from `gridkit.dispatch_down()`'s own docstring. The
  MWh figures above are the simple before/after total (matching what this
  redo, like the original, was asked to report), not the
  constraint-based-only component `examples/b_lopf_dispatch.py`'s
  `_congestion_share()` method would isolate.

## Open items

- ~~SV2033 arbitrary-sweep dispatch-down numbers hadn't been computed~~ —
  done: `j_dlr_rating_sensitivity.py SV2033 north-west 5041-17010-2` has
  now been run for real (21,814/20,803/20,098/19,695 MWh at +0/10/20/30%,
  matching the SV2033 hours-at-rating sweep — 89/76/66/54 — exactly). The
  summer chart now shows the same full apples-to-apples MWh comparison as
  the winter one: the weather-derived point (19,701.3 MWh at +29.8%
  uplift) lands right next to the sweep's own +30% point (19,694.8 MWh) —
  another independent cross-check that both methods agree.
- See `claude/dlr-cross-team-impact.md` (shared project) for how this
  affects Harshitha's and Alex's sections — short version: Harshitha's
  battery sizing should know the winter constraint it's solving for
  mostly disappears under real DLR; Alex's Q6 numbers are baseline-rating
  dependent and would shrink under a DLR-adjusted baseline, though his
  method doesn't need to change.

## What's next

Files ready to hand off now. Same slide pairing the original section
suggested — same x-axis as Q1's thermal-rating chart, drop-in replacement
for the panel deck. Worth citing the same DLR literature (Trivedi &
Chandran, CIGRE 2024) alongside these results — that paper's own finding
(wind speed the dominant driver, 0.84 Pearson correlation) is exactly
what this redo's methodology is built on, just applied to this specific
line's real nearby weather station instead of taken as a general range.
