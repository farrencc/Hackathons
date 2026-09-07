# 03 — The Network

The grid as a graph, and the constraint groups EirGrid uses to manage it.
**This is the core modelling asset of the project.**

**Layout.** `data/` network model + EirGrid PDFs · `scripts/` parsing and joining · `script-output/` tables

---

## What a constraint group is

EirGrid's own words, from the Wind Dispatch Tool document:

> "Wind/solar farms are grouped together depending on their **effectiveness** to
> alleviate constraints. The effectiveness is a measure of the change in
> wind/solar farm output relative to the change in the level of the 'base case',
> 'N-1' or 'N-1-1' overload. The effectiveness of each wind/solar farm is a
> **function of the topology of the transmission network**."

Three consequences:

1. This is **not** graph clustering. No EirGrid document describes spectral
   clustering or community detection. Do not claim you discovered their algorithm.
2. "Effectiveness as a function of network topology" is a **sensitivity
   calculation on the network graph** — something computable directly from the
   bus/branch data in this folder.
3. **N-1 is inside the definition.** Effectiveness is measured against
   post-contingency overloads, so contingency analysis is not optional garnish.

A farm can belong to **several overlapping groups at once** and takes the
tightest binding setpoint. Reductions are shared pro-rata within a group.

---

## Files, most important first

### 1. [data/ireland_case_july2025.xlsx](data/ireland_case_july2025.xlsx) — the network model
An all-island bus/branch/generator model, openly licensed. 13 sheets, 20 MB.

| Sheet | Rows | Contents |
|---|---|---|
| `bus` | 446 | name, description, baseKV, zone (ROI/NI) |
| `branch` | 592 | from/to bus, r, x, b, short-term and continuous ratings |
| `transformer` | 184 | from/to bus, type, r, x, b, ratings |
| `generator` | 294 | bus, name, fuel, limits, costs, **group memberships** |
| `demand` | 164 | bus, real power, value of lost load |
| `ts_*` (7 sheets) | 1,488 each | half-hourly time series for July 2025 |

**The `generator` sheet is the find.** It carries a **`prorata_groups`** column,
populated for all 294 generators, mapping named farms to constraint groups in
EirGrid's own naming scheme, with overlapping membership explicit:

```
Sliabh Bawn Windfarm      ->  ROI-NW/4, ROI-W/1, ROI-W/2, ROI/1
Molly Mountain Wind Farm  ->  NI/2, NI/3, NI/4
```

Both briefing documents call this mapping a confirmed public gap. It is
unpublished *by EirGrid* — but this model reconstructs it. It also carries a
**`MUON_group`** column for the 38 synchronous units, with named constraints
(`S_NBMIN_ROImin`, `S_NBMIN_Dub_NB`, `S_MWMAX_CRK_MW`).

**Caveats the authors state themselves:**
- It is explicitly **a draft**, needing "operational date validation, transformer
  classification improvements, and connection point rationalization."
- **N-1 security is not modelled**, so it *underestimates* constraint — and
  constraint is now the larger half of the problem.
- It is **Pyomo-based, not PyPSA**. Treat it as a *data* asset and convert the
  tables into a PyPSA network rather than adopting the solver stack.

**Caveat we found:** the row counts differ slightly from the paper, which reports
586 lines / 183 transformers / 288 generators against the 592 / 184 / 294 in the
file. Bus count matches at 446. Minor, but check which you are quoting.

### 2. [script-output/constraint-groups-to-stations.csv](script-output/constraint-groups-to-stations.csv) — the official groups, machine-readable
Generated from the EirGrid PDF by [scripts/parse_wdt.py](scripts/parse_wdt.py). **514 rows**
covering **41 group sections** and **99 distinct transmission stations**.

