# Hackathon Team 9: Easing Wind Constraints on the Irish Grid

Our work for the **TPSA & TFWind Hackathon 2026**. Roughly half of the renewable generation dispatched down in Ireland is down to **constraints** rather than system-wide curtailment: specific lines run out of headroom and the wind farms behind them are switched off. We take a PyPSA model of Ireland's transmission network and ask which lines bind, which wind farms can relieve them, and what a battery, a dynamic line rating (DLR) or a smarter curtailment rule would change.

The base network and the starter kit come from the hackathon organisers and live in [`grid_TF_Wind/`](grid_TF_Wind/). Everything else in this repository is our analysis built on top of it.

## Headline findings

All numbers are for the `WP2033` scenario (2033 winter peak), north-west region, over the modelled 168-hour week, unless stated otherwise.

- **One line is the bottleneck.** `5041-17010-2` (210 MVA) is the only north-west circuit that reaches 100% loading, and it sits at its rating for 52 of 168 hours. Nationally the worst line is a different one (`3581-89516-1`).
- **A bigger rating helps, with diminishing returns.** Raising the rating by 30% cuts hours-at-rating from 52 to 13 but does not remove the constraint.
- **A real weather-based DLR is modest.** Using Met Éireann weather and PVGIS solar gives a winter rating of 213.0 MVA (+1.4%). An earlier proxy figure of 301.9 MVA was retracted.
- **Battery sizing basis.** 588.6 MWh of wind is curtailed for this constraint over the week at the static rating. At the 213 MVA DLR rating it falls to 507.8 MWh (-13.7%).
- **The sign of a shift factor matters more than its size.** Corderry, Glenree and Sligo have the largest shift factor (+0.579) but the opposite sign to the ten farms in the other group (-0.238). The line loads in one direction, so the +0.579 farms cannot relieve it, and all of the constraint curtailment sits in the second group.
- **Multi-line awareness gives smaller curtailment groups.** In the first validation case, a 15-node group that accounts for side effects on other lines relieves the same 2.0 MW overload as a 28-node group, while cutting 128 MW instead of 220 MW.

## Repository map

```
.
├── grid_TF_Wind/            Organiser-provided network, data and starter kit
│   └── participant-kit/     The PyPSA networks + gridkit.py our scripts import
│
├── n_binding_lines_baseline.py     Step 1  find the binding lines (all-island)
├── o_shift_factor_matrix.py        Step 2  shift factors: node x binding line
├── p_multi_line_conflicts.py       Step 3A which nodes help one line but hurt another
├── step3b_group_generation.py      Step 3B candidate curtailment groups
├── Alex's Work 3.2/                Step 4  validate and compare the groups
│
├── fetch_pvgis_2024_solar.py       Q3  DLR inputs and ratings (j_*.py)
├── j_*.py
├── k_battery_siting_sizing.py      Q2/Q4  battery siting and sizing
├── l_battery_validation.py
├── h_export_hourly_flows.py        Track A exports (Q1/Q5)
├── i_export_shift_factors.py
├── Alex's Work 3.1/                Q6  priority vs non-priority wind farms
│
├── *.csv                           Pipeline inputs/outputs the scripts read by name
├── docs/                           Write-ups, grouped by topic (see below)
├── figures/                        Saved charts and interactive maps
├── results/                        Older or suffixed result files kept for reference
├── archive/duplicates/             Byte-identical copies of files kept elsewhere
├── workshop/, populationDensity_2024/   Supporting workshop and map material
└── shell.nix                       Nix dev shell
```

### Documentation (`docs/`)

| Folder | Contents |
| --- | --- |
| [`docs/pipeline/`](docs/pipeline/) | Step 1 summary ([v1](docs/pipeline/step1-line-binding-full-summary.md), [v2](docs/pipeline/step1-line-binding-full-summary_2.md)), [Track A summary](docs/pipeline/TRACK_A_SUMMARY_1.md), [shift-factor note](docs/pipeline/shift_factor_matrix_technical_note.md), [multi-line conflicts](docs/pipeline/p_multi_line_conflicts_summary.md), [Step 3B method](docs/pipeline/step3b-group-generation.md) |
| [`docs/dlr/`](docs/dlr/) | Dynamic line rating: [first proxy version](docs/dlr/chibuikeim-q3-summary%20%281%29.md), [real-weather version](docs/dlr/chibuikeim-q3-summary_2.md), [2024 rewrite](docs/dlr/dlr-2024-real-weather-rewrite%20%281%29.md), [presentation summary](docs/dlr/dlr-presentation-summary_1%20%281%29%20%281%29.md), [branch notes](docs/dlr/dynamic-line-rating.md) |
| [`docs/batteries/`](docs/batteries/) | [Battery siting and sizing, developer siting narrative](docs/batteries/harshitha-q2-q4-summary.md) |
| [`docs/audits/`](docs/audits/) | Responses to review findings on Step 1 and Step 3B |

