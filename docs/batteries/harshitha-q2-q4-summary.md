# Q2 (Battery siting/sizing) + Q4 (Developer siting narrative) — Harshitha

North-West, WP2033, monitored circuit `5041-17010-2` (Srananagh–Cathaleen's Fall, 210 MVA static / 213 MVA real winter DLR — see below) — the same target line as Lucy's Q1/Q5 (`TRACK_A_SUMMARY_1.md`) and Chibuikeim's Q3 (`dlr-2024-real-weather-rewrite.md`). Scripts: `k_battery_siting_sizing.py` (static rating), `k_battery_siting_sizing_DLR-PATCHED.py` (real DLR rating), `l_battery_validation.py` (inserts the recommended batteries and re-solves — see "Validation" section, this is new).

**This file supersedes both the original `harshitha-q2-q4-summary.md` and the interim `harshitha-q2-q4-summary (2).md` — there is now only one authoritative version. Delete the `(2)` copy once this is pushed, so nobody edits the wrong one.**

## One correction to the task brief

The brief says to size from `hourly_flows.csv`'s flow/limit columns ("worst-hour MW reduction," "summed MWh-over-limit"). That doesn't work here: the LOPF that produced those flows already respects the line's rating, so flow never exceeds `limit_MW` — there's no "excess" to read off the flow column. What's actually lost is wind output withheld to keep the line at its cap, and that only shows up in the generator dispatch, not the line flow. So this re-solves the network directly and reads dispatch-down from there.

## Method, and a bug caught + fixed along the way

Splitting constraint-based vs. surplus-based dispatch-down **per generator** by subtracting (real-ratings run) − (all-ratings-lifted run) is invalid — lifting ratings can shift the whole optimal dispatch pattern, so an individual generator's loss can go *down* when ratings are lifted even though the aggregate is well-behaved. (Caught this directly: one generator showed 0 MW curtailed with real ratings but 88 MW curtailed with ratings lifted, at one hour — a different dispatch pattern, not this constraint.) That's exactly why the kit's own `examples/b_lopf_dispatch.py` only ever reports this split as one number for the whole system.

Fixed by splitting at the aggregate-hourly level (matches the kit's own whole-week method exactly), then allocating each hour's validated total across generators pro-rata by their own share of that hour's real curtailment.

**Corrected total at the static 210 MVA rating: 588.6 MWh of wind curtailed for this constraint over the 168-hour week.**

## DLR reconciliation — real number, both re-runs done

Chibuikeim's Q3 result was corrected from a retracted 301.9 MVA (+43.7%) figure to a real, weather-derived 213.0 MVA (+1.4%) winter rating (`dlr-2024-real-weather-rewrite.md`). `k_battery_siting_sizing_DLR-PATCHED.py` has now actually been re-run at the corrected rating, not left as a pending TODO:

| Rating | Total dispatch-down (week) | Constraint-based only |
|---|---|---|
| 210 MVA (static) | 3,660.6 MWh | **588.6 MWh** |
| 213 MVA (real winter DLR) | 3,579.8 MWh | **507.8 MWh** (−13.7%) |
| 3,072.0 MWh (surplus-only floor, ratings lifted) | — | — |

DLR meaningfully helps (13.7% reduction) but does **not** eliminate the constraint the way the retracted 301.9 MVA figure implied — consistent with Q3's own "DLR helps a lot, doesn't solve it alone" framing for this rating. At 213 MVA a new nonzero contributor appears at the margin: Cathaleen's Fall (26.2 MWh, 99.8% cumulative) — negligible next to Drumkeen (336.7 MWh, 66.3%) and Binbane (144.1 MWh, 94.7%), but worth knowing it's there if a judge asks for the full per-generator table at the DLR rating.

**Present both numbers.** Use 588.6 MWh (static) as the sizing basis for the battery recommendation below — that's the more conservative, defensible design point — and cite 507.8 MWh only when specifically discussing DLR's own effect.

## Sign matters more than magnitude — checked against real dispatch, not just the shift-factor sheet

`shift_factors_1.csv` has two groups on this circuit:

| group | members | shift factor |
|---|---|---|
| A | Corderry, Glenree, Sligo | **+0.579** |
| B | Ardnagappary, Tievebrack, Binbane, Cathaleen's Fall, Clogher, Croaghonagh, Drumkeen, Letterkenny, Trillick, Sorne Hill | **−0.238** |
| — | Moy | ~0.000 (not electrically on this corridor) |

Largest magnitude is group A (Corderry, 0.579). But the sign is opposite to group B, and sign — not magnitude — determines whether curtailing a farm relieves this line or worsens it: flow on this circuit is negative every one of the 52 binding hours, so a positive-shift-factor farm structurally cannot relieve it.

**Confirmed against the actual solved dispatch: Corderry, Glenree, and Sligo each show 0.0 MWh of constraint-based curtailment across the entire week** — the optimiser never once curtails them for this constraint, exactly as the sign predicts. Every megawatt-hour of the 588.6 MWh sits in group B.

**Flag for the team — Track A's Q5 section currently states "Corderry wind alone offers 43 MW" of relief at the peak hour.** That's the raw |shift factor| × available-MW number, before checking sign against this line's actual flow direction — the same "pick the largest |shift factor|" trap this section exists to correct. Worth a one-line caveat there (or a pointer to this doc) before the panel, since a judge who checks the actual dispatch would find Corderry contributes zero real relief on this line.

## Where the curtailment actually concentrates (static 210 MVA)

| rank | node | MWh curtailed (week) | cumulative % |
|---|---|---|---|
| 1 | **Drumkeen** | 346.5 | 58.9% |
| 2 | **Binbane** | 197.9 | 92.5% |
| 3 | Letterkenny | 41.1 | 99.5% |
| 4 | Clogher | 3.1 | 100.0% |
| — | Ardnagappary, Tievebrack, Cathaleen's Fall, Croaghonagh, Trillick, Sorne Hill, Moy | 0.0 | — |

Two sites — Drumkeen and Binbane — cover 92.5% of everything, which is a different picture from nameplate capacity (Croaghonagh is the largest group-B generator at 139.2 MW and contributes 0.0 MWh) — impact tracks which farms are actually generating heavily in the hours the corridor is already full, which only the real dispatch run reveals.

## Hand-derived siting & sizing (screening estimate — see Validation section below before quoting these as a firm recommendation)

**Single site — Drumkeen:** covers 58.9% of all constraint-based curtailment on its own.
- Power rating: **42.9 MW** (worst single hour)
- Energy, conservative (sum of every curtailed hour, no discharge in between): **346.5 MWh**
- Energy, realistic (largest contiguous congestion episode): **100.8 MWh over a 4-hour episode**

**Two sites — Drumkeen + Binbane:** covers 92.5% combined.
- Power rating: **48.4 MW** (worst combined hour)
- Energy, conservative: **544.4 MWh**
- Energy, realistic (largest contiguous episode): **232.6 MWh over 6 hours**

## Validation — batteries actually inserted and re-solved (`l_battery_validation.py`, new)

The gap flagged in earlier drafts of this document — "no run here actually inserts a battery of the recommended size at the recommended bus and re-solves to confirm it removes the constraint-based curtailment" — has now been closed. `l_battery_validation.py` uses `gridkit.add_battery()` to place batteries at Drumkeen (and Binbane) at the sizes above, then re-solves the full LOPF and re-measures constraint-based dispatch-down, at the static 210 MVA baseline (588.6 MWh).

**Real result — materially smaller relief than the hand-derived numbers implied:**

| Scenario | Battery spec | Constraint-based remaining | Relief |
|---|---|---|---|
| Baseline | — | 588.6 MWh | — |
| Drumkeen only, episodic | 42.9 MW / 100.8 MWh | 557.6 MWh | **5.3%** |
| Drumkeen only, conservative | 42.9 MW / 346.5 MWh | 466.2 MWh | **20.8%** |
| Drumkeen + Binbane, episodic | 42.9 MW/100.8 MWh + 48.4 MW/146.3 MWh | 546.3 MWh | **7.2%** |
| Drumkeen + Binbane, conservative | 42.9 MW/346.5 MWh + 48.4 MW/197.9 MWh | 399.3 MWh | **32.2%** |

**Headline: the recommendation above does not deliver anything close to the 58.9%/92.5% coverage the worst-hour/worst-episode reading implied.** Even the larger "conservative" sizing only reaches 20.8%/32.2% real relief once the battery's own charge/discharge behaviour is allowed to interact with the rest of the network's dispatch. The smaller "episodic" sizing — the one this document previously recommended leading with in the deck as "small, realistic, buildable" — performs worst of all (5.3%/7.2%). A battery sized to only its single worst episode has no capacity left for the *other* congestion episodes in the week, and recharging after one episode interacts with hours the hand-derived method never examined.

One more wrinkle worth knowing before a judge asks about it: for the two-battery episodic case, two different (and equally legitimate) ways of computing "constraint-based MWh" disagree — 619.8 MWh by the exact method `k_battery_siting_sizing.py` uses (clip each hour's difference at zero, then sum) vs. 546.3 MWh by a simpler whole-week-totals-then-subtract method. They agree everywhere else in this project; they only diverge once a battery is present, because in 2 of the 168 hours the "ratings-lifted" counterfactual run curtails *more* than the real-ratings run with the same battery installed (an artifact of the battery charging differently across the two counterfactuals). Full explanation in `l_battery_validation.py`'s own docstring.

**What this means for the pitch:** present the battery section as a two-stage story rather than a single sizing number — "a 42.9 MW / 346.5 MWh battery at Drumkeen, actually re-solved, delivers ~21% real relief; getting materially higher requires either a bigger battery than the naive worst-episode reading suggests, or accepting that a battery alone won't close this gap and DLR (13.7% at the real 213 MVA rating) needs to be counted alongside it, not instead of it." That's a more defensible, and more interesting, panel answer than a single "battery solves 92.5% of this" number that doesn't survive a re-solve.

## Q4 — Developer siting narrative

**One-sentence version:** on this corridor, whether a location is good for a wind developer or a battery developer isn't a matter of degree — it's which side of Srananagh you're on.

**Attractive for new wind (low risk of adding to this constraint):** Corderry, Glenree, Sligo — the positive-shift-factor group. New capacity here sits electrically close to the Srananagh import point; more output there relieves the constraint rather than adding to it. Confirmed against real dispatch: zero curtailment here across the whole week, regardless of how much they generated.

**Attractive for BESS (this is where the real problem lives):** the negative-shift-factor group, but overwhelmingly concentrated at two of its ten members — Drumkeen and Binbane, 92.5% of the *curtailment* between them (not the same as 92.5% of *relief* — see Validation above for why those aren't interchangeable). New wind added at these two without storage directly worsens dispatch-down; storage sited here directly relieves it, just not by as much as the curtailment share alone would suggest.

**The threshold isn't a number, it's a side, and even the side isn't the whole story.** The group clusters tightly on shift factor alone (−0.238 for ten different farms), so magnitude alone doesn't discriminate within it — but it also doesn't reveal that two farms dominate while eight contribute nothing, or that "dominates curtailment" isn't the same claim as "a battery sized to that farm's numbers delivers proportional relief." Both distinctions only came from the real dispatch runs: shift factors tell you the mechanism, not the answer, and a hand-derived MWh reading doesn't substitute for actually re-solving with the battery in place.

**Honest caveats for this slide:** WP2033 is a synthetic weather week (Ornstein–Uhlenbeck / Gaussian-field wind, not historical or forecast) — MWh figures are indicative of the mechanism, not a real-world forecast for these specific farms. Wind `marginal_cost` is **0.0** in every shipped `generators.csv` (not −1 EUR/MWh as an earlier draft of this note and the kit README stated) — costs are round-number placeholders either way, but 0.0 specifically means curtailment among same-side wind farms is **cost-neutral to the optimiser**, so the exact per-farm split within group B is an LP-degenerate result — the pro-rata-by-real-curtailment allocation above is a reasonable way to break that tie, but a different solver or solver version could plausibly redistribute the split differently while landing on the same 588.6 MWh aggregate. Say the total with confidence; say the specific per-farm ranking as "this run's result," not as a uniquely determined fact. This is a DC linear approximation — no voltage, no reactive power, no N-1 — a screening result, not an operational recommendation.

---
*Reproducible with `python k_battery_siting_sizing.py` (static rating), `python k_battery_siting_sizing_DLR-PATCHED.py` (real DLR rating), and `python l_battery_validation.py` (battery insertion + re-solve) from the repo root — all three need `grid_TF_Wind/participant-kit` on the path, as in each script's header. All three re-run and cross-checked against this repo's own copy of the kit before this commit.*