| Column | Meaning |
|---|---|
| `group_id` | e.g. `ROI-SW/3a`, `NI/4` — matches the model's naming |
| `region` | `NI`, `ROI-NW`, `ROI-W`, `ROI-SW`, `ROI-SE`, `ROI-NE`, `ROI-ALL` |
| `group_name` | Full title from the PDF |
| `context` | `intact` (normal network), `outage` (temporary modification), `all-generation` |
| `station` | Transmission station name; blank for all-generation groups |
| `pdf_page` | Page it came from, for checking by hand |

**Reading the count.** 41 sections, but **39 numbered groups** — South West
group 3 splits into `3a`, `3b`, `3c`. Region totals match the published
structure exactly: NI 5, NW 7, West 9, SW 11, SE 4, NE 2, nationwide 1.
Two groups (`NI/4` "All NI" and `ROI-ALL/1` "All IE") have no station list
because they cover all generation; they are marked `all-generation`.

**Validation.** 88% of parsed stations (87 of 99) match a bus description in the
network model or a node name in the SEAI farm list. The 12 that don't are
genuine station names absent from those references — mostly Northern Irish
(Coolkeeragh, Rasharkin, Tremoge, Magherakeel) plus real ROI sites (Mount Lucas,
Gort, Slieve Callan). **No parse noise remains.**

**Known limit:** the PDF publishes membership at **station level only**, never as
named wind farms. That is why the model's `prorata_groups` column matters.

### 3. [data/WDT-Constraint-Group-Overview.pdf](data/WDT-Constraint-Group-Overview.pdf) — the source document
74 pages, 1 February 2024. The authoritative description of the grouping method.
Group definitions run to page 65; Appendix 1 explains the setpoint calculation.

### 4. [data/nayer-2026-arxiv-2608.24464.pdf](data/nayer-2026-arxiv-2608.24464.pdf) — the paper
A full MILP formulation of Irish curtailment and constraint, built on OATS.
Read **§V-B** for the data pipeline and **Appendix A** for EirGrid's named
security constraints with MW limits — the MUON structure written out explicitly.

### 5. [script-output/farm-to-constraint-group-map.csv](script-output/farm-to-constraint-group-map.csv) — the integration table
Built by [scripts/build_join.py](scripts/build_join.py). This is the file that connects the
project's four separate tables:

```
SEAI farms --node--> WDT stations --> constraint groups
     |                                       |
     +---- name ----> model generators --prorata_groups--+
```

**Two independent routes reach a farm's groups, so each checks the other.**
Of 112 farms where both routes exist, **82 (82%) share at least one group.**

Matching farm names is the hard part, and it is done with two signals rather
than one. A name score alone is not safe: "Cappawhite A" scores 71 against
"Cappawhite B" and they are *different farms*, while "Gortahile Wind Farm"
scores 82 against "gortahile ltd" and they are the *same one*. So a weaker name
match is accepted only when the farm's SEAI connection node agrees with the
station of the model generator's bus.

| Result | Value |
|---|---|
| Farms matched to a model generator | 129 of 313 (41% by count) |
| **Capacity covered** | **3,201 of 4,304 MW (74%)** |
| Of which location corroborates | 107 |

Judge it by capacity, not count: 125 of the unmatched farms are under 5 MW and
total only 320 MW — small distribution-connected sites a *transmission* model
does not represent individually. The model also holds 48 Northern Irish
generators that the SEAI list, being Republic-only, can never match.

Every row carries `match_score`, `station_agrees` and `routes_overlap`, so any
match can be audited by hand. Nothing is silently merged.

### 6. [script-output/model-generators-july2025.csv](script-output/model-generators-july2025.csv) — simulation inputs
Built by [scripts/explore_timeseries.py](scripts/explore_timeseries.py), which assesses the
model's seven `ts_*` sheets. What it found:

| Sheet | Varies over July? |
|---|---|
| `ts_PD` (demand) | 162 of 164 columns vary |
| `ts_PGUB` (generator upper bound) | 211 of 288 vary — the wind and solar profiles |
| `ts_PGLB` (lower bound) | only 3 vary — the must-run units |
| **`ts_Lmax` (line ratings)** | **0 of 586 vary** |
| `ts_TLmax` (transformer ratings) | 0 of 180 vary |
| `ts_bid` | 0 of 288 vary |

**Line ratings are constant.** The model uses static thermal ratings with no
seasonal or dynamic variation — which is precisely the assumption that dynamic
line rating (already trialled in Ireland, targeting ~30% more capacity on
existing circuits) is designed to relax. That is a ready-made angle.

The model's July 2025 wind fleet: **190 units, 4,753 MW peak, capacity factor
0.250**. Our independent ERA5-plus-power-curve estimate for the same month gave
**0.219** — two entirely separate derivations agreeing within three points,
which is a good check on both.

### 7. The PyPSA pipeline — where the physics happens

| Script | What it does |
|---|---|
| [scripts/build_pypsa_network.py](scripts/build_pypsa_network.py) | Loads the workbook into PyPSA -> `script-output/ireland-network.nc` |
| [scripts/verify_ptdf.py](scripts/verify_ptdf.py) | Checks PTDF against a network solvable by hand. **8/8 pass** |
| [scripts/compute_effectiveness.py](scripts/compute_effectiveness.py) | Effectiveness of every farm against every branch |
| [scripts/verify_bodf.py](scripts/verify_bodf.py) | Checks N-1 outage factors by hand, including the radial case. **5/5 pass** |
| [scripts/compute_n1_effectiveness.py](scripts/compute_n1_effectiveness.py) | Effectiveness under the worst single outage, plus the critical-outage ranking |

**N-1 in one line.** `BODF[l, k]` is the fraction of line k's flow that lands on
line l when k trips, so post-contingency sensitivity is
`PTDF[l,f] + BODF[l,k] * PTDF[k,f]`. Of 770 branches, **714 are usable
contingencies**; the other 56 are radial, and outaging them splits the network so
BODF is undefined - they are detected and excluded rather than allowed to produce
plausible-looking nonsense.

Under N-1 the number of meaningful farm-line couplings rises from **7,041 to
24,887 (+253%)**: most farms that matter for a line only matter after something
else has tripped. `script-output/critical-contingencies.csv` ranks single outages
by the distinct wind capacity they put at risk.

**Three conversions the loader gets right, and which would fail silently otherwise:**

1. **Per-unit to physical.** The workbook stores `r`, `x`, `b` per-unit on a
   100 MVA base. PyPSA wants line reactance in *ohms* (`x_pu * V^2/100`) but
   transformer reactance per-unit on the *transformer's own* rating
   (`x_pu * s_nom/100`). Confuse the two and you get a plausible-looking network
   with the wrong flows.
2. **Status flags differ by sheet.** Branches use `stat = 1` for in-service,
   transformers use `2`, and `0` always means out. 588 lines, 183 transformers
   and 288 generators survive.
3. **Connectivity.** The 446 buses form **two** sub-networks: the main 444-bus
   grid, and a dead 2-bus Northern Irish stub (`CRR_N_Z_110` / `CRR_N_Z_33`)
   joined by a transformer with no generation and no load. PTDF is only defined
   within a connected sub-network, so the stub is excluded.

**The slack-bus trap, and the fix.** PyPSA's raw PTDF assumes balancing power is
withdrawn at a single slack bus, here `CPS_N_Z_110` in Northern Ireland. That
makes every line near the slack look exposed to every farm in Ireland, which is
a property of the reference, not of the grid. So the output carries two columns:

| Column | Meaning |
|---|---|
| `effectiveness` | raw, slack-referenced |
| `effectiveness_vs_fleet` | minus the capacity-weighted fleet average: a distributed slack matching how EirGrid share a pro-rata reduction. **Use this one** |

