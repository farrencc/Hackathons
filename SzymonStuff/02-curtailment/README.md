# 02 — Curtailment

Why Ireland wastes wind energy, and the official numbers for how much.

Read this before [../03-network/](../03-network/). The network model only makes
sense once you know what curtailment and constraint actually are.

**Layout.** `data/` EirGrid reports · `scripts/` extraction code · `script-output/` tidy CSVs

---

## The one distinction that matters

**Dispatch-down** is EirGrid instructing a wind or solar farm to reduce output.
It splits into two things that need completely different solutions:

| | **Curtailment** | **Constraint** |
|---|---|---|
| **Scope** | System-wide | Local |
| **Cause** | SNSP limit, minimum units online | Not enough transmission capacity here |
| **Analogy** | The whole system can't absorb it | A traffic jam on one road |
| **Fixed by** | Storage, flexibility, interconnection | Reinforcement, redispatch, better siting |
| **RoI 2025** | 4.7% | 6.6% |

Two acronyms carry most of the physics:

- **SNSP** (System Non-Synchronous Penetration) — the maximum share of
  instantaneous generation allowed from non-synchronous sources: wind, solar,
  HVDC imports. Raised 50% (2015) → 65% → 70% → **75% (April 2022, current)**.
- **MUON** (Minimum Number of Units Online) — conventional synchronous plant
  that must keep running for frequency, voltage and reserve stability.
  **This is the inertia problem**, and it is the bigger lever.

> **The key empirical result.** In 2020–21, **MUON — not SNSP — drove roughly 80%
> of curtailment**. In 2024 EirGrid attributed **96% of RoI curtailment** to it.
> A project aimed only at the SNSP cap addresses a small slice of the problem.
>
> Read the scope carefully: that 80% is a share of *curtailment*, not of total
> dispatch-down. Since 2025, *constraint* is the larger half overall.

## The numbers, with their scope

Always state which one you are quoting — they differ by a factor of ~2.6.

| Measure | Value |
|---|---|
| RoI wind dispatch-down, 2025 | **11.3%** (4.7 curtailment + 6.6 constraint) |
| All-island wind dispatch-down, 2024 | **14.0%** (2,181 GWh) |
| Northern Ireland, 2024 | **29.6%** |
| Northern Ireland, 2025 | **21.7%** |
| All-island renewables as % of demand, 2024 | **40.0%** |
| All-island wind generated, 2024 | **13,288 GWh** |

**On cost — quote carefully.** The widely repeated **€567m** is the *Network
Imperfections Charge allowed for tariff year 2024/25* (€567.21m, SEM-25-053), a
broader basket than curtailment that also covers make-whole payments and net
imbalance energy cost. It is **not** "the cost of curtailment."

---

## Files, most important first

### 1. [ireland-high-voltage-grid.md](ireland-high-voltage-grid.md) — the sourced briefing
The authoritative domain document. Constraint groups, dispatch machinery, the
physical limits, current statistics, and an explicit caveats section. **Where any
other file in this repository disagrees with it, this one wins.**

### 2. [data/Annual-Curtailment-Report-2025.pdf](data/Annual-Curtailment-Report-2025.pdf) — the primary source
EirGrid/SONI's official annual report. The definitive figures for 2025. Use this
rather than secondary analyses.

### 3. [data/DD-Summary-Report-V21.xlsx](data/DD-Summary-Report-V21.xlsx) — the core time series
Half-hourly dispatch-down volumes, multi-year. Six sheets; the useful one is
**"Wind & Solar Monthly Detailed"**, which breaks dispatch-down down by *reason
code* — constraints, transmission constraint, TSO testing, curtailment, high
frequency / min gen, RoCoF / inertia. This is your validation ground truth.

### 4. [data/DD-Calc-UserGuide-v1.1.pdf](data/DD-Calc-UserGuide-v1.1.pdf) — the methodology
How EirGrid actually calculates constraint vs curtailment MWh, with worked
examples. **Read this before modelling anything**, or you will compute a
different quantity from the one in the reports.

### 5. Supporting series
- [data/System-and-Renewable-Summary-V28.xlsx](data/System-and-Renewable-Summary-V28.xlsx) — fuel mix, installed wind capacity, renewable %
- [data/System-Data-Qtr-Hourly-2026-V7.xlsx](data/System-Data-Qtr-Hourly-2026-V7.xlsx) — quarter-hourly system state, Jan–Jul 2026 (partial year)
- [data/System-Data-Qtr-Hourly-2025-V12.xlsx](data/System-Data-Qtr-Hourly-2025-V12.xlsx) — the same for **all of 2025**, 35,040 rows. A complete calendar year, and it covers July 2025, the period the network model's time series uses. EirGrid increment the version through the year (V2 held only Q1), so always take the highest available

### 6. Extracted, machine-readable versions