The grid model itself is documented in [`grid_TF_Wind/README.md`](grid_TF_Wind/README.md) and [`grid_TF_Wind/participant-kit/README.md`](grid_TF_Wind/participant-kit/README.md).

## The analysis pipeline

Each step reads the CSVs written by the one before it.

| Step | Script | Reads | Writes |
| --- | --- | --- | --- |
| 1. Binding lines | `n_binding_lines_baseline.py` | kit networks | `binding_lines.csv`, `baseline_hourly_flows.csv` |
| 2. Shift factors | `o_shift_factor_matrix.py` | `binding_lines.csv` | `shift_factor_matrix.csv`, `shift_factor_matrix_wide.csv`, `candidate_renewable_nodes.csv` |
| 3A. Multi-line conflicts | `p_multi_line_conflicts.py` | `binding_lines.csv`, `shift_factor_matrix.csv`, `baseline_hourly_flows.csv` | `multi_line_conflicts.csv`, heatmap and top-20 charts |
| 3B. Group generation | `step3b_group_generation.py` | `binding_lines.csv`, `baseline_hourly_flows.csv`, `shift_factor_matrix.csv` | `proposed_groups.csv`, `group_method_comparison.csv`, `group_map_readable.csv`, `multiline_tradeoff_analysis.csv` |
| 4. Validation | `Alex's Work 3.2/p_step4_validation_comparison_v3_final.py` | the network plus the Step 1-3 outputs | `validation_results.csv`, `validation_comparison_table.csv` |

The Step 3B outputs are created when the script runs. The copies committed here carry upload suffixes such as `_2` or `(1)` and are kept in [`results/step3b/`](results/step3b/).

Questions from the hackathon sheet map onto the scripts like this:

| Question | Where |
| --- | --- |
| Q1 most-constrained lines, Q5 shift factor per wind farm | kit scripts `a`, `d`, `f`, plus `h_export_hourly_flows.py`, `i_export_shift_factors.py` ([summary](docs/pipeline/TRACK_A_SUMMARY_1.md)) |
| Q2 battery siting and sizing, Q4 developer siting narrative | `k_battery_siting_sizing.py`, `l_battery_validation.py` ([summary](docs/batteries/harshitha-q2-q4-summary.md)) |
| Q3 dynamic line rating | `fetch_pvgis_2024_solar.py`, `j_*.py` ([summary](docs/dlr/dlr-2024-real-weather-rewrite%20%281%29.md)) |
| Q6 priority vs non-priority wind farms | [`Alex's Work 3.1/`](Alex's%20Work%203.1/) (a small negative marginal cost stands in for priority dispatch) |

## Running it

Install the kit's requirements (a Nix shell is provided in `shell.nix` if you prefer):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r grid_TF_Wind/participant-kit/requirements.txt
```

Run the pipeline scripts **from the repository root**, in step order:

```bash
python n_binding_lines_baseline.py WP2033 all-island overload_hours 15
python p_multi_line_conflicts.py
python step3b_group_generation.py
```

A few scripts (`h_export_hourly_flows.py`, `i_export_shift_factors.py`, `j_dlr_rating_sensitivity (1).py`, `j_thermal_rating_chart (1).py`) were written to sit in `grid_TF_Wind/participant-kit/examples/` and look for `gridkit.py` relative to their own location. Copy them there to run them.

## Why the scripts and CSVs stay at the root

The scripts locate their inputs relative to their own folder or the repository root, and several pass CSVs to one another by file name. Keeping them together means the pipeline runs as written. Charts, notes and older result variants are the parts that were moved out of the way. `p_multi_line_conflicts.py` writes its charts into the folder it is run from, so re-running it puts fresh copies at the root; the committed versions live in [`figures/`](figures/).

## Notes on the data and model

- The network is a **DC approximation** of an AC model, so it suits shift-factor and PTDF reasoning but not a substitute for an AC study.
- Each source case is one solved hour; the 168-hour week is built from real weather and demand shapes fitted to that anchor hour.
- Priority and non-priority status is **not** in the dataset. Q6 uses an assumed split (the 7 largest of 14 north-west farms), stated explicitly in its write-up.
- Thresholds such as `TAU = 0.05` in Step 3B are working placeholders, not validated values.
