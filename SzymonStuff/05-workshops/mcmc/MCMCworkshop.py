"""
Metropolis algorithm for the q-state Potts model on a d-dimensional
square lattice (d=2 implemented, per the exercise's "assume d=2 if needs
be"). Collects (E, M) after every sweep and writes them to a .csv file.
"""

import csv

import numpy as np

# ----------------------------------------------------------------------
# System parameters {d, q, beta, J, Li, N}
# ----------------------------------------------------------------------
d = 2               # spatial dimension
q = 3               # number of Potts states {1, ..., q}, q <= 4
J = 1.0             # coupling constant, J > 0
Li = (10, 10)       # lattice shape (L1, L2), L ~ O(10)
N = 2000            # number of sweeps
seed = 0            # RNG seed, for reproducibility

# 2D q-state Potts critical point (ferromagnetic, square lattice): beta_c = (1/J)(1 + sqrt(q))
beta_c = (1 / J) * (1 + np.sqrt(q))
beta = 1.5 * beta_c  # inverse temperature, beta = 1/(k_B T); chosen comfortably above beta_c

rng = np.random.default_rng(seed)


# ----------------------------------------------------------------------
# Initialisation
# ----------------------------------------------------------------------
def init_spins(Li, q, rng):
    """'Hot' start: every site gets an independent uniform state in {1,...,q}."""
    return rng.integers(1, q + 1, size=Li)


# ----------------------------------------------------------------------
# Observables
# ----------------------------------------------------------------------
def potts_hamiltonian(spins, J):
    """
    Full 2D square-lattice Potts Hamiltonian with periodic boundaries:
        H = -J * sum_<i,j> delta(s_i, s_j)
    O(L1*L2); called once per sweep for logging, not inside the update loop.
    """
    right = np.roll(spins, -1, axis=1)
    down = np.roll(spins, -1, axis=0)
    same_right = spins == right
    same_down = spins == down
    return -J * (same_right.sum() + same_down.sum())


def potts_magnetisation(spins, q):
    """
    Potts order parameter M = (q * n_max - n_sites) / (n_sites * (q - 1)) in [0, 1],
    where n_max is the size of the largest same-state population.
    M = 0 for a fully disordered configuration, M = 1 if every site agrees.
    """
    counts = np.array([(spins == s).sum() for s in range(1, q + 1)])
    n_max = counts.max()
    n_sites = spins.size
    return (q * n_max - n_sites) / (n_sites * (q - 1))


# ----------------------------------------------------------------------
# Metropolis single-site update
# ----------------------------------------------------------------------
def propose_new_state(current_state, q, rng):
    """Draw s' uniformly from {1,...,q} \\ {current_state} (slide step 2)."""
    offset = rng.integers(1, q)  # 1 .. q-1, so new_state is guaranteed != current_state
    return ((current_state - 1 + offset) % q) + 1


def local_same_count(spins, i, j, state, L1, L2):
    """How many of site (i,j)'s 4 nearest neighbours (periodic BC) equal `state`."""
    up = spins[(i - 1) % L1, j]
    down = spins[(i + 1) % L1, j]
    left = spins[i, (j - 1) % L2]
    right = spins[i, (j + 1) % L2]
    # cast to int: summing numpy bools stays boolean and can't later be subtracted
    return int(up == state) + int(down == state) + int(left == state) + int(right == state)


def metropolis_step(spins, i, j, q, J, beta, L1, L2, rng):
    """
    Slide steps 1-3 for a single site (i,j): propose s' != s, compute
    delta = H_new - H_old from the 4 local bonds only (equivalent to but far
    cheaper than recomputing the whole-lattice H), and accept/reject.
    Mutates `spins` in place.
    """
    old_state = spins[i, j]
    new_state = propose_new_state(old_state, q, rng)

    old_same = local_same_count(spins, i, j, old_state, L1, L2)
    new_same = local_same_count(spins, i, j, new_state, L1, L2)
    delta = -J * (new_same - old_same)

    if delta <= 0:
        spins[i, j] = new_state           # energy decreases or is unchanged -> always accept
    else:
        p = rng.random()
        if p <= np.exp(-beta * delta):
            spins[i, j] = new_state       # uphill move, accept with Boltzmann probability
        # else: reject, spins[i, j] stays as old_state


def sweep(spins, q, J, beta, L1, L2, rng, sequential=False):
    """
    One sweep = one attempted update at every one of the L1*L2 sites.
    sequential=True walks the lattice row-by-row; sequential=False (default)
    picks L1*L2 uniformly random sites instead. The slides allow either.
    """
    if sequential:
        for i in range(L1):
            for j in range(L2):
                metropolis_step(spins, i, j, q, J, beta, L1, L2, rng)
    else:
        for _ in range(L1 * L2):
            i = rng.integers(L1)
            j = rng.integers(L2)
            metropolis_step(spins, i, j, q, J, beta, L1, L2, rng)


# ----------------------------------------------------------------------
# Main driver: run N sweeps, collect (E, M), write to csv
# ----------------------------------------------------------------------
def run_metropolis(d, q, beta, J, Li, N, rng, sequential=False, out_csv="potts_metropolis.csv"):
    if d != 2:
        raise NotImplementedError("only d=2 is implemented (exercise allows assuming d=2)")

    L1, L2 = Li
    spins = init_spins(Li, q, rng)

    results = np.empty((N, 2))
    for sweep_idx in range(N):
        sweep(spins, q, J, beta, L1, L2, rng, sequential=sequential)
        results[sweep_idx, 0] = potts_hamiltonian(spins, J)
        results[sweep_idx, 1] = potts_magnetisation(spins, q)

    with open(out_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sweep", "E", "M"])
        for sweep_idx, (E, M) in enumerate(results, start=1):
            writer.writerow([sweep_idx, E, M])

    return spins, results


if __name__ == "__main__":
    final_spins, data = run_metropolis(d, q, beta, J, Li, N, rng)
    print(f"Done: {N} sweeps on a {Li} lattice, q={q}, J={J}")
    print(f"beta_c = {beta_c:.3f}, beta = {beta:.3f} (beta/beta_c = {beta / beta_c:.2f})")
    print(f"Final E = {data[-1, 0]:.3f}, final M = {data[-1, 1]:.3f}")
    print("Data written to potts_metropolis.csv")
