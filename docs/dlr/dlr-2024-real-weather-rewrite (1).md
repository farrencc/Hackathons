# DLR rewrite — 2024-only weather, real PVGIS solar, real wind-direction physics

This supersedes the methodology described in `dlr-presentation-summary.md`
and `dlr-cross-team-impact.md`. Those documents describe the 29-year
(1997-2026), wind+temperature-only, perpendicular-wind-assumed version of
`j_seasonal_weather_rating.py`. This rewrite is a different, more
defensible version of the same script, **now run end-to-end against real
data**. The 43.7%/29.8% winter/summer uplift numbers in those documents
**no longer apply** — don't quote 301.9/231.1 MVA against this new code.

## Real results (final, real 2024 Met Éireann weather + real PVGIS-derived solar)

| Season | Static rating | New real-weather rating | Change |
|---|---|---|---|
| Winter (WP2033, P10) | 210.0 MVA | **213.0 MVA** | **+1.4%** |
| Summer (SV2033, P10) | 178.0 MVA | **184.4 MVA** | **+3.6%** |

| Season | Static dispatch-down | New rating dispatch-down | Change |
|---|---|---|---|
| Winter | 3,660.6 MWh | 3,579.4 MWh | −81.2 MWh |
| Summer | 21,813.6 MWh | 21,406.0 MWh | −407.6 MWh |

