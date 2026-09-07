# Handoff

**For an AI assistant picking this project up cold.** Everything done, everything
known, everything left. This is the only file written for a machine rather than a
person — every other document in this repository is written for a human reader
and should stay that way.

---

## 1. The task

TPSA Hackathon 2026, Trinity College Dublin, **7–11 September 2026**. Brief:
*develop models and optimise decision-making on Ireland's high-voltage network,
with the goal of reducing wind energy wasted each year.* Team of up to 5. Friday
presentation.

**The project.** Three stages, each standing alone:

1. Compute each wind farm's **effectiveness** — how much its output changes the
   flow on each transmission line. This is a PTDF.
2. **Cluster on it** and compare against EirGrid's real constraint groups.
3. Ask whether EirGrid's fixed pro-rata grouping **wastes energy** versus a
   per-farm optimum. Answer in MWh and euro.

**Status: stage 1 done and validated. Stage 2 blocked on two decisions. Stage 3
not started.**

---

## 2. Environment

- Python **3.14**, global install (user chose global over venv)
- Installed and verified: `pypsa 1.3.0`, `highspy 1.15.1`, `openpyxl`, `pdfplumber`,
  `pypdf`, plus pre-existing numpy 2.4.4 / pandas 3.0.3 / scipy / geopandas /
  networkx / sklearn / pyproj 3.7.2 / esda / libpysal
- PyPSA + HiGHS smoke-tested on a 3-bus DC-OPF: line pinned at its limit, expensive
  generator forced on. Works.
- Windows. Bash tool available; **large heredocs get truncated or mangle escape
  sequences** — use the Write/Edit tools for anything substantial. This bit
  repeatedly during the session.

---

## 3. Repository layout

Consistent by design — every content folder has the same three subfolders.

```
0X-name/
   README.md          what this folder is
   data/              downloaded from others. Never edited
   scripts/           our code
   script-output/     generated. Safe to delete and rebuild
```

Exceptions: `07-figures/` uses `charts/`; `05-workshops/` splits into
`graph-theory/` and `mcmc/`; `01-brief/` and `06-reference/` are flat.

| Folder | Purpose |
|---|---|
| `01-brief/` | Brief, TODO, open decisions |
| `02-curtailment/` | EirGrid reports; extracted reason-code and 15-min series |
| `03-network/` | Network model, constraint groups, **PyPSA + PTDF** |
| `04-meteorology/` | Farm locations, ERA5 pipeline, forecast, validation |
| `05-workshops/` | Graph theory notebooks, MCMC slides and code |
| `06-reference/` | Source catalogue, data scope audit |
| `07-figures/` | 13 charts, one script |
| `08-analysis/` | Cross-folder analyses |

**Conventions.** Scripts resolve paths from `Path(__file__).resolve().parent.parent`,
so they run from any working directory. Filenames describe contents
(`dispatch-down-by-reason-monthly.csv`); period-specific files carry the period
(`wind-speed-100m-2025-01.npy`). Root has `README.md`, `Rundown.md` (the human
explainer) and this file.

**Verification state:** 20 scripts all run clean from scratch; 127+ relative
markdown links resolve; every non-README file is named in its folder's README.

---

## 4. Data held

All public, all openly licensed, nothing needed permission.