The two source workbooks are laid out for humans. These scripts flatten them.

| File | What it is |
|---|---|
| [scripts/extract_dd.py](scripts/extract_dd.py) -> [script-output/dispatch-down-by-reason-monthly.csv](script-output/dispatch-down-by-reason-monthly.csv) | 5,610 rows: year, month, region, reason code, MWh. **2016-2026** |
| [scripts/extract_system.py](scripts/extract_system.py) -> [script-output/system-state-15min-2026.csv](script-output/system-state-15min-2026.csv) | 20,348 rows of 15-minute system state, Jan-Jul 2026 |

**The extraction is validated against five published figures**, all reproduced
from the raw data:

| | Computed | Published |
|---|---|---|
| All-island dispatch-down 2024 | 14.0% | 14.0% |
| Ireland 2024 | 10.1% | 10.1% |
| Northern Ireland 2024 | 29.6% | 29.6% |
| Ireland 2025 split | 6.68% constraint + 4.76% curtailment | 6.6% + 4.7% |
| MUON share of all-island curtailment 2024 | 96.3% | ~96% |

That last row matters: **you can now compute the MUON result from primary data
rather than citing it.**

Two things the quarter-hourly file gives you that nothing else does:
**wind availability minus generation is dispatch-down at 15-minute resolution**
(without the reason attached), and a live **SNSP** series - mean 55.2%, max
76.2% against a 75% limit, above 70% for 16% of periods.

Quarterly subtotal rows are kept but flagged `is_month=no`; including them in a
sum would double-count.

### 7. [data/archive](data/archive) — earlier annual reports
2023 and 2024 editions, for trend comparison and because definitions shift
between editions.

---

## References

All EirGrid files retrieved **5 September 2026** from the *System and Renewable
Data Reports* hub, <https://www.eirgrid.ie/grid/system-and-renewable-data-reports>.
Free to download; no account required.

| File | Source | Retrieved |
|---|---|---|
| `ireland-high-voltage-grid.md` | Compiled by Szymon Ablewicz, 1 Sep 2026, from ~300 web sources; every claim individually tagged | — |
| `data/Annual-Curtailment-Report-2025.pdf` | EirGrid/SONI, *Annual Renewable Energy Constraint and Curtailment Report 2025*, v1.0. Mirrored at <https://hacktheclimate.io/samples/Annual-Renewable-Constraint-and-Curtailment-Report-2025-V1.0.pdf> | 5 Sep 2026 |
| `data/DD-Summary-Report-V21.xlsx` | EirGrid, *DD Summary Report* v21. <https://cms.eirgrid.ie/sites/default/files/publications/DD-Summary-Report-V21.xlsx> | 5 Sep 2026 |
| `data/DD-Calc-UserGuide-v1.1.pdf` | EirGrid, *New Wind DD Calculation User Guide* v1.1. <https://cms.eirgrid.ie/sites/default/files/publications/New-Wind-DD-Calc-Userguide-v1.1.pdf> | 5 Sep 2026 |
| `data/System-and-Renewable-Summary-V28.xlsx` | EirGrid, *System and Renewable Data Summary Report* v28 | 5 Sep 2026 |
| `data/System-Data-Qtr-Hourly-2026-V7.xlsx` | EirGrid, *System Data Quarter Hourly 2026* v7 (Jan–Jul) | 5 Sep 2026 |
| `data/System-Data-Qtr-Hourly-2025-V12.xlsx` | EirGrid, *System Data Quarter Hourly 2025* v12 (full year) | 5 Sep 2026 |
| `archive/Annual-Curtailment-Report-2024.pdf` | EirGrid/SONI, *Annual Renewable Energy Constraint and Curtailment Report 2024* v1.0 | 5 Sep 2026 |
| `archive/Annual-Curtailment-Report-2023.pdf` | EirGrid/SONI, same series, 2023 edition | 5 Sep 2026 |
| `script-output/dispatch-down-by-reason-monthly.csv`, `script-output/system-state-15min-2026.csv` | **Generated** by the scripts in this folder | 5 Sep 2026 |

**Underlying academic source for the MUON result:** M. Hurtado, T. Kërçi,
S. Tweed, E. Kennedy, N. Kamaluddin and F. Milano, "Analysis of Wind Energy
Curtailment in the Ireland and Northern Ireland Power Systems," *2023 IEEE Power
& Energy Society General Meeting (PESGM)*, pp. 1–5.
Preprint: [arXiv:2302.07143](https://arxiv.org/abs/2302.07143).

**Cost figures:** SEM Committee decision **SEM-25-053** (Network Imperfections
Charge, tariff year 2024/25). The curtailment/constraint distinction was approved
in **SEM-13-011**.

> **Note on the version numbers.** EirGrid increments these (`V21`, `V28`, `V7`)
> as they publish updates. Check the hub page for a newer edition before quoting
> figures in the presentation.
