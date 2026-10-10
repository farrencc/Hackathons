# Dynamic Line Rating section — presentation summary

> **This document has been rewritten to match the current, authoritative
> DLR result.** An earlier version of this summary quoted 301.9/231.1 MVA
> (+43.7%/+29.8%) figures from a 29-year weather archive with no solar
> radiation and an assumption that wind always hits the line perfectly
> perpendicular (the maximum-cooling case). Those figures are retracted.
> The methodology has been redone: 2024-only weather, real PVGIS solar
> heat gain, and the line's real wind-direction geometry. The real result
> is **213.0 MVA (+1.4%) winter, 184.4 MVA (+3.6%) summer** — the winter
> constraint does NOT disappear. See `dlr-2024-real-weather-rewrite.md`
> for the full methodology and the P10-vs-median caveat (F-05).

---

**The question the panel will ask:** *How could Dynamic Line Rating
reduce the amount of wind constraint on your model?*

**One-line answer to lead with:** a real, weather-derived winter rating
on the north-west's own bottleneck line raises its capacity by 1.4%, and
a real, weather-derived summer rating raises it by 3.6% — both genuine,
data-backed results, and both modest. DLR alone recovers roughly 2% of
either season's dispatch-down; it does not come close to eliminating the
constraint in either season. That's a smaller, more defensible finding
than an earlier draft of this work claimed, and it means DLR and battery
storage are both still needed in winter, not just in summer.

---

## The method — why this isn't a hand-waved "add 20%" number

DLR uses the line's actual current weather (wind cooling the conductor,
air temperature, and solar heating) instead of a fixed worst-case rating,
since a conductor's safe carrying capacity rises when wind speed is
higher and falls when it's hotter or sunnier. This project computed a
*real* rating, not an assumed uplift:

- Real 2024 Met Éireann hourly wind-speed, wind-direction and temperature
  observations from the nearest weather station to the target line
  (Finner Camp, Co. Donegal), filtered by season.
- Real solar radiation (PVGIS, calendar-matched from the most recent
  complete PVGIS year, 2023, onto the 2024 calendar — a documented proxy,
  not invented data; see `dlr-2024-real-weather-rewrite.md`).
- The line's real wind-direction geometry: each hour's wind is resolved
  into its component perpendicular to the line's real 22.33° azimuth
  (derived from the network's own geocoded bus coordinates), not assumed
  to always hit the line head-on.
- A Hilpert-correlation thermal model converts those weather observations
  into a rating multiplier for every historical hour.
- The **P10** value of that multiplier's distribution (the rating that
  representative weather supports at least 90% of the time — a
  conservative, defensible choice) is the representative seasonal rating
  used in the model. **This is the conservative end of a wide
  distribution, not the middle of it** — the median winter hour would
  support a rating over 50% higher than static. See
  `dlr-2024-real-weather-rewrite.md` for the full percentile band.

Applied to **`5041-17010-2`** — the same Srananagh–Cathaleen's Fall line
Lucy's own Q1 work identified as the north-west's sole real bottleneck
(52 of 168 hours at 100% loading, every other line under 73% all week).

| Season | Static rating | Real-weather P10 rating | Uplift |
|---|---|---|---|
| Winter (WP2033) | 210 MVA | **213.0 MVA** | **+1.4%** |
| Summer (SV2033) | 178 MVA | **184.4 MVA** | **+3.6%** |

## Winter finding — a real but small reduction, not elimination

Applying the real 213.0 MVA winter rating and re-solving the full model:

- **Total wind dispatch-down across all 14 north-west farms** (the
  measure this project's own Step 1 work established as the honest way
  to quantify curtailment, once the structural finding that a correctly
  solved LOPF can never show `overload_MW > 0` was understood) drops from
  **3,660.6 MWh/week to 3,579.4 MWh/week** — a reduction of 81.2 MWh, or
  about 2.2% of the static-baseline curtailment.
- This is **not** the theoretical floor (the "ratings lifted entirely"
  case): 3,579.4 MWh is still far above what a fully unconstrained line
  would show. The line remains a real, materially unchanged constraint
  under real winter weather.
- For the battery-sizing work built on this line (Q2): the 588.6
  MWh/week of *network-constraint-based* curtailment that battery was
  being sized against should be expected to shrink only slightly at 213
  MVA, not disappear. **The exact re-solved number is not yet available
  here** — it requires re-running the constraint-based/surplus-based
  split at 213 MVA (script fixed and ready; see
  `k_battery_siting_sizing_DLR-PATCHED.py`), and that number should
  replace this placeholder before this goes in front of a panel.
