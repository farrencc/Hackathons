"""(d) PTDF from the Moore-Penrose pseudoinverse of the Laplacian.

    python examples/d_ptdf.py [SCENARIO] [SCOPE] [MONITORED_CIRCUIT]

Builds the network's weighted Laplacian ``L = K B K^T``, inverts it with the
Moore-Penrose pseudoinverse, and reads the power transfer distribution factors
straight off it: ``PTDF = B K^T L+``.  Then checks the answer against a PyPSA
power flow, because a PTDF that has not been checked against a flow is a
matrix of plausible numbers.  Writes ``figures/d_ptdf_<scenario>_<scope>.png``.

Why the pseudoinverse and not a slack bus.  ``L`` is singular: adding the same
angle to every bus changes nothing, so the constant vector is in its
nullspace.  The textbook fix is to delete a row and a column - pick a slack -
and invert what is left.  That works, but it writes the arbitrary choice of
slack into every number that comes out.  ``L+`` instead returns the solution
orthogonal to the nullspace, which is the one where the balancing megawatt is
spread evenly over the buses.  The choice has not gone away; it has become
explicit, and :func:`flowmath.shift_factors` lets you change it to a
load-weighted or single-bus reference without rebuilding anything.
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

    frame = flowmath.branches(n)
    K, buses, edges = flowmath.incidence(n, frame)
    L, _, _ = flowmath.laplacian(n, frame)
    Lp = flowmath.pseudoinverse(L)
    print(f"{len(buses)} buses, {len(edges)} branches")
    print(f"Laplacian {L.shape}, rank {np.linalg.matrix_rank(L)} "
          f"-> nullspace dimension {len(buses) - np.linalg.matrix_rank(L)} "
          f"(one per connected component)")
    print(f"L L+ L == L to {np.abs(L @ Lp @ L - L).max():.2e}")

    matrix = flowmath.ptdf(n, frame)
    print(f"PTDF {matrix.shape}; each row sums to "
          f"{matrix.sum(axis=1).abs().max():.2e} "
          f"(it must: injecting 1 MW at every bus at once moves nothing)")

    # The check.  Solve a dispatch, flow it, and rebuild the same flows from
    # the PTDF and the bus injections.  If these disagree, one of them is
    # wrong, and it is worth knowing which before building anything on top.
    gridkit.solve(n)
    gridkit.freeze_dispatch(n)
    n.lpf(n.snapshots)
    snapshot = n.loads_t.p_set.sum(axis=1).idxmax()

    from_ptdf = flowmath.flows(n, snapshot, frame)
    from_lpf = pd.concat([n.lines_t.p0.loc[snapshot],
                          n.transformers_t.p0.loc[snapshot]
                          if len(n.transformers) else pd.Series(dtype=float)])
    both = pd.DataFrame({"ptdf_mw": from_ptdf,
                         "lpf_mw": from_lpf.reindex(from_ptdf.index)}).dropna()
    error = (both["ptdf_mw"] - both["lpf_mw"]).abs()
    shifters = int((frame["phase_shift"].abs() > 1e-9).sum())
    if shifters:
        print(f"\n{shifters} phase-shifting transformers in this network - "
              f"the largest at "
              f"{np.degrees(frame['phase_shift'].abs().max()):.0f} degrees.")
        print("A shifter imposes an angle of its own, so the flow is "
              "b*(theta_i - theta_j - phi) and\nthe bus equation gains "
              "K B phi on its right-hand side.  It behaves exactly like a "
              "pair of\nequal and opposite injections, so the PTDF is "
              "unchanged and only the flows shift.\nIgnore it and this check "
              "comes out at 79 MW rather than 1e-10.")
    print(f"\nat {snapshot}: PTDF flows vs n.lpf() over {len(both)} branches, "
          f"max |difference| {error.max():.3e} MW")

    monitored = monitored or gridkit.line_loading(n).max().idxmax()
    print(f"\nmonitored circuit: {monitored} "
          f"({n.lines.at[monitored, 's_nom']:.0f} MVA)")
    column = matrix.loc[monitored]
    ranked = column.reindex(column.abs().sort_values(ascending=False).index)
    print("buses whose injection this circuit feels most "
          "(MW on the circuit per MW injected, balanced evenly island-wide)")
    print(ranked.head(12).round(4).to_string())

    _draw(n, column, monitored, both, error, scenario, scope)
    return 0


def _draw(network, column, monitored, both, error, scenario, scope):
    os.makedirs(FIGURES, exist_ok=True)
    fig, (left, right) = plt.subplots(1, 2, figsize=(11.2, 6.0),
                                      width_ratios=(1.15, 1.0))
    for ax in (left, right):
        ax.set_axisbelow(True)

    # Left: the PTDF column on the map.  A signed quantity, so a diverging
    # ramp with a neutral middle - blue draws flow one way, red the other.
    placed = gridkit.placed_buses(network)
    values = column.reindex(placed.index).fillna(0.0)
    limit = float(np.nanpercentile(values.abs(), 99)) or 1e-6
    for _, line in network.lines.iterrows():
        if line["bus0"] in placed.index and line["bus1"] in placed.index:
            left.plot([placed.at[line["bus0"], "x"], placed.at[line["bus1"], "x"]],
                      [placed.at[line["bus0"], "y"], placed.at[line["bus1"], "y"]],
                      color="#e6e5e1", linewidth=0.6, zorder=1)
    order = values.abs().sort_values().index
    dots = left.scatter(placed.loc[order, "x"], placed.loc[order, "y"],
                        c=values[order], cmap=plotstyle.diverging_cmap,
                        vmin=-limit, vmax=limit, s=16, zorder=3,
                        linewidths=0.4, edgecolors=plotstyle.SURFACE)
    if monitored in network.lines.index:
        line = network.lines.loc[monitored]
        if line["bus0"] in placed.index and line["bus1"] in placed.index:
            left.plot([placed.at[line["bus0"], "x"], placed.at[line["bus1"], "x"]],
                      [placed.at[line["bus0"], "y"], placed.at[line["bus1"], "y"]],
                      color=plotstyle.INK, linewidth=2.4, zorder=4)
            left.annotate(monitored,
                          (np.mean([placed.at[line["bus0"], "x"],
                                    placed.at[line["bus1"], "x"]]),
                           np.mean([placed.at[line["bus0"], "y"],
                                    placed.at[line["bus1"], "y"]])),
                          xytext=(-14, 22), textcoords="offset points",
                          ha="right", fontsize=8, color=plotstyle.INK,
                          arrowprops=dict(arrowstyle="-",
                                          color=plotstyle.INK_SOFT,
                                          linewidth=0.8))
    bar = fig.colorbar(dots, ax=left, orientation="horizontal",
                       fraction=0.045, pad=0.03, shrink=0.85)
    bar.set_label("MW on the monitored circuit per MW injected",
                  color=plotstyle.INK_SOFT)
    bar.outline.set_visible(False)
    margin = 0.25
    left.set_xlim(placed["x"].min() - margin, placed["x"].max() + margin)
    left.set_ylim(placed["y"].min() - margin, placed["y"].max() + margin)
    left.set_aspect(1 / np.cos(np.radians(float(placed["y"].mean()))))
    left.set_xticks([]); left.set_yticks([]); left.grid(False)
    for spine in left.spines.values():
        spine.set_visible(False)
    left.set_title(f"{scenario} {scope}: PTDF column\nfor {monitored}",
                   fontsize=11)

    # Right: the check.  A 45-degree line and the points on it.
    right.scatter(both["lpf_mw"], both["ptdf_mw"], s=12,
                  color=plotstyle.CATEGORICAL[0], alpha=0.75, linewidths=0)
    span = [both.min().min(), both.max().max()]
    right.plot(span, span, color=plotstyle.INK_MUTED, linewidth=1.0,
               linestyle=(0, (4, 2)), zorder=0)
    right.set_xlabel("branch flow from n.lpf() (MW)")
    right.set_ylabel("branch flow from PTDF x injections (MW)")
    right.set_title("the check: two routes to the same flows")
    right.annotate(f"{len(both)} branches\nmax |difference| {error.max():.1e} MW",
                   (0.04, 0.94), xycoords="axes fraction", va="top",
                   fontsize=9, color=plotstyle.INK_SOFT)

    fig.tight_layout()
    path = os.path.join(FIGURES, f"d_ptdf_{scenario}_{scope}.png")
    fig.savefig(path, bbox_inches="tight")
    print(f"\n-> {path}")


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
