# TODO — TPSA Hackathon 2026

**Status as of 5 September 2026.** Environment, data and the meteorology layer
are done. What remains is the physics.

---

## 0. Not doing

- **Outreach / emails — dropped 5 Sep 2026.** No part of this project waits on
  a reply. ENTSO-E data would only cross-check figures we already have from
  EirGrid directly, so its multi-day token turnaround is not worth the block.

---

## Open decisions

Choices that need a person, not a tool. Each changes what gets built.
**Three still open; D3 is settled.**

| # | Decision | Why it matters | Status |
|---|---|---|---|
| D1 | **Overlapping or disjoint clustering?** | Confirmed in the data: farms carry up to 4 group tags. Spectral clustering and k-means give disjoint partitions, so the standard tool **cannot produce the shape of the answer**. Options: fuzzy c-means, NMF, or thresholding the effectiveness vector per constraint (closest to EirGrid's own description) | **Open** |
| D2 | **Which scoring metric?** | ARI and NMI assume disjoint sets. Without settling this, "we recovered 70% of the groups" has no meaning. Candidates: omega index, overlapping NMI, or per-group precision/recall on station sets | **Open** |
| D3 | **Validate-and-extend Nayer's mapping, or reconstruct independently?** | Changes Monday's first task | **Decided 5 Sep: validate and extend.** It has a scoreable answer, and the mapping's holes are the contribution |
| D4 | **Does MCMC earn its place?** | Spectral + k-means is deterministic and fast for clustering effectiveness vectors. MCMC only pays if you write a partition objective with constraints that have no closed form. Friday's workshop is a reason to consider it, not to use it | **Open** |

---

## 1. The farm-to-group mapping already exists

The `generator` sheet of `../03-network/ireland_case_july2025.xlsx` has a
**`prorata_groups`** column populated for **all 294 generators**, using EirGrid's
own group naming:

```
Sliabh Bawn Windfarm      ->  ROI-NW/4, ROI-W/1, ROI-W/2, ROI/1
Molly Mountain Wind Farm  ->  NI/2, NI/3, NI/4
```

Both briefs call this mapping a "confirmed public gap." It is not published by
EirGrid — but Nayer reconstructed it, and it is CC BY 4.0.

**What it changes.** You are no longer inventing a farm-to-group table with no
way to check it. You now have a labelled ground truth to validate a computed
effectiveness clustering against. That is a stronger project, not a weaker one.

**Its holes — these are your contribution:**
- 25 group tokens vs the PDF's 39 groups
- **no South-East region at all** (the PDF has 4 SE groups)
- a bus name (`DFR_I_Z_110`) sitting in the group column
- a duplicated entry (`ROI-W/2,ROI-W/2` on Athea)
- `MUON_group` is populated for 38 synchronous units with named constraints
  (`S_NBMIN_ROImin`, `S_NBMIN_Dub_NB`, `S_MWMAX_CRK_MW`) — the MUON structure,
  machine-readable, which nothing in the briefs anticipated

- [ ] Decide: validate-and-extend Nayer's mapping, or reconstruct independently
      and compare? (Recommend the first — it has a scoreable answer.)

---

## 2. Physics / method — the real work, none done

- [ ] **PTDF (line-flow sensitivity).** This *is* Stage 1 and it is defined
      nowhere in the six briefing files. The workshop taught the unweighted
      Laplacian `L = D - A`; DC power flow needs the susceptance-weighted
      `B = A^T diag(1/x) A`, and the sensitivity is a specific matrix product
      with a pseudo-inverse and a slack bus. **Write this bridge down first.**
      Everything else is downstream. Check it against the 4-node Braess network
      in Session 1 section 8, where you can verify by hand.
- [ ] **N-1 / LODF.** Not optional: EirGrid defines effectiveness against
      "base case, **N-1 or N-1-1** overload", so N-1 is inside the definition of
      the thing you are reconstructing. Also the stated reason Nayer's model
      underestimates constraint — so it is your differentiator too.
- [ ] **Finish the workshop capstone.** Session 2 cell 29 has step 1 only
      (`t = 0.2 #lambda2 = 5 vibes based`); steps 2-4 and the conclusion are
      blank. It is your only validation method. Finish it on the Dublin toy
      data — the structure transfers directly.
- [ ] **DC-OPF, cost function, MWh -> EUR.** Stage 3. Zero progress.
      PyPSA + HiGHS are installed and verified, so the solver is ready.

---

## 3. Graph partitioning — see D1 and D2 above

- [ ] **EirGrid's groups OVERLAP and are non-exhaustive; spectral clustering and
      k-means produce disjoint, exhaustive partitions.** Your standard tool
      cannot produce the shape of the answer. Options: fuzzy c-means, NMF, or —
      probably best, and closest to EirGrid's own description — simply threshold
      the effectiveness vector per constraint. **Resolve this before writing
      clustering code.** Confirmed by the data: farms carry up to 4 group tags.
- [ ] **Pick a scoring metric.** ARI and NMI assume disjoint partitions and will
      not work. Use the omega index / overlapping-NMI, or per-group
      precision-recall on station sets. You cannot say "we recovered 70% of the
      groups" until you decide what that sentence means.
- [ ] Choose algorithm, feature vector, distance metric, cluster count — four
      undecided choices currently hiding in the word "cluster them".
- [ ] Consider a spatial-contiguity constraint: EirGrid's groups are regional,
      so an unconstrained clustering will scatter geographically and score badly
      for a reason that is not your fault.

---

## 4. MCMC — machinery exists, application does not

- [ ] **Write the mapping.** What is a spin? What is the graph? What is the
      Hamiltonian? Nowhere stated. COTHROM is cited as inspiration but not one
      line of the analogy exists.
- [ ] **Fix the bug in [../05-workshops/mcmc/MCMCworkshop.py](../05-workshops/mcmc/MCMCworkshop.py).**
      `beta_c = (1/J)*(1 + sqrt(q))` is missing a logarithm; the 2D Potts
      critical point is `beta_c = ln(1 + sqrt(q))/J`. You ran at beta = 4.098
      when beta_c = 1.005, i.e. **4.1x above critical**. Verified in the output:
      the last 500 sweeps sit at `E = -200.00` exactly and `M = 1.000` — the
      frozen ground state, zero fluctuations. 2,000 sweeps of a dead system.
- [ ] Add a cluster algorithm (Swendsen-Wang or Wolff) and replica exchange —
      Friday's workshop content, and what COTHROM actually used. You currently
      have only the slowest algorithm.
- [ ] **Decide whether MCMC earns its place.** If you are clustering
      effectiveness vectors, spectral + k-means is deterministic and fast and
      MCMC adds nothing. MCMC only pays off if you write a partition objective
      with awkward constraints (contiguity, group size, overlapping membership)
      where no closed form exists. Decide deliberately; do not drift into it
      because there is a workshop on Friday.

---

## 5. Honesty items for the Friday slides

- [x] **Braess — settled 5 Sep 2026.** The DOI resolves via CrossRef to
      Witthaut & Timme, *New J. Phys.* **14** (2012) 083036. Safe to cite. Still
      true, and worth saying out loud: **no source applies Braess's paradox to
      the Irish grid**, so demonstrating it here would be original work.
- [ ] **Per-farm dispatch-down data is not public.** Validation is station-level
      only, and any euro figure is a modelled estimate, not a measurement. Say
      this before a judge says it for you.
- [ ] **State your scope on slide 1.** 11.3% (RoI 2025) vs 14.0% (all-island
      2024) vs 29.6% (NI 2024) differ by a factor of ~2.6.
- [ ] **The ERA5 and power-curve caveats** (see `../04-meteorology/wind_power.py` docstring):
      reanalysis is not forecasting, the grid is ~28 km, the power curve is
      generic not per-turbine.
