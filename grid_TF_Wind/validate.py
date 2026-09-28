"""Is the ensemble realistic?  Its SNSP and inertia against history.

What it checks
--------------
Whether the ensemble's SNSP and system-inertia marginals overlap what the
all-island system has actually done.  Not whether they match: the ensemble is
meant to reach states the operational limits keep history out of (SNSP above
75%, inertia below 23,000 MWs), so an ensemble that *only* reproduced history
would be failing at its job.  What it must not do is live somewhere history
never goes on the side the limits do not police - high inertia at high SNSP,
say - because that would mean the dispatch is not the island's.

Reported per variable: the fraction of the ensemble inside the historical
range, the overlap coefficient of the two histograms (1 = identical, 0 =
disjoint), the Kolmogorov-Smirnov statistic, and the share of the ensemble
beyond each operational limit, next to history's.

Where history comes from
------------------------
1. A file downloaded by hand from the Smart Grid Dashboard, under
   ``data/raw/eirgrid/`` (``snsp_*.csv`` / ``inertia_*.csv``), or given with
   ``--history``.
2. The dashboard itself, live.
3. Nothing - and then **it skips, with a message.**  It never falls back to
   anything invented.

The committed file ``data/validation/format_fixture.csv`` is **not historical
data**.  It is a hand-made format fixture, every row labelled as such, that
exists so the reader and the overlap metric can be tested without a network.
:func:`validate` refuses it unless told explicitly that it is a test.

Usage
-----
    python validate.py --ensemble data/ensemble/2024_seed42_n50
    python validate.py --ensemble ... --history snsp.csv inertia.csv
"""

from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np
import pandas as pd

import inertia
import profiles

#: The dashboard series this needs.  **The area names are unverified**: the
#: host was refused at the proxy in the session that wrote this, so they are
#: the dashboard's names as best known and not tested against a response.  A
#: hand-downloaded CSV does not depend on them.
DASHBOARD_AREAS = {"snsp": "SnspALL", "inertia": "inertia"}

HISTORY_DIR = profiles.EIRGRID_DIR
FIXTURE = "data/validation/format_fixture.csv"
FIXTURE_MARK = "FORMAT FIXTURE"

#: The operational SNSP limit the share-beyond figure is reported against.
#: Not a constraint anywhere; see ensemble.py.
SNSP_LIMIT = 0.75

#: Histogram bins for the overlap coefficient.
BINS = 20


class Unavailable(RuntimeError):
    """No historical data could be had.  The caller should skip."""


# --------------------------------------------------------------------------- #
# Reading history
# --------------------------------------------------------------------------- #

def read_series(path: str, kind: str) -> pd.Series:
    """One historical series from a file: SNSP as a fraction, inertia in MWs.

    Takes the dashboard's own export through :func:`profiles.read_eirgrid`.
    SNSP published as a percentage is converted to a fraction.  A value
    outside the physical range for its kind is refused rather than clipped.
    """
    series = profiles.read_eirgrid(path)
    if kind == "snsp":
        if series.max() > 1.5:
            series = series / 100.0
        if series.min() < 0 or series.max() > 1.2:
            raise Unavailable(f"{path}: SNSP outside [0, 1.2]")
    elif kind == "inertia":
        if series.min() < 1_000 or series.max() > 200_000:
            raise Unavailable(f"{path}: inertia outside 1,000-200,000 MWs")
    else:
        raise ValueError(kind)
    return series.rename(kind)


def read_fixture(path: str = FIXTURE) -> pd.DataFrame:
    """The committed format fixture.  For tests only."""
    frame = pd.read_csv(path)
    if not frame["source"].str.contains(FIXTURE_MARK).all():
        raise ValueError(f"{path} is not labelled as a fixture in every row")
    return frame


def find_history(paths: list[str] | None = None) -> dict:
    """History from given files, else the local EirGrid folder, else live."""
    found = {}
    if paths:
        for path in paths:
            kind = "snsp" if "snsp" in os.path.basename(path).lower() \
                else "inertia"
            found[kind] = read_series(path, kind)
        return found
    for kind in DASHBOARD_AREAS:
        files = sorted(glob.glob(os.path.join(HISTORY_DIR, f"{kind}_*")))
        if files:
            found[kind] = pd.concat([read_series(f, kind) for f in files])
    if found:
        return found
    return fetch_live()