**This is a dramatically smaller uplift than the old 29-year/no-solar/
perpendicular-wind figures (+43.7%/+29.8%)** — expected, not a bug. Three
things separately pull it down: a single year (2024) instead of a 29-year
blend, real solar heat gain now subtracted from available cooling capacity
(bigger effect in summer), and real per-hour wind-direction geometry
instead of assuming every hour's wind hits the line perfectly perpendicular
(the old code's implicit best-case assumption). All three are more
defensible individually, and together they replace an overstated number
with a smaller, better-grounded one. **Any slide/narrative quoting the old
43.7%/29.8% or "eliminates the entire winter constraint" framing needs to
be redone against these numbers** — the winter constraint does NOT
disappear this time (3,579 MWh still stranded, not ~0), so the "DLR alone
solves winter" headline from `dlr-presentation-summary.md` no longer holds.

## The +1.4% headline is a P10, not the median — the full band matters (audit finding F-05)

`+1.4%` (213.0 MVA) is the **P10** of the per-hour rating-multiplier
distribution — the value that representative 2024 winter weather supports
at least 90% of the time, deliberately the conservative end of the
distribution (see "P10 is documented as this study's own conservative
choice" above), not the middle of it. `j_seasonal_weather_rating.py`
prints the full distribution on every run; recomputed here from the
committed `j_seasonal_dlr_5041-17010-2_2024_winter.csv` (2,184 valid
hours):

| Percentile | Multiplier | Implied winter rating | Implied uplift |
|---|---|---|---|
| p5 | 0.921 | 193.4 MVA | −7.9% |
| **p10 (headline)** | **1.014** | **213.0 MVA** | **+1.4%** |
| p25 | 1.265 | 265.7 MVA | +26.5% |
| p50 (median) | 1.530 | 321.3 MVA | +53.0% |
| mean | 1.547 | 324.9 MVA | +54.7% |

The median winter hour would support a rating over 50% higher than static
— the P10 headline is genuinely the conservative tail, not a
representative "typical" hour. This is a legitimate, stated study choice
(P10 is a standard conservative-planning percentile, the same exceedance
logic as a P90 wind-resource estimate), but it should be presented as a
**band** (roughly +1% to +55% depending on how conservative the assumed
operating rule is), with the reason for choosing the conservative end
stated explicitly, rather than quoting +1.4% alone as if it were the only
number the weather supports. **The equivalent summer band has not yet
been computed** — re-run the same percentile printout against
`j_seasonal_dlr_5041-17010-2_2024_summer.csv` before presenting a summer
band claim.

## The PVGIS solar data is a documented 2023-into-2024 proxy, not real 2024 solar

PVGIS's radiation database (PVGIS-SARAH3, for this location) does not yet
cover 2024 — 2023 is the most recent complete year available. **Real 2023
PVGIS solar radiation (uploaded by hand from PVGIS's own interactive tool,
`Timeseries_54.487_8.222_SA3_0deg_0deg_2023_2023.csv`) was calendar-matched
onto the 2024 calendar** (same month/day/hour) rather than invented or
defaulted to 0 — see `fetch_pvgis_2024_solar.py`'s docstring ("PVGIS DOES
NOT YET HAVE 2024 DATA") for the full reasoning. The one date with no
direct match (2024-02-29, a leap day; 2023 isn't a leap year) falls back to
2023-02-28, 24 hours, clearly logged. Every row in `pvgis_2024_solar.csv`
carries `source_observed_at_utc`/`source_year` columns pointing back to the
real 2023 hour it came from, and `j_seasonal_weather_rating.py` prints a
loud NOTE every run surfacing this substitution — it is never silently
passed off as real 2024 observations. This is a real, stated limitation:
"2024 solar" here means "real 2023 solar, replayed onto 2024's calendar
dates," not actual 2024 measurements. Re-run `fetch_pvgis_2024_solar.py`
against a real 2024 PVGIS export once PVGIS publishes one, to remove this
substitution entirely.

## What changed in the code, and why

1. **2024 only, not 29 years.** `TARGET_YEAR = 2024` is filtered first,
   before any season filter — "winter" now means Jan+Feb+Dec **2024**
   specifically (not the usual Dec-of-previous-year DJF convention).
2. **Solar radiation is now real (2023-proxy), not zero.** Global
   horizontal irradiance, computed as `Gb(i)+Gd(i)+Gr(i)` from PVGIS's
   component export (confirmed `Gr(i)=0` at every one of 8,760 hours — the
   physically-expected value at 0° tilt), merged onto the weather data by
   exact UTC timestamp and fed into the heat balance hour-by-hour, before
   any percentile is taken. Missing solar → excluded from the calc, not
   defaulted to 0.
3. **Real wind direction, real line azimuth.** The line's true bearing
   (22.33° true) was calculated from `WP2033_north-west/buses.csv`'s real
   geocoded coordinates for Srananagh 220 and Cathaleen's Fall (both
   `coordinate_source=geocoded`, not a fallback) — not invented. Each
   hour's wind is resolved into its component perpendicular to the line
   and *that* speed (not raw wind speed) drives the Reynolds number/Hilpert
   convection term. This also fixes a real physics bug in the old code:
   the old `wind_angle_correction=1.0` assumed every hour's wind hit the
   line exactly perpendicular (the *maximum*-cooling case) and its own
   comment mislabelled that as "conservative" — it's actually optimistic.
4. **Resistance-cancellation is now explained correctly**, not asserted.
5. **P10 is documented as this study's own conservative choice**, not an
   EirGrid or industry convention.
6. **Output CSV is fully expanded** for auditability — every intermediate
   heat-balance term per hour, not just the final multiplier.

## Also found and fixed along the way

- `WEATHER_CSV_FOR_LINE` pointed at `finner_camp_historical_hourly.csv`,
  but the file actually committed on the `Dynamic-Line-Rating` branch is
  named `finner_camp_historical_hourly_1.csv` (GitHub web-upload artifact)
  — the script would `FileNotFoundError` on a fresh checkout.
- Both `j_*.py` scripts' `sys.path`/`ROOT` logic assumed they live at
  `participant-kit/examples/`, but on this branch they're flattened at the
  repo root (same upload artifact) — `import gridkit` and the weather/output
  CSV paths were silently broken. Fixed with a small dual-layout probe
  (`_find_participant_kit_dir()`) so it works either way rather than
  guessing one.
- PVGIS's own API (`re.jrc.ec.europa.eu`) was unreachable from every
  automated channel tried (cloud sandbox network policy, WebFetch's
  robots.txt, and the desktop app's browser pane, which flags it as a
  high-risk site requiring per-action approval that was ultimately
  declined) — real data only entered this project via a person manually
  downloading it from PVGIS's own interactive tool and uploading the file.
  `fetch_pvgis_2024_solar.py` now has a `--from-csv` mode built specifically
  for that real, working path, in addition to the (never actually
  exercised) API path.

## Files

- `j_seasonal_weather_rating.py` (j.1) — full rewrite, see script docstring.
- `j_apply_seasonal_dlr.py` (j.2) — compatibility updates, see script docstring.
- `fetch_pvgis_2024_solar.py` — PVGIS cache-builder; `--from-csv` for a
  manually-downloaded export (the real path used), API mode kept for
  anyone with a working path to `re.jrc.ec.europa.eu`.
- `pvgis_2024_solar.csv` — the real cached solar file (2023 PVGIS data,
  calendar-matched onto 2024 — see above).
- `j_seasonal_dlr_5041-17010-2_2024_{winter,summer}.csv` — full
  per-observation audit trail for both seasons' real runs.
- `j_seasonal_dlr_comparison_5041-17010-2_{winter,summer}.csv` — static vs
  DLR network comparison for both seasons' real runs.
