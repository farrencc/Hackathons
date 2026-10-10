# Branch: `Dynamic-Line-Rating`

**Owns:** Q3 — Dynamic Line Rating for `5041-17010-2`
**Status:** ✅ Done, per confirmation this branch is finished — one thing worth
double-checking before closing it out completely.

## Resolved

- **F-01** — retracted 301.9 MVA / +43.7% (winter) and 231.1 MVA / +29.8%
  (summer) numbers superseded. Current authoritative result: 210 → 213 MVA
  (+1.4%) winter, 178 → 184.4 MVA (+3.6%) summer, from
  `dlr-2024-real-weather-rewrite.md`.
- **F-05** — P10-vs-P50 framing addressed (the headline was almost entirely a
  P10 artifact; P50 winter multiplier is ≈+53% vs P10's +1.4%).

## Worth confirming before fully closing

- **F-06, DLR half** — this was a *code* fix, not just a narrative one:
  - `j_seasonal_weather_rating.py:179` hard-coded
    `finner_camp_historical_hourly.csv`; the committed file is
    `finner_camp_historical_hourly_1.csv`. Confirm the filename in the script
    now matches what's actually committed on this branch.
  - `j_dlr_rating_sensitivity.py` and `j_thermal_rating_chart.py` assumed the
    `participant-kit/examples/` layout for `import gridkit`; only
    `j_apply_seasonal_dlr.py` had the dual-layout probe
    (`_find_participant_kit_dir()`). Confirm the other two scripts either got
    the same probe or were retired.
  - **Quick check:** clone the branch fresh and run
    `python j_apply_seasonal_dlr.py` and `python j_dlr_rating_sensitivity.py`
    end to end. If either throws `FileNotFoundError` or `ModuleNotFoundError`,
    F-06 isn't actually closed on this branch yet — it's a narrative-only fix.

## Not this branch's problem

- `301.9` MVA still hard-coded downstream on `Harshitha-Q2-Q4-Battery-Siting`
  (already fixed, per that branch's file) and on `Alex's-Work`'s
  `q6_priority_analysis_bugfix.py` (**not** fixed — see `alexs-work.md`, F-02).
  Nothing to do here; those are the consuming branches' job to update once
  they pull this branch's real number.