def fetch_live(year: int = 2024, timeout: float = 30.0) -> dict:
    """The dashboard, live.  Raises :class:`Unavailable` on any failure."""
    import requests

    found = {}
    for kind, area in DASHBOARD_AREAS.items():
        url = (f"{profiles.DASHBOARD_URL}?area={area}&region=ALL"
               f"&datefrom={year}-01-01+00%3A00&dateto={year}-12-31+23%3A59")
        try:
            response = requests.get(url, timeout=timeout)
        except Exception as exc:                              # noqa: BLE001
            raise Unavailable(
                f"Smart Grid Dashboard unreachable ({type(exc).__name__}: "
                f"{str(exc)[:160]}).  Download SNSP and inertia CSVs by hand "
                f"into {HISTORY_DIR}/ as snsp_<year>.csv and "
                "inertia_<year>.csv, or pass --history.") from exc
        if response.status_code != 200:
            raise Unavailable(f"dashboard returned {response.status_code} "
                              f"for {area}")
        os.makedirs(HISTORY_DIR, exist_ok=True)
        path = os.path.join(HISTORY_DIR, f"{kind}_{year}.json")
        with open(path, "w") as fh:
            fh.write(response.text)
        found[kind] = read_series(path, kind)
    return found


# --------------------------------------------------------------------------- #
# The comparison
# --------------------------------------------------------------------------- #

def overlap(a, b, bins: int = BINS) -> dict:
    """How far two samples share their support, several ways."""
    from scipy.stats import ks_2samp

    a, b = np.asarray(a, float), np.asarray(b, float)
    lo, hi = min(a.min(), b.min()), max(a.max(), b.max())
    if hi <= lo:
        hi = lo + 1.0
    edges = np.linspace(lo, hi, bins + 1)
    pa, _ = np.histogram(a, edges)
    pb, _ = np.histogram(b, edges)
    pa, pb = pa / pa.sum(), pb / pb.sum()
    return {
        "overlap_coefficient": float(np.minimum(pa, pb).sum()),
        "ks_statistic": float(ks_2samp(a, b).statistic),
        "share_inside_history_range": float(
            np.mean((a >= b.min()) & (a <= b.max()))),
        "ensemble_median": float(np.median(a)),
        "history_median": float(np.median(b)),
    }


def validate(scenarios: pd.DataFrame, history: dict,
             allow_fixture: bool = False) -> dict:
    """Ensemble SNSP and pre-trip inertia against the historical series."""
    for kind, series in history.items():
        if getattr(series, "attrs", {}).get("fixture") and not allow_fixture:
            raise Unavailable(f"the {kind} history is the format fixture, "
                              "not historical data")
    result = {}
    columns = {"snsp": "snsp", "inertia": "E_pre_mws"}
    limits = {"snsp": ("above", SNSP_LIMIT),
              "inertia": ("below", inertia.OPERATIONAL_INERTIA_FLOOR_MWS)}
    for kind, series in history.items():
        ens = scenarios[columns[kind]].to_numpy(float)
        hist = series.to_numpy(float)
        side, limit = limits[kind]
        beyond = (lambda x: np.mean(x > limit)) if side == "above" \
            else (lambda x: np.mean(x < limit))
        result[kind] = {**overlap(ens, hist),
                        f"ensemble_share_{side}_limit": float(beyond(ens)),
                        f"history_share_{side}_limit": float(beyond(hist)),
                        "n_ensemble": int(len(ens)),
                        "n_history": int(len(hist))}
    return result


def fixture_history(path: str = FIXTURE) -> dict:
    """The format fixture as history series, flagged so validate() refuses it."""
    frame = read_fixture(path)
    index = pd.to_datetime(frame["timestamp"])
    out = {}
    for kind, col in (("snsp", "snsp"), ("inertia", "inertia_mws")):
        series = pd.Series(frame[col].to_numpy(float), index=index, name=kind)
        series.attrs["fixture"] = True
        out[kind] = series
    return out


def main(argv=None) -> int:
    import ensemble

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ensemble", required=True)
    parser.add_argument("--history", nargs="*", default=None)
    args = parser.parse_args(argv)
    scenarios = ensemble.load(args.ensemble)["scenarios"]
    try:
        history = find_history(args.history)
    except Unavailable as exc:
        print(f"SKIPPED: no historical SNSP or inertia data.  {exc}")
        report = {"status": "skipped", "reason": str(exc)}
    else:
        report = {"status": "validated", **validate(scenarios, history)}
        print(json.dumps(report, indent=2))
    with open(os.path.join(args.ensemble, "validation.json"), "w") as fh:
        json.dump(report, fh, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