| File | Source | Licence |
|---|---|---|
| `03-network/data/ireland_case_july2025.xlsx` | Nayer (2025), Zenodo [10.5281/zenodo.17287498](https://doi.org/10.5281/zenodo.17287498) | CC BY 4.0 |
| `03-network/data/WDT-Constraint-Group-Overview.pdf` | EirGrid, 1 Feb 2024, 74pp | Free |
| `03-network/data/nayer-2026-arxiv-2608.24464.pdf` | arXiv:2608.24464 | Preprint |
| `02-curtailment/data/DD-Summary-Report-V21.xlsx` | EirGrid | Free |
| `02-curtailment/data/System-Data-Qtr-Hourly-2026-V7.xlsx` | EirGrid, Jan–Jul 2026 | Free |
| `02-curtailment/data/System-Data-Qtr-Hourly-2025-V12.xlsx` | EirGrid, **full year 2025** | Free |
| `02-curtailment/data/Annual-Curtailment-Report-2025.pdf` (+ 2023, 2024 in `archive/`) | EirGrid/SONI | Free |
| `04-meteorology/data/WindFarmsConnectedJune2022.csv` | SEAI | CC BY 4.0 |
| `04-meteorology/data/era5_wind_*.json` | Open-Meteo ERA5, cached | CC BY 4.0 |
| `04-meteorology/data/TSO-Contracted-Wind-Report-2025-11-28.pdf` | EirGrid | Free |

**EirGrid version numbers increment through the year** — `V2` for 2025 held only
Q1, `V12` is the full year. Always take the highest available.

### Data scope: complete

Three things are genuinely unpublished by anyone and cannot be obtained:

1. **Per-farm dispatch-down volumes** — EirGrid send these to individual
   operators only. Validation is therefore station-level; any per-farm euro
   figure is modelled, not measured.
2. **Which named constraint was binding at a given moment** — only retrospective
   category aggregates are published.
3. **Real turbine power curves per site** — not public. All wind-to-power here
   uses a generic IEC-style curve.

A softer fourth: no open day-ahead SNSP forecast (a wind forecast exists; turning
it into SNSP needs a demand forecast too).

**Deliberately not collected:** ENTSO-E (token takes days, duplicates EirGrid
data); the two EirGrid scraper repos (`Daniel-Parke/EirGrid_Data_Download`,
`dclabby/EirgridDashboardAnalysis`) — they fetch the same data we already hold
from source. Outreach/emails were dropped by the user on 5 Sep; nothing waits on
a reply.

---

## 5. What was built, in dependency order

| Script | Output | Note |
|---|---|---|
| `03-network/scripts/parse_wdt.py` | `constraint-groups-to-stations.csv` | 514 rows, 41 sections = **39 numbered groups** |
| `04-meteorology/scripts/farm_locations.py` | `wind-farms-with-coordinates.csv` | 313 farms, EPSG:29903 → WGS84 |
| `04-meteorology/scripts/wind_power.py` | `wind-speed-100m-YYYY-MM.npy` etc | Takes `start end` args |
| `03-network/scripts/build_join.py` | `farm-to-constraint-group-map.csv` | The four-table join |
| `03-network/scripts/explore_timeseries.py` | `model-generators-july2025.csv` | Assesses the `ts_*` sheets |
| `03-network/scripts/build_pypsa_network.py` | `ireland-network.nc` | **The loader** |
| `03-network/scripts/verify_ptdf.py` | — | **8/8 hand-checked** |
| `03-network/scripts/compute_effectiveness.py` | `effectiveness-farm-by-line.csv` | 11,920 pairs |
| `02-curtailment/scripts/extract_dd.py` | `dispatch-down-by-reason-monthly.csv` | 5,610 rows, 2016–2026 |
| `02-curtailment/scripts/extract_system.py` | `system-state-15min-2026.csv` | 20,348 rows |
| `04-meteorology/scripts/wind_correlation.py` | — | Takes a `_YYYY-MM` tag |
| `04-meteorology/scripts/wind_forecast.py` | `wind-forecast-7day.csv` | Real forecast, not reanalysis |
| `04-meteorology/scripts/validate_against_eirgrid.py` | `model-vs-eirgrid-hourly-2026.csv` | **r² = 0.968** |
| `08-analysis/scripts/audit_join.py` | `join-coverage-gaps.csv` | Zero contradictions |
| `08-analysis/scripts/wind_by_bus.py` | `wind-by-bus-*` | 58 buses |
| `08-analysis/scripts/groups_vs_weather.py` | `groups-vs-weather-test.csv` | 1/12 |
| `08-analysis/scripts/groups_vs_effectiveness.py` | `groups-vs-effectiveness-test.csv` | **11/12** |
| `08-analysis/scripts/curtailment_per_farm.py` | `curtailment-per-farm-2026.csv` | Deliberately shows its own limits |
| `08-analysis/scripts/contracted_pipeline.py` | `contracted-pipeline-vs-constraints.csv` | 24 farms |
| `07-figures/scripts/make_figures.py` | 13 PNGs | Validated palette |

---

## 6. Key technical details a successor will need

### The PyPSA loader — three conversions that fail silently

1. **Per-unit → physical.** Workbook stores `r`, `x`, `b` per-unit on 100 MVA.
   PyPSA wants **line** reactance in ohms (`x_pu · V²/100`) but **transformer**
   reactance per-unit on the transformer's own rating (`x_pu · s_nom/100`).
   Different conversions from the same column.
2. **`stat` differs by sheet.** In-service is `1` for branches, `2` for
   transformers; `0` always means out. Result: 588 lines, 183 transformers, 288
   generators from 592/184/294 rows.
3. **Two sub-networks.** 444-bus main grid plus a dead 2-bus NI stub
   (`CRR_N_Z_110` / `CRR_N_Z_33`) joined by a transformer with no generation or
   load. PTDF is only defined within a connected sub-network; the stub is excluded.

### The slack-bus trap

PyPSA's PTDF references a single slack bus — it picked `CPS_N_Z_110` in Northern
Ireland. Raw PTDF therefore makes every line near the slack appear exposed to
every farm in Ireland. **Artefact of the reference, not the grid.**

Fix implemented: a **capacity-weighted distributed slack**, subtracting the
fleet-weighted mean per line, matching how EirGrid share a pro-rata reduction.
Output carries both columns; **`effectiveness_vs_fleet` is the one to use.**

Evidence the fix is right: afterwards the most wind-exposed lines are in Galway
and the West, where EirGrid actually have nine constraint groups. Before, they
were in Northern Ireland beside the slack.

### PyPSA API notes (v1.3.0)

- `sub_network.calculate_PTDF()`, `.calculate_BODF()`, `.branches_i()` all work
- `sub_network.buses()` is deprecated → `sub_network.components.buses.static`
- `sub_network.branches()` deprecated but `branches_i()` returns the `(component,
  name)` MultiIndex in PTDF row order
- PTDF columns are **relative to the slack**, so the slack's own column is zero.
  For a transfer between two chosen buses, subtract one column from the other

### The join

Fuzzy name matching between SEAI farm names and model generator descriptions
needed **two signals**, not one: `"Cappawhite A"` scores 71 against
`"Cappawhite B"` and they are *different farms*, while `"Gortahile Wind Farm"`
scores 82 against `"gortahile ltd"` and they are the *same one*. A weaker name
match is accepted only when the SEAI connection node agrees with the model bus's
station.

Result: 129 farms, **74% of Irish wind capacity** (3,201 of 4,304 MW). Judge by
capacity — 125 unmatched farms are under 5 MW totalling 320 MW, and the model has
48 NI generators the RoI-only SEAI list can never match.

### Data quirks encountered

- **21 SEAI farm names contain embedded newlines** — normalise whitespace at
  ingest or any newline-delimited join corrupts silently
- WDT PDF station tables are **two-column**; `Brockaghboy Lisaghmore` is two
  stations, `Sorne Hill` is one. Split on word x-gaps (measured: 166–187 pt
  between columns vs 3.1 pt within a name), not whitespace
- WDT South West groups are numbered `1, 2, 3a, 3b, 3c, 4…11` — **the subsection
  number is not the group number**. Read the label from the heading text
- `NI/4` ("All NI") and `ROI-ALL/1` ("All IE") have **no station list** because
  they cover all generation
- Model row counts differ from the paper: 592/184/294 in the file vs 586/183/288
  reported. Buses match at 446
- SNSP in the quarter-hourly file is a **fraction** (0.6375), not a percentage

---

## 7. Findings, with numbers

| # | Finding | Evidence |
|---|---|---|
| 1 | **Groups are electrically coherent, not meteorological** | 11/12 groups beat a random-farm null on effectiveness (mean excess **+0.384**); only 1/12 beat a distance-only null on weather (mean **−0.019**). Same groups, same method |
| 2 | **Irish wind barely decorrelates** | Fitted L = **460 km** summer, **599 km** winter; island is ~450 km. Farms 200–400 km apart still correlate 0.55–0.66 |
| 3 | **The weather model reproduces EirGrid's measurements** | r = 0.984 (**r² = 0.968**), bias −3.8%, RMSE 253 MW, over 5,087 hours. No fitting, no EirGrid data as input |
| 4 | **MUON dominates curtailment** | **96.3%** of all-island curtailment 2024, computed from EirGrid reason codes — not cited |
| 5 | **The two group mappings never contradict** | 0 genuine conflicts in 112 farms. The 20 differences are all "model has nationwide only, WDT adds regional" |
| 6 | **The model omits the South-East entirely** | 16 farms, 269 MW, fall back to `ROI/1`. Plus ROI-NW 4 farms and ROI-W 4 farms |
| 7 | **`ROI-W/2` is not electrically coherent** | 95 members, "all of the West", the one group failing the effectiveness test. Where a per-farm optimum should win biggest |
| 8 | **Flat pro-rata attribution is provably wrong** | Every farm lands 14.1–16.0%, Donegal to Wexford. The flatness measures what a location-blind method misses |
| 9 | **Model line ratings never vary** | 0 of 586 vary across July — static ratings, which is what DLR exists to relax |
| 10 | **Greenlink missing from the briefings** | Live in 89% of periods, mean +313 MW. Briefings list only EWIC, Moyle, Celtic, North–South |

Extraction validated against five published EirGrid figures exactly: all-island
2024 14.0%, RoI 10.1%, NI 29.6%, RoI 2025 split 6.68%+4.76%, MUON ~96%.

---

## 8. What is left

### Blocking decisions — need the user, not a tool

**D1. Overlapping or disjoint clustering?** EirGrid's groups overlap (farms carry
up to 4 tags). k-means and spectral clustering give disjoint exhaustive
partitions, so the standard tool cannot produce the answer's shape. Options:
fuzzy c-means, NMF, or per-constraint thresholding of the effectiveness vector.
*Thresholding is recommended — closest to EirGrid's own description.* **Open.**

