# 06 — Reference

A catalogue of data sources. Look here when you need a dataset that isn't already
in this repository.

---

## Files

### [data-scope-audit.md](data-scope-audit.md) — do we have everything?
**Read this first.** A live check of what the project holds, the three gaps that
are genuinely unpublished (per-farm dispatch-down, which constraint bound when,
real turbine power curves), and seven sources worth collecting only if a
specific angle needs them. Also records one correction: the briefings omit
**Greenlink**, an interconnector that is live and carrying power in 2026.

### [irish-grid-curtailment-data-sources.md](irish-grid-curtailment-data-sources.md) — the catalogue

Every publicly accessible tool, dataset, API and document relevant to modelling
Irish wind curtailment, organised into five categories:

| § | Category | Contains |
|---|---|---|
| 1 | Grid topology & infrastructure | Transmission maps, OpenStreetMap routes, connected-generator lists |
| 2 | Curtailment & constraint data | EirGrid dispatch-down reports, the WDT document, annual reports |
| 3 | Real-time & historical system data | Smart Grid Dashboard, ENTSO-E, SEMOpx, ready-made scrapers |
| 4 | Wind resource & farm locations | SEAI wind atlas, Met Éireann, Open-Meteo/ERA5 |
| 5 | Existing research & prior art | The key papers, code releases, and competing student projects |

It closes with **real gaps** (things nobody has published) and **dead ends**
(sources that look promising but are paywalled, request-only, or too coarse) —
both worth reading before spending time searching.

> ### ⚠️ How to use this file
>
> **It is a catalogue of links, not a source of facts.** It was LLM-generated,
> and several of its original claims were wrong or imprecise. Corrections are
> marked `[CORRECTED 01-09-26]` in place.
>
> Verify any number against
> [../02-curtailment/ireland-high-voltage-grid.md](../02-curtailment/ireland-high-voltage-grid.md),
> which is the sourced document.

---

## What has changed since it was written

The catalogue was compiled 29 August and revised 1 September 2026. Three of its
entries are now out of date in this repository's favour:

| Its claim | Status now |
|---|---|
| "No open bus/branch network model" | **Closed.** The model is downloaded — [../03-network/](../03-network/) |
| "No machine-readable farm→constraint-group map" | **Largely closed twice over.** The network model's `prorata_groups` column maps all 294 generators, and the PDF is parsed to [../03-network/script-output/constraint-groups-to-stations.csv](../03-network/script-output/constraint-groups-to-stations.csv) |
| "Repo licence could not be confirmed" | **Resolved.** Both Zenodo deposits are CC BY 4.0. The file states this in its corrections but the older text survives further down — trust the correction |

Still genuinely open, and confirmed by our own checks:

- **No open day-ahead SNSP or wind-forecast feed** for Ireland. Building one is a
  project, not a download.
- **No live breakdown of which specific constraint is binding** right now — only
  retrospective monthly and annual aggregates.
- **ESB Networks' full distribution geometry** is FOI/request-only.
- **No published application of Braess's paradox to the Irish grid.** The
  underlying physics paper is real and verified; the Irish application is not.

---

## Fastest routes to more data

Checked live and returning HTTP 200 on **5 September 2026**:

| Need | Route |
|---|---|
| System demand/generation/wind/SNSP history | `github.com/Daniel-Parke/EirGrid_Data_Download` — full history to CSV in ~11 min, no API key |
| Curtailment time series | Already downloaded — [../02-curtailment/](../02-curtailment/) |
| Per-farm wind | Already built — [../04-meteorology/](../04-meteorology/) |
| Wholesale prices | SEMOpx static reports, or the Ember pre-cleaned dataset |
| EU-wide cross-check | ENTSO-E Transparency Platform — **token takes days, request early** |
| Anything else Irish-energy | `energy-modelling-ireland.github.io/wiki` — a whole community already did this |

**Note:** the *Hack the Climate* hackathon (28–30 Sept 2026, Microsoft Ireland)
has the same stated mission and publishes curated sample data plus the 2025
curtailment report at <https://hacktheclimate.io/>. Free and public — the 2025
report in [../02-curtailment/](../02-curtailment/) came from there.

---

## References

| File | Source |
|---|---|
| `irish-grid-curtailment-data-sources.md` | Compiled by Szymon Ablewicz, 29 Aug 2026, revised 1 Sep 2026. Assembled from 30+ live web searches and page fetches; entries marked ⚠️ were found only via citation and not fetched directly |
| `data-scope-audit.md` | Written 5 Sep 2026. Every source in it was fetched live on that date; HTTP status recorded per row |

**Provenance of the corrections in that file:** each `[CORRECTED 01-09-26]` note
was checked against a primary source on that date — SEM Committee decisions for
the cost figures, the EirGrid WDT PDF for the group count, EirGrid annual reports
for the dispatch-down percentages, and the Zenodo deposit pages for the licences.
