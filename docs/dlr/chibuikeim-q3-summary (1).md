# Q3 — Dynamic Line Rating (DLR) proxy on the target line

> **Note:** the numbers in this document (the arbitrary-uplift proxy
> sweep) are still accurate and are explicitly labelled as a proxy, not
> real DLR — nothing here needs correcting. A follow-up real-weather DLR
> analysis now exists (`dlr-2024-real-weather-rewrite.md`), which answers
> the same question with real Met Éireann weather instead of a round
> guessed uplift: the real result is +1.4% winter / +3.6% summer, a much
> smaller uplift than this sweep alone would suggest is plausible. Present
> this document's sweep as the honest proxy method it was, and pair it
> with the real-weather rewrite rather than in place of it.

Network: `WP2033` (2033 winter peak), scope: `north-west`, target line:
**`5041-17010-2`** (the Q1 target line — 100% max loading, 52/168 hours at
rating in the unmodified baseline, confirmed reproduced below). New script:
`examples/j_dlr_rating_sensitivity.py`, lives in `participant-kit/examples/`
alongside the rest of the kit — copy the whole `participant-kit` folder or
re-run yourself; both are one command below.

---

## Question being answered

*"How could Dynamic Line Rating reduce the amount of wind constraint on
our model?"*

## Method

DLR raises a conductor's real-time thermal rating using live weather data
— mainly wind speed, which cools the conductor. The kit's own
`gridkit.set_rating()` can only set **one fixed MVA value** for the whole
week, not an hour-by-hour weather-driven series, so this script tests
*"what if the rating were permanently raised by X%"* as a stand-in for real
DLR, not a literal simulation of live weather-based uplift. **This
distinction matters and is stated explicitly in the script's own output —
repeat it in the panel writeup, don't let this get read as literal DLR.**

For each uplift factor (0%, +10%, +20%, +30% — range chosen to match
published DLR pilot results, see justification below), the script:
1. loads a fresh copy of the network,
2. applies `gridkit.set_rating(n, "5041-17010-2", base_rating * (1 + factor))`,
3. re-solves fresh: `gridkit.solve(n)` → `gridkit.freeze_dispatch(n)` →
   `n.lpf(n.snapshots)` — this exact order, every time (skipping
   `freeze_dispatch` gives nonsense, per the kit's own warning),
4. reads `gridkit.line_loading(n)` for hours at rating (`>= 0.999`) on the
   target line, and `gridkit.dispatch_down(n)` for MWh of wind actually
   recovered.

```bash
python examples/j_dlr_rating_sensitivity.py WP2033 north-west 5041-17010-2
```

## Results

| uplift | rating (MVA) | hours at rating (of 168) | wind dispatch-down (MWh/week) |
|---|---|---|---|
| **+0%** | 210 | **52** | 3,661 |
| +10% | 231 | 39 | 3,233 |
| +20% | 252 | 19 | 3,077 |
| +30% | 273 | 13 | 3,072 |

The `hours_at_rating` column at +0%/+10%/+20%/+30% (52/39/19/13) matches
Track A's own thermal-rating sensitivity table exactly — good
cross-confirmation that both scripts are solving the same network the
same way.

**Key finding — diminishing returns, and a visible plateau.** Going from
+0% to +10% recovers ~430 MWh/week of wind for a modest rating increase.
But +20% → +30% barely moves wind recovered at all (3,077 → 3,072 MWh)
even though hours-at-rating keeps falling (19 → 13). That gap between the
two metrics is worth flagging explicitly: past a point, the remaining
constrained hours are ones where something else in the network — not
just this one line's rating — is the actual limiting factor. This lines up
with Track A's own audit note that transformers aren't checked by the
stock kit and could be a hidden constraint elsewhere.

Full long-form results: `figures/j_dlr_sensitivity_WP2033_north-west.csv`
and `figures/j_dlr_sensitivity_WP2033_north-west.png` (both attached,
chart uses the same x-axis — rating uplift % — as Q1's thermal-rating
chart, so they can sit side by side in the deck).

## Why 0/10/20/30% specifically (citable justification, not arbitrary)

Pulled from *"A Data-Driven Machine Learning Framework for Day-ahead
Estimation of Dynamic Line Rating in Power Systems"* (Trivedi & Chandran,
EirGrid Group, CIGRE 2024 Paris Session, Paper ID 10912) — a real EirGrid
DLR pilot on a 110 kV Irish line:
- Wind speed is by far the strongest driver of DLR headroom: **0.84
  Pearson correlation** with line rating, vs. slightly negative for
  temperature and near-zero for precipitation/direction.
- Their pilot line's real DLR reached **~1,400 A against a 550 A static
  summer rating** in winter — over 2.5x uplift at peak.
- Cited literature ranges: **10–15% average capacity increase** (TWENTIES
  project) up to **30%** (Malaysia pilot).

This justifies the +10/+20/+30% test range as literature-grounded rather
than picked arbitrarily, and gives a physical story (wind cools the
conductor, raising capacity right when wind output — and curtailment risk
— is highest) to go with the numbers. Worth citing this paper directly in
the presentation.

## Open items / not done here

- This only tests the single Q1 target line (`5041-17010-2`), not the
  other two candidate lines from Track A's original top-3 — matches Q1's
  own finding that only the target line ever binds in this scope, so
  widening the others wouldn't have changed anything anyway.
- Not tested on `all-island` scope — this was scoped to `north-west` to
  match the rest of the team's target-line work.
- The fixed-rating-uplift proxy (vs. real weather-driven hourly DLR)
  limitation is the main caveat to carry into the panel Q&A — see Method
  above.

## What's next

Files ready to hand off now. Pairs directly with Track A's Q1 thermal-
rating chart (same x-axis) — suggest Lucy puts them on the same slide.
Also worth a quick cross-check with Kanyisola's Q2 battery sizing: if DLR
recovers most of the available wind cheaply at +10–20%, that changes how
much battery capacity is actually needed to fully eliminate the remaining
constraint — worth a joint sentence in the writeup on DLR + battery as
complementary rather than competing solutions.