- No claim is made here about the line dropping out of the all-island
  binding-lines list. Separately from DLR, this line does not appear in
  the all-island binding set at all, because of how the 15-node
  north-west scope reduction changes what is visible as a circuit (see
  Track A audit finding ML-5) — that is a scoping property, not a DLR
  effect, and the two should not be conflated.

## Summer finding — also real, also small

Same method, summer P10 rating (184.4 MVA, +3.6% — a slightly larger
percentage uplift than winter this time, though both are modest):

- Total dispatch-down drops from **21,813.6 MWh/week to 21,406.0
  MWh/week** — a reduction of 407.6 MWh, or about 1.9% of the
  static-baseline curtailment. Proportionally almost identical to
  winter's ~2.2% reduction, despite the much larger absolute summer
  problem.

## The framing this supports: DLR helps a little in both seasons; the battery case is not weakened in either

The season-split "DLR solves winter, battery solves summer" framing from
the earlier draft of this document does not survive the corrected
numbers — winter and summer see proportionally similar, modest reductions
(~2% each), not a large winter effect and a small summer one. The
accurate framing:

> **Real weather-derived DLR is a genuine but modest lever in both
> seasons (roughly 2% of dispatch-down recovered either way). It is a
> legitimate part of the mitigation story, but it does not reduce the
> case for battery storage in winter** — the battery-sizing work (Q2)
> should be re-run against the 213 MVA winter rating to get the
> corrected (almost certainly still substantial) constraint-based
> curtailment figure, rather than assuming DLR has already solved it.

## Robustness — what is and isn't verified yet

- The 213.0/184.4 MVA ratings and the total dispatch-down figures above
  come directly from `dlr-2024-real-weather-rewrite.md`'s own re-solved
  comparison files (`j_seasonal_dlr_comparison_5041-17010-2_{winter,
  summer}_2.csv`) — these are real, re-solved results, not projections.
- **Not yet re-verified**: the corrected rating has not yet been
  re-patched into the Q2 battery-siting model or the Q6 priority-analysis
  model and actually re-run (an earlier version of both scripts was
  patched with the retracted 301.9 MVA value and produced results that
  are now known to be wrong — see `k_battery_siting_sizing_DLR-PATCHED.py`
  and `q6_priority_analysis_DLR-PATCHED.py`, which have been corrected to
  use 213.0 MVA but need an actual re-run against the real kit before
  their output numbers can be quoted anywhere).
- The old document's "independent cross-check" claim (that the arbitrary
  +30% uplift sweep's 3,072 MWh result matched the weather-derived number
  "to rounding") no longer applies — that was a coincidence of the
  retracted 301.9 MVA figure landing near the sweep's own plateau. At the
  corrected +1.4% uplift, 3,579.4 MWh sits, as expected, between the
  sweep's 0% (3,660.6 MWh) and +10% (3,232.8 MWh) points — a sanity check
  that the number is in a physically reasonable range, not a
  "matches independently" claim.

## Caveats worth naming up front, not waiting to be asked

- This is currently a **single-line** result. Real weather-derived DLR
  only exists for `5041-17010-2` so far — no weather station has been
  mapped to any of the project's other lines yet.
- The **P10 threshold is a conservative choice, not the best case, and
  the distribution is wide** — the median winter hour would support a
  rating more than 50% above static (see
  `dlr-2024-real-weather-rewrite.md`'s percentile table). State the band,
  not just the P10 point, if asked how confident this number is.
- Solar input is a documented 2023-onto-2024 calendar-matched proxy
  (PVGIS has not yet published 2024 radiation data) — not actual 2024
  solar observations.
- **Both seasons' results are specific to this modelled scenario week**,
  not a claim that winter or summer curtailment is generally solved.

---

### Quick-reference numbers for slides

| Metric | Value |
|---|---|
| Line DLR was applied to | `5041-17010-2` (the project's own identified bottleneck line) |
| Winter static → real rating | 210 → **213.0 MVA** (+1.4%) |
| Summer static → real rating | 178 → **184.4 MVA** (+3.6%) |
| Winter dispatch-down, static → DLR | 3,660.6 → **3,579.4 MWh/week** (−2.2%) |
| Summer dispatch-down, static → DLR | 21,813.6 → **21,406.0 MWh/week** (−1.9%) |
| Winter constraint-based curtailment (Q2's battery target) | 588.6 → **TBD, pending re-run at 213 MVA — do not present as 0.0** |
| Winter rating distribution | P10 = +1.4% (headline), P50 ≈ +53%, mean ≈ +55% — a wide band, see rewrite doc |
| Headline framing | DLR recovers ~2% of either season's curtailment; battery case stands in both seasons |
