"""DC flow linear algebra: PTDF, Braess susceptibility, and shift factors.

Everything here comes out of one object, the **weighted graph Laplacian** of
the DC network::

    L = K B K^T

where ``K`` is the bus-branch incidence matrix (+1 at ``bus0``, -1 at
``bus1``) and ``B`` is the diagonal matrix of branch susceptances, in MW per
radian.  ``L`` is singular - adding a constant to every voltage angle changes
no flow - so it is inverted with the **Moore-Penrose pseudoinverse**, which
picks the solution orthogonal to that nullspace.  That is not a numerical
trick to get around the singularity; it is the right answer, and it is what
makes the reference bus disappear from the results below.

From ``L+`` follow, in order:

    angles         theta = L+ (p + K B phi)
    flows          F = B (K^T theta - phi)
    PTDF           dF/dp = B K^T L+
    susceptibility dF_e/dB_e'
    shift factors  a PTDF column difference against a chosen reference

Each function checks itself against something that does not depend on it -
PTDF against a PyPSA power flow, susceptibility against finite differences -
and the checks are in ``test_kit.py``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# The graph
# --------------------------------------------------------------------------- #

def branches(network) -> pd.DataFrame:
    """Every DC-flow branch - lines and transformers - with its susceptance.

    Susceptance is ``1 / x_pu_eff`` in MW per radian, taken from PyPSA's own
    per-unit values so that anything computed here agrees with what
    ``n.lpf()`` would do.  Links are not here: a DC link is a controllable
    injection, not part of the linear network.

    ``phase_shift`` is in **radians**, converted from the degrees PyPSA
    stores.  Two of the all-island network's transformers are phase shifters,
    one of them at 17 degrees, and a Laplacian that ignores them is wrong by
    tens of MW on the circuits around them - see :func:`angles`.
    """
    network.calculate_dependent_values()
    rows = []
    for kind, frame in (("Line", network.lines),
                        ("Transformer", network.transformers)):
        if not len(frame):
            continue
        x = frame["x_pu_eff"].to_numpy(dtype=float)
        shift = (np.radians(frame["phase_shift"].to_numpy(dtype=float))
                 if "phase_shift" in frame.columns else np.zeros(len(frame)))
        rows.append(pd.DataFrame({
            "branch": frame.index, "kind": kind,
            "bus0": frame["bus0"].to_numpy(), "bus1": frame["bus1"].to_numpy(),
            "x_pu_eff": x, "susceptance": 1.0 / x,
            "phase_shift": shift,
            "s_nom": frame["s_nom"].to_numpy(dtype=float),
        }))
    if not rows:
        raise ValueError("this network has no lines or transformers")
    return pd.concat(rows, ignore_index=True).set_index("branch")


def incidence(network, branch_frame: pd.DataFrame | None = None
              ) -> tuple[np.ndarray, pd.Index, pd.Index]:
    """The bus-branch incidence matrix ``K``, plus its two labellings.

    ``K[i, e]`` is +1 if bus ``i`` is branch ``e``'s ``bus0``, -1 if it is its
    ``bus1``, and 0 otherwise.  Flow is defined positive from ``bus0`` to
    ``bus1``, which is PyPSA's ``p0``.
    """
    frame = branch_frame if branch_frame is not None else branches(network)
    buses = network.buses.index
    position = {b: i for i, b in enumerate(buses)}
    K = np.zeros((len(buses), len(frame)))
    for e, (_, row) in enumerate(frame.iterrows()):
        K[position[row["bus0"]], e] += 1.0
        K[position[row["bus1"]], e] -= 1.0
    return K, buses, frame.index


def laplacian(network, branch_frame: pd.DataFrame | None = None
              ) -> tuple[np.ndarray, pd.Index, pd.Index]:
    """The weighted Laplacian ``L = K B K^T``, and its labellings."""
    frame = branch_frame if branch_frame is not None else branches(network)
    K, buses, edges = incidence(network, frame)
    b = frame["susceptance"].to_numpy(dtype=float)
    return (K * b) @ K.T, buses, edges


def pseudoinverse(L: np.ndarray) -> np.ndarray:
    """``L+``, the Moore-Penrose pseudoinverse.

    For a connected network the nullspace is exactly the constant vector, and
    ``L+`` is the inverse on the orthogonal complement of it.  For a network
    in several pieces the nullspace has one dimension per piece and the
    pseudoinverse handles that too, which is why nothing here needs a slack
    bus.
    """
    return np.linalg.pinv(L, hermitian=True)


# --------------------------------------------------------------------------- #
# PTDF
# --------------------------------------------------------------------------- #

def ptdf(network, branch_frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """Power transfer distribution factors, branches by buses.

    ``PTDF[e, i]`` is the MW that appears on branch ``e`` when 1 MW is
    injected at bus ``i`` and taken out **spread evenly over every bus**,
    which is what the pseudoinverse's own reference gives.  Pick a different
    reference with :func:`shift_factors`; the difference between two columns
    is independent of it, which is the useful property.
    """
    frame = branch_frame if branch_frame is not None else branches(network)
    K, buses, edges = incidence(network, frame)
    b = frame["susceptance"].to_numpy(dtype=float)
    L = (K * b) @ K.T
    return pd.DataFrame((b[:, None] * K.T) @ pseudoinverse(L),
                        index=edges, columns=buses)


def injections(network, snapshot) -> pd.Series:
    """Net MW injected at every bus at one snapshot, after a solve.

    Generators and storage add, loads subtract, and a link adds at its
    ``bus1`` what it takes from its ``bus0``.
    """
    p = pd.Series(0.0, index=network.buses.index)
    if len(network.generators_t.p.columns):
        gen = network.generators_t.p.loc[snapshot]
        sign = network.generators["sign"].reindex(gen.index).fillna(1.0)
        for name, value in (gen * sign).items():
            p[network.generators.at[name, "bus"]] += value
    if len(network.storage_units_t.p.columns):
        for name, value in network.storage_units_t.p.loc[snapshot].items():
            p[network.storage_units.at[name, "bus"]] += value
    if len(network.loads_t.p_set.columns):
        for name, value in network.loads_t.p_set.loc[snapshot].items():
            p[network.loads.at[name, "bus"]] -= value
    if len(network.links) and len(network.links_t.p0.columns):
        p0 = network.links_t.p0.loc[snapshot]
        for name, value in p0.items():
            p[network.links.at[name, "bus0"]] -= value
            p[network.links.at[name, "bus1"]] += (
                value * network.links.at[name, "efficiency"])
    return p


def angles(network, snapshot, branch_frame: pd.DataFrame | None = None
           ) -> tuple[np.ndarray, np.ndarray]:
    """Bus voltage angles and the *effective* angle difference per branch.

    A phase-shifting transformer imposes an angle of its own, so the DC flow
    on a branch is not ``b * (theta_i - theta_j)`` but

        F_e = b_e * (theta_i - theta_j - phi_e)

    and the bus equation gains a term to match::

        L theta = p + K B phi

    which is to say a phase shifter behaves exactly like a pair of equal and
    opposite injections at its two ends.  Returns ``(theta, a)`` where ``a``
    is the effective difference ``K^T theta - phi``; with no shifters in the
    network ``phi`` is zero and ``a`` is the plain angle difference.

    This matters here.  Ignore the two shifters in the all-island network and
    the reconstructed flows are out by up to 79 MW on the circuits around
    them, which is more than half the rating of some of them.
    """
    frame = branch_frame if branch_frame is not None else branches(network)
    K, buses, _ = incidence(network, frame)
    b = frame["susceptance"].to_numpy(dtype=float)
    phi = frame["phase_shift"].to_numpy(dtype=float)
    L = (K * b) @ K.T
    p = injections(network, snapshot).reindex(buses).fillna(0.0).to_numpy()
    theta = pseudoinverse(L) @ (p + K @ (b * phi))
    return theta, K.T @ theta - phi


def flows(network, snapshot, branch_frame: pd.DataFrame | None = None
          ) -> pd.Series:
    """Branch flows from the Laplacian and the injections, in MW.

    Should agree with ``n.lines_t.p0`` to numerical precision.  Where it does
    not, the injections are not balanced - which is worth knowing.

    This is ``PTDF @ p`` plus the phase-shifter term; with no shifters the two
    are the same thing, and :func:`ptdf` alone is enough.
    """
    frame = branch_frame if branch_frame is not None else branches(network)
    _, effective = angles(network, snapshot, frame)
    return pd.Series(frame["susceptance"].to_numpy(dtype=float) * effective,
                     index=frame.index)


# --------------------------------------------------------------------------- #
# Braess: how flow on one branch responds to another's susceptance
# --------------------------------------------------------------------------- #

def susceptibility(network, snapshot, branch_frame: pd.DataFrame | None = None
                   ) -> pd.DataFrame:
    """``dF_e / dB_e'`` - the edge-to-edge flow susceptibility matrix.

    Differentiating ``F = B K^T L+ p`` with respect to one branch's
    susceptance, using ``dL/dB_e' = k_e' k_e'^T`` and
    ``dL+/dB_e' = -L+ k_e' k_e'^T L+`` on the range space, gives

        dF_e/dB_e'  =  delta(e, e') * a_e
                       -  B_e * (k_e^T L+ k_e') * a_e'

    where ``a_e`` is the effective angle difference across branch ``e`` -
    ``theta_i - theta_j`` less any phase shift, which is ``F_e / B_e``.  The
    second term is the interesting one and it is where **Braess's paradox**
    lives: strengthening branch ``e'`` - raising its susceptance, which is
    what a second circuit on the same route does - can *increase* the flow on
    an already-loaded branch ``e``.  A positive entry off the diagonal, for an
    ``e`` you are trying to unload, means reinforcing ``e'`` makes your
    problem worse.

    Rows are ``e`` (the branch whose flow changes), columns are ``e'`` (the
    branch whose susceptance is changed).  Units are MW per (MW/radian).
    """
    frame = branch_frame if branch_frame is not None else branches(network)
    K, buses, edges = incidence(network, frame)
    b = frame["susceptance"].to_numpy(dtype=float)
    L = (K * b) @ K.T
    Lp = pseudoinverse(L)

    # The *effective* angle difference, which carries any phase shift with it.
    # Differentiating through the shifter term leaves the formula unchanged
    # with ``a`` in place of ``dtheta``, because ``a_e`` is just ``F_e / b_e``.
    _, a = angles(network, snapshot, frame)

    # k_e^T L+ k_e' for every pair, all at once.
    resistance = K.T @ Lp @ K                  # branches by branches
    matrix = -np.outer(b, a) * resistance
    matrix[np.diag_indices_from(matrix)] += a
    return pd.DataFrame(matrix, index=edges, columns=edges)


def braess_candidates(network, snapshot, monitored: str,
                      branch_frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """Branches whose reinforcement would load ``monitored`` more, not less.

    The row of the susceptibility matrix for the branch you care about,
    signed so that a **positive** number means "strengthening this makes the
    monitored branch carry more".
    """
    frame = branch_frame if branch_frame is not None else branches(network)
    matrix = susceptibility(network, snapshot, frame)
    if monitored not in matrix.index:
        raise KeyError(f"no branch named {monitored!r}")
    row = matrix.loc[monitored]
    out = pd.DataFrame({
        "d_flow_per_d_susceptance": row,
        "susceptance": frame["susceptance"],
        "s_nom": frame["s_nom"],
        "kind": frame["kind"],
    })
    out["effect_on_monitored"] = np.where(
        out["d_flow_per_d_susceptance"] > 0, "increases", "decreases")
    return out.reindex(row.abs().sort_values(ascending=False).index)


# --------------------------------------------------------------------------- #
# Shift factors
# --------------------------------------------------------------------------- #

def shift_factors(network, monitored: str, reference: str = "load",
                  branch_frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """Each generator's shift factor on one monitored circuit.

    The shift factor is the MW that appears on the monitored circuit per MW
    of output at a generator, with the megawatt balanced somewhere - and
    *where* is the whole of the definition:

    ``reference="load"``
        balanced across every load in proportion to its size.  This is the
        distributed slack a system operator normally uses, and what a
        constraint-group calculation means by a shift factor.
    ``reference="uniform"``
        balanced evenly across all buses - the pseudoinverse's own reference.
    any bus name
        balanced entirely at that bus, the textbook single-slack convention.

    Ranking generators by ``abs(shift_factor)`` on a monitored circuit is how
    a constraint group is drawn: the machines with a high factor are the ones
    whose output the circuit actually sees, and they are the ones a dispatch
    tool has to act on.
    """
    frame = branch_frame if branch_frame is not None else branches(network)
    matrix = ptdf(network, frame)
    if monitored not in matrix.index:
        raise KeyError(f"no branch named {monitored!r}")
    row = matrix.loc[monitored]

    if reference == "uniform":
        base = 0.0
    elif reference == "load":
        weights = pd.Series(0.0, index=matrix.columns)
        if len(network.loads_t.p_set.columns):
            demand = network.loads_t.p_set.mean()
        else:
            demand = network.loads["p_set"]
        for name, value in demand.items():
            weights[network.loads.at[name, "bus"]] += float(value)
        total = weights.sum()
        if total <= 0:
            raise ValueError("no load to distribute the reference over")
        base = float((row * (weights / total)).sum())
    elif reference in matrix.columns:
        base = float(row[reference])
    else:
        raise ValueError(
            f"reference must be 'load', 'uniform' or a bus name, not "
            f"{reference!r}")

    generators = network.generators
    factors = pd.DataFrame({
        "bus": generators["bus"],
        "carrier": generators["carrier"],
        "p_nom": generators["p_nom"],
        "shift_factor": [row.get(b, np.nan) - base for b in generators["bus"]],
    })
    factors["mw_on_monitored_at_full_output"] = (
        factors["shift_factor"] * factors["p_nom"])
    return factors.reindex(
        factors["shift_factor"].abs().sort_values(ascending=False).index)