**D2. Scoring metric?** ARI and NMI assume disjoint sets. Need omega index,
overlapping NMI, or per-group precision/recall on station sets. **Open.**

**D3. Validate-and-extend Nayer's mapping, or reconstruct independently?**
**Decided 5 Sep: validate and extend.**

**D4. Does MCMC earn its place?** Only if the partition objective has constraints
with no closed form (contiguity, size limits, overlap). Otherwise spectral +
thresholding is deterministic and faster. **Open.**

### Technical work

1. **N-1 / BODF** — largest gap. EirGrid define effectiveness against
   *"base case, N-1 or N-1-1"* overloads, so contingency analysis is inside the
   definition. `sub_network.calculate_BODF()`, one call. Also the stated reason
   the Nayer model underestimates constraint, so it is a differentiator too.
2. **The clustering itself** — blocked on D1/D2.
3. **Stage 3: DC-OPF and the euro figure** — solver installed and tested, unused.
4. **Workshop capstone unfinished** — `05-workshops/graph-theory/` Session 2 cell
   29 has step 1 only; steps 2–4 and the conclusion blank. It is the null-model
   validation template the two group tests already borrowed.
5. **MCMC bug** — `05-workshops/mcmc/MCMCworkshop.py` has
   `beta_c = (1/J)(1+√q)`; the 2D Potts critical point is `ln(1+√q)/J`. The run
   sits at β = 4.098 vs β_c ≈ 1.005, i.e. **4.1× above critical**. Output confirms
   it: last 500 sweeps at `E = −200.00`, `M = 1.000` — frozen ground state.