With the fix, the most wind-exposed lines come out in **Galway and the West**,
which is where EirGrid actually have nine constraint groups. Before the fix they
came out in Northern Ireland, beside the slack.

Sanity check that the physics is right: farms on radial connections show
effectiveness near +/-0.99, because one line carries all their output.

### 8. [scripts/parse_wdt.py](scripts/parse_wdt.py) — the parser
Rebuilds the CSV from the PDF. Runs from any directory.

```bash
python 03-network/scripts/parse_wdt.py
```

Two non-obvious things it handles: station tables are **two-column**, so
`Brockaghboy Lisaghmore` is two stations while `Sorne Hill` is one — it splits on
word x-coordinates (measured gaps: 166–187 pt between columns, 3.1 pt within a
name). And South West groups are labelled `3a/3b/3c`, so the **subsection number
is not the group number** — it reads the label from the heading text.

---

## References

| File | Source | Licence | Retrieved |
|---|---|---|---|
| `data/ireland_case_july2025.xlsx` | Nayer, R. (2025). *Ireland Electricity System Model* (0.1) [Data set]. Zenodo. DOI [10.5281/zenodo.17287498](https://doi.org/10.5281/zenodo.17287498) | **CC BY 4.0** | 5 Sep 2026 |
| `data/nayer-2026-arxiv-2608.24464.pdf` | R. Nayer, S. Hodges, W. Bukhsh (Strathclyde), C. Chitambo, C. Wijeratne (RES), "Modelling Renewable Curtailment and Constraints in Ireland's Electricity System," [arXiv:2608.24464](https://arxiv.org/abs/2608.24464), 25 Aug 2026 | arXiv preprint | 1 Sep 2026 |
| `data/WDT-Constraint-Group-Overview.pdf` | EirGrid/SONI, *Wind Dispatch Tool Constraint Group Overview*, 1 Feb 2024. <https://cms.eirgrid.ie/sites/default/files/publications/Wind-Dispatch-Tool-Constraint-Group-Overview_0.pdf> | Free to download | 5 Sep 2026 |
| `script-output/constraint-groups-to-stations.csv` | **Generated** by `scripts/parse_wdt.py` from the PDF above | Derived | 5 Sep 2026 |
| `scripts/parse_wdt.py`, `scripts/build_join.py`, `scripts/explore_timeseries.py`, `scripts/build_pypsa_network.py`, `scripts/verify_ptdf.py`, `scripts/compute_effectiveness.py` | Written for this project | — | 5 Sep 2026 |
| `script-output/ireland-network.nc`, `script-output/effectiveness-farm-by-line.csv`, `script-output/line-effectiveness-summary.csv` | **Generated** from the network model via PyPSA | Derived | 5 Sep 2026 |
| `script-output/effectiveness-n1-farm-by-line.csv`, `script-output/critical-contingencies.csv`, `script-output/effectiveness-n1-matrix.npy`, `script-output/effectiveness-n1-order.csv` | **Generated** under N-1 contingency conditions | Derived | 6 Sep 2026 |
| `script-output/farm-to-constraint-group-map.csv`, `script-output/model-generators-july2025.csv` | **Generated**, joining the model, the WDT CSV and the SEAI farm list | Derived | 5 Sep 2026 |

**Attribution required.** The network model and the accompanying code release are
CC BY 4.0 — free to use, including in the Friday presentation, provided they are
credited. Cite as:

> Nayer, R. (2025). *Ireland Electricity System Model* (0.1) [Data set]. Zenodo.
> https://doi.org/10.5281/zenodo.17287498

alongside the arXiv paper. The code release is separately deposited at
[10.5281/zenodo.17358993](https://doi.org/10.5281/zenodo.17358993), also CC BY 4.0,
mirrored at `github.com/richardnayer/oats_curtailment`. It builds on **OATS**
(Bukhsh, Edmunds & Bell, *IEEE Trans. Power Systems* 35(5):3552–3561, 2020),
which is GPL-3.
