"""(e) Edge-to-edge flow susceptibility, dF_e/dB_e', and Braess's paradox.

    python examples/e_braess_susceptibility.py [SCENARIO] [SCOPE] [MONITORED]

Builds the full susceptibility matrix - how the flow on every branch responds
to a change in every branch's susceptance - and then uses it to answer the
question a planner actually has: which reinforcements would make my worst
circuit worse?  Writes ``figures/e_braess_<scenario>_<scope>.png``.

Braess's paradox is usually told about traffic, where adding a road can slow
everybody down.  In a power network the same thing happens because flow is not
routed, it is *imposed*: the power divides between parallel paths in inverse
proportion to their reactances, and nothing consults the ratings.  Build a
second circuit somewhere and every impedance ratio in that mesh changes.  Some
of those changes push more power onto a circuit that was already full.

The matrix says which.  Differentiating ``F = B K^T L+ p``:

    dF_e/dB_e'  =  delta(e,e') * dtheta_e  -  B_e * (k_e^T L+ k_e') * dtheta_e'

The diagonal is the obvious part - make a branch more conductive and it takes
more of its own flow.  The off-diagonal is Braess: a **positive** entry for a
monitored circuit ``e`` means that strengthening ``e'`` loads ``e`` further.

This script does not ask you to take that on trust.  It picks the strongest
positive candidate, actually doubles that branch's susceptance, re-solves the
power flow, and prints what the monitored circuit did.
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import flowmath
import gridkit
import plotstyle

FIGURES = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "figures")


def main(scenario="WP2033", scope="all-island", monitored=None):
    plotstyle.use()
    gridkit.quiet()
    n = gridkit.load(scenario, scope)
    gridkit.solve(n)
    gridkit.freeze_dispatch(n)
    n.lpf(n.snapshots)

    loading = gridkit.line_loading(n)
    snapshot = loading.max(axis=1).idxmax()
    monitored = monitored or loading.loc[snapshot].idxmax()
    print(f"snapshot {snapshot}; monitored circuit {monitored} at "
          f"{loading.at[snapshot, monitored]:.1%} of its "
          f"{n.lines.at[monitored, 's_nom']:.0f} MVA rating\n")

    frame = flowmath.branches(n)
    candidates = flowmath.braess_candidates(n, snapshot, monitored, frame)
    others = candidates.drop(index=monitored, errors="ignore")
    worse = others[others["d_flow_per_d_susceptance"] > 0]
    better = others[others["d_flow_per_d_susceptance"] < 0]

    print(f"{len(others)} other branches: strengthening {len(worse)} of them "
          f"increases the flow on {monitored}, {len(better)} decreases it")
    print("\nstrengthen these and the monitored circuit gets WORSE "
          "(Braess candidates)")
    print(worse.head(8)[["d_flow_per_d_susceptance", "susceptance",
                         "s_nom", "kind"]].round(4).to_string())
    print("\nstrengthen these and it gets better")
    print(better.head(8)[["d_flow_per_d_susceptance", "susceptance",
                          "s_nom", "kind"]].round(4).to_string())

    demonstration = None
    if len(worse):
        demonstration = _demonstrate(
            scenario, scope, snapshot, monitored, worse.index[0], frame,
            float(worse["d_flow_per_d_susceptance"].iloc[0]))

    _draw(n, candidates, monitored, snapshot, demonstration, scenario, scope)
    return 0


def _demonstrate(scenario, scope, snapshot, monitored, culprit, frame,
                 predicted):
    """Double one branch's susceptance and see what the monitored one does.

    The matrix is a derivative, so it predicts the response to an
    infinitesimal change; doubling a susceptance is emphatically not
    infinitesimal, and the linear prediction and the re-solved flow will not
    agree to the decimal.  The **sign** is the claim being tested.
    """
    m = gridkit.load(scenario, scope)
    gridkit.solve(m)
    gridkit.freeze_dispatch(m)
    m.lpf(m.snapshots)
    before = float(m.lines_t.p0.at[snapshot, monitored])
    series_before = m.lines_t.p0[monitored].copy()

    added = float(frame.at[culprit, "susceptance"])      # +100%
    target = m.lines if culprit in m.lines.index else m.transformers
    target.loc[culprit, "x"] = target.at[culprit, "x"] / 2.0
    target.loc[culprit, "s_nom"] = target.at[culprit, "s_nom"] * 2.0
    m.lpf(m.snapshots)                      # same dispatch, different network
    after = float(m.lines_t.p0.at[snapshot, monitored])
    series_after = m.lines_t.p0[monitored].copy()

    print(f"\ncheck: doubled the susceptance of {culprit} "
          f"(what a second circuit on the same route does), dispatch held")
    print(f"  linear prediction  {predicted * added:+,.1f} MW")
    print(f"  actual power flow  {after - before:+,.1f} MW "
          f"({before:+,.1f} -> {after:+,.1f})")
    print("  " + ("the reinforcement made the monitored circuit worse - "
                  "this is Braess's paradox on a real network"
                  if abs(after) > abs(before) else
                  "the reinforcement helped after all: the derivative is "
                  "local and a 100% change is not"))
    return {"culprit": culprit, "before": before, "after": after,
            "predicted": predicted * added,
            "series_before": series_before, "series_after": series_after,
            "rating": float(m.lines.at[monitored, "s_nom"])}


def _draw(network, candidates, monitored, snapshot, demonstration,
          scenario, scope):
    os.makedirs(FIGURES, exist_ok=True)
    fig, (left, right) = plt.subplots(1, 2, figsize=(11.0, 5.6),
                                      width_ratios=(1.25, 1.0))
    for ax in (left, right):
        ax.set_axisbelow(True)

    # Left: the branches that matter most for this circuit, signed.  A
    # diverging pair, because the sign is the whole point.
    top = candidates.drop(index=monitored, errors="ignore").head(14)
    top = top.iloc[::-1]
    values = top["d_flow_per_d_susceptance"].to_numpy()
    colours = [plotstyle.STATUS["serious"] if v > 0
               else plotstyle.CATEGORICAL[0] for v in values]
    left.barh(range(len(top)), values, color=colours, height=0.62)
    left.set_yticks(range(len(top)), list(top.index), fontsize=7)
    left.set_ylim(-1.9, len(top) - 0.4)     # an empty row for the legend
    left.axvline(0.0, color=plotstyle.INK_MUTED, linewidth=0.8)
    left.set_xlabel("dF/dB on the monitored circuit "
                    "(MW per MW/radian of added susceptance)")
    left.set_title(f"what moves {monitored}", fontsize=10)
    left.grid(axis="y", visible=False)
    # Patch proxies, not zero-height bars: a dummy bar is still a bar and
    # matplotlib widens the x-axis to fit it, which flattened this chart to
    # nothing the first time.
    from matplotlib.patches import Patch
    left.legend(handles=[
        Patch(color=plotstyle.STATUS["serious"],
              label="strengthening this loads it MORE"),
        Patch(color=plotstyle.CATEGORICAL[0],
              label="strengthening this relieves it")], loc="lower right")

    # Right: the week of flows, before and after the reinforcement.  Two bars
    # of 123 and 127 MW hide a 3.5% change behind a zero baseline; the same
    # change over 168 hours against the rating line is legible.
    if demonstration:
        rating = demonstration["rating"]
        hours = np.arange(len(demonstration["series_before"]))
        right.plot(hours, demonstration["series_before"].abs().to_numpy(),
                   color=plotstyle.INK_MUTED, linewidth=1.6,
                   label="before")
        right.plot(hours, demonstration["series_after"].abs().to_numpy(),
                   color=plotstyle.STATUS["critical"], linewidth=1.6,
                   label=f"after doubling {demonstration['culprit']}")
        right.axhline(rating, color=plotstyle.INK, linewidth=1.2,
                      linestyle=(0, (4, 2)))
        right.annotate(f"rating {rating:,.0f} MVA", (0.99, rating),
                       xycoords=("axes fraction", "data"), ha="right",
                       va="bottom", fontsize=8, color=plotstyle.INK)
        worse = int((demonstration["series_after"].abs()
                     > demonstration["series_before"].abs() + 1e-6).sum())
        right.set_ylabel(f"|flow| on {monitored} (MW)")
        right.set_xlabel(f"hour of the week - heavier in {worse} of "
                         f"{len(hours)} of them")
        right.set_xlim(0, len(hours) - 1)
        right.set_ylim(0, None)
        right.set_title("the prediction, tested over the week", fontsize=10)
        right.legend(loc="lower right", ncol=1)
    else:
        right.text(0.5, 0.5, "no branch increases the flow on this circuit",
                   ha="center", va="center", color=plotstyle.INK_SOFT)
        right.set_axis_off()

    fig.suptitle(f"{scenario} {scope} at {snapshot:%Y-%m-%d %H:%M}: "
                 f"edge-to-edge susceptibility", x=0.012, ha="left",
                 fontsize=12, fontweight="bold", color=plotstyle.INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    path = os.path.join(FIGURES, f"e_braess_{scenario}_{scope}.png")
    fig.savefig(path, bbox_inches="tight")
    print(f"\n-> {path}")


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