6. **Network map** — the bus sheet has no coordinates, so `n.plot()` renders
   nothing geographic. Farm lat/lon exists for 129 matched buses; could seed a map.

### Honesty items for the presentation

- Per-farm dispatch-down is not public → validation is station-level, euro figures
  are modelled
- The network model is a **draft** by its author's own statement; N-1 not modelled,
  so it underestimates constraint
- ERA5 is reanalysis, not forecast — do not call hindcasting prediction
- Generic power curve, not per-site turbines
- **State scope on slide 1** — RoI/all-island/NI differ by ~2.6×
- **€567m is the Network Imperfections Charge** (SEM-25-053), a broader basket
  than curtailment. Not "the cost of curtailment"
- Braess: the Witthaut & Timme DOI is confirmed, but **nobody has applied it to
  the Irish grid** — doing so would be original

---

## 9. User preferences observed

- Wants **concise, clear, simple** output. Has asked repeatedly. Bullets and small
  tables over prose
- **No speculation presented as fact.** Verify with a tool before stating; say
  "not checked" rather than guessing
- Values honest negative results and self-limiting analyses
- Wants everything outside this file readable by "someone off the street"
- Dislikes overstating problems — asked explicitly not to frame the join's
  coverage gaps as contradictions when there are none
- Working alongside this on another project; expects work to proceed without
  constant check-ins

---

## 10. Fastest orientation for a successor

1. Read `Rundown.md` — the full explainer, written for a human
2. Read `01-brief/TODO.md` — open decisions and remaining work
3. Run `03-network/scripts/verify_ptdf.py` — confirms the physics chain works (8/8)
4. Open `03-network/script-output/effectiveness-farm-by-line.csv` — the core output
5. Look at `07-figures/charts/13-weather-vs-effectiveness.png` — the headline result

**The single next action:** N-1 via `calculate_BODF()`, since it is one call, it
is inside EirGrid's own definition, and it is the model's known weakness.

---

*Written 5 September 2026, after the session that built everything above.*
