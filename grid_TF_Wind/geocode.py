"""Coordinates for the TYTFS transmission buses, from OpenStreetMap.

The problem
-----------
PSS/E raw files carry no geography.  A bus record is a number, a twelve-
character name and a base voltage; where the station is, is not in the file.
Every map, every distance, every spatial join a downstream model wants has to
come from somewhere else, and the only name to join on is those twelve
characters.

What this does
--------------
Downloads every named ``power=substation`` and ``power=plant`` on the island
from OpenStreetMap, and matches them against the station names of the buses at
110 kV and above.  Each bus gets a coordinate and a stated method, or no
coordinate and a stated reason.  **Nothing is interpolated, averaged or
guessed**: a bus this cannot match is reported as a failure, by name, with the
best candidate it rejected and why.

Why name matching at all
------------------------
Because there is nothing else to join on.  Voltage is corroboration rather
than a key - OSM's ``voltage`` tag is present on 367 of the island's named
substations and absent or partial on the rest - and it is used that way here:
a voltage that agrees raises a match's confidence, a voltage that is missing
does not lower it, and a voltage that contradicts rejects the match.

The three known hard cases, and what they turned out to be
----------------------------------------------------------
**Cathaleen's Fall** is in TYTFS, as ``CATH_FALL`` and ``CATH FALL`` - the
twelve-character field cannot hold the name.  It is in OSM too, spelled
*Cathleen's Fall*, without the second 'a'.  Neither spelling reaches the other
by truncation or by fuzzy matching alone, so it is in the alias table with
that reasoning written next to it.  ESB's own spelling is Cathaleen's Fall;
OSM's is Cathleen's Fall; the station is one station either way.

**Clady** is not in TYTFS under any name, and this is not a naming problem.
OSM has it as *Clady 38kV Substation* alongside *Clady Hydroelectric Station*,
both at 55.038 N, 8.272 W in Gweedore, Co. Donegal, and both at 38 kV.  A
38 kV ESB Networks station is below the transmission model's floor: TYTFS
carries the sub-110 kV network only as the stub that load and small generation
hangs off, and Clady's four megawatts do not earn a bus of their own.  It is
absent because it is distribution, not because it is misspelled.

**Clogher** is four 110 kV buses in TYTFS - 2870, 2871, 28710, 28712 - and one
substation in OSM, *Clogher 110kV Substation* in Co. Donegal.  The four are
busbar sections of the same site, which is what the 28710-28712 zero-impedance
coupler in the branch section says: split busbars are an electrical
arrangement, not four places.  All four get the same coordinate, and the
report says so rather than leaving three of them unmatched.

Usage
-----
    python geocode.py fetch          # Overpass -> data/raw/osm_substations.json
    python geocode.py candidates     # -> data/osm_substations.csv (committed)
    python geocode.py match          # -> data/pypsa/geocoding.csv, and a report
    python geocode.py report         # the report, from the CSV
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time

import numpy as np
import pandas as pd

import psse
import pypsa_net

# --------------------------------------------------------------------------- #
# Source
# --------------------------------------------------------------------------- #

#: Overpass mirrors, in order.  The main endpoint is not reachable from every
#: network and every mirror rate-limits, so this retries across all of them.
OVERPASS_MIRRORS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

#: Ireland and Northern Ireland, with enough margin for the coastal stations.
ISLAND_BBOX = (51.3, -10.8, 55.5, -5.3)

RAW_PATH = "data/raw/osm_substations.json"
CANDIDATES_PATH = "data/osm_substations.csv"
GEOCODING_DIR = "data/pypsa/geocoding"
GEOCODING_PATH = "data/pypsa/geocoding.csv"

#: The name tags worth reading.  A station is often tagged under one of these
#: and not the others, and OSM's Irish-language names occasionally carry the
#: spelling the English name lost.
NAME_TAGS = ("name", "official_name", "alt_name", "short_name", "old_name",
             "name:en", "name:ga", "ref")


def overpass(query: str, attempts: int = 8, pause: float = 8.0) -> dict:
    """Run an Overpass query, retrying across mirrors.

    Overpass answers a query it cannot schedule with an HTML page carrying a
    "server is probably too busy" runtime error and a 200 status, so success
    is judged on the payload rather than on the status code.
    """
    import requests

    last = ""
    for attempt in range(attempts):
        url = OVERPASS_MIRRORS[attempt % len(OVERPASS_MIRRORS)]
        try:
            response = requests.get(url, params={"data": query}, timeout=900)
            if response.text.lstrip().startswith("{"):
                payload = response.json()
                if "elements" in payload:
                    return payload
            last = response.text[:200].replace("\n", " ")
        except Exception as exc:                            # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"Overpass gave nothing usable after {attempts} "
                       f"attempts across {len(OVERPASS_MIRRORS)} mirrors. "
                       f"Last response: {last}")


def fetch(path: str = RAW_PATH) -> dict:
    """Download every named substation and power plant on the island."""
    south, west, north, east = ISLAND_BBOX
    box = f"({south},{west},{north},{east})"
    query = (f'[out:json][timeout:600];('
             f'nwr["power"="substation"]{box};'
             f'nwr["power"="plant"]{box};);out center tags;')
    payload = overpass(query)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh)
    return payload


# --------------------------------------------------------------------------- #
# Candidates
# --------------------------------------------------------------------------- #

#: Words an OSM substation name carries that are not part of the station's
#: name: what it is, what it is rated at, who runs it.
_DECORATION = re.compile(
    r"\b("
    r"\d{2,3}\s*k\.?v\.?|\d{3,6}\s*volts?|"
    r"sub-?stations?|switching\s+(house|station)|switchyard|"
    r"electricity|electrical|transmission|distribution|"
    r"converter|inverter|hvdc|static|interconnector|"
    r"hydro-?electric|power|generating|stations?|plants?"
    r")\b", re.IGNORECASE)

_PUNCTUATION = re.compile(r"[^A-Z0-9 ]+")
_SPACES = re.compile(r"\s+")


def normalise(name: str) -> str:
    """A station name reduced to what is comparable across the two sources.

    Voltage classes, the words "substation" and "power station", punctuation
    and apostrophes all go; ampersands and "St." are spelled out, because the
    two sources disagree about them and neither disagreement means anything.
    """
    if not name:
        return ""
    text = str(name).strip()
    # An apostrophe is dropped rather than turned into a space: Cathleen's
    # is one word in both sources, and splitting it makes it two.
    text = re.sub(r"[\u2018\u2019']", "", text)
    text = text.replace("&", " and ")
    text = re.sub(r"\bSt\.?\b", "Saint", text, flags=re.IGNORECASE)
    text = _DECORATION.sub(" ", text)
    text = _PUNCTUATION.sub(" ", text.upper())
    return _SPACES.sub(" ", text).strip()


def _voltages(tags: dict) -> tuple[float, ...]:
    """The kV values an OSM object claims, from its ``voltage`` tag."""
    raw = str(tags.get("voltage") or "")
    out = []
    for part in re.split(r"[;,]", raw):
        part = part.strip()
        if part.isdigit():
            out.append(round(int(part) / 1000.0, 2))
    return tuple(sorted(set(out), reverse=True))


def candidates(payload: dict) -> pd.DataFrame:
    """One row per named OSM object, with every name it carries."""
    rows = []
    for element in payload["elements"]:
        tags = element.get("tags") or {}
        centre = element.get("center") or element
        lat, lon = centre.get("lat"), centre.get("lon")
        if lat is None or lon is None:
            continue
        names = [tags[t] for t in NAME_TAGS if tags.get(t)]
        if not names:
            continue
        kv = _voltages(tags)
        rows.append({
            "osm": f"{element['type']}/{element['id']}",
            "name": tags.get("name", names[0]),
            "names": " | ".join(dict.fromkeys(names)),
            "keys": " | ".join(dict.fromkeys(
                filter(None, (normalise(n) for n in names)))),
            "power": tags.get("power", ""),
            "operator": tags.get("operator", ""),
            "voltage_kv": ";".join(f"{v:g}" for v in kv),
            "max_kv": max(kv) if kv else np.nan,
            "lat": float(lat), "lon": float(lon),
        })
    return pd.DataFrame(rows).sort_values("name").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Matching
#
# Confidence is a statement about how the match was made, not a probability.
# The order below is the order they are tried in, and every accepted match
# records which one it came from.
# --------------------------------------------------------------------------- #

#: Names that differ between the two sources for a reason, each resolved by
#: hand to a specific OSM object and each carrying why.  This is the only
#: place a human judgement enters the matching, and it is a judgement about
#: names - never about where something is.
ALIASES = {
    "CATH FALL": ("Cathleen's Fall 110kV Substation",
                  "TYTFS truncates Cathaleen's Fall to fit twelve characters; "
                  "OSM spells it Cathleen's Fall, without the second 'a'. "
                  "Neither reaches the other by truncation or by fuzzy match"),
    "CATH_FALL": ("Cathleen's Fall 110kV Substation",
                  "the same station as CATH FALL, on the other busbar"),
    "EASTWEST": ("Portan Converter Station",
                 "the East-West Interconnector's converter station is at "
                 "Portan, Co. Meath, beside Woodland 400 kV; TYTFS names the "
                 "260 kV converter bus EASTWEST and the 400 kV station PORTAN"),
    "GREENLINK": ("Campile Converter Station",
                  "Greenlink's Irish converter station at Great Island, "
                  "tagged in OSM as Campile after the townland; the adjacent "
                  "'Greenlink Interconnector Substation' way carries no "
                  "voltage tag"),
    "BALLYCRO": ("Ballycronan More HVDC Static Inverter Plant",
                 "Moyle's Northern Ireland terminal; TYTFS truncates "
                 "Ballycronan More to BALLYCRO"),
    "MOYL_DUM": ("Ballycronan More HVDC Static Inverter Plant",
                 "the 110 kV dummy bus at the Moyle terminal, same site"),
    "SCOTLAND": ("", "the GB end of Moyle. It is a boundary bus, not a place "
                     "in Ireland, and is left without a coordinate rather "
                     "than being put at Auchencrosh"),
}

#: A fuzzy match needs this score, and this much daylight over the runner-up.
#: The metric is ``token_sort_ratio`` rather than ``token_set_ratio``, because
#: a set ratio scores a subset at 100 - "Irishtown" against "Irishtown Solar
#: Farm" is a perfect match to it, and a solar farm is not a 220 kV station.
FUZZY_ACCEPT = 92
FUZZY_MARGIN = 6

#: A prefix shorter than this is not evidence of anything.
PREFIX_MIN = 6

#: Objects with the same name this close together are the same site mapped
#: more than once - the power station, the 220 kV yard and the 110 kV yard of
#: one station each get their own way in OSM.  Further apart than this and two
#: objects sharing a name are two places.
SAME_SITE_KM = 2.0

#: How far apart two stations of the same name may be before the match is
#: treated as a coincidence rather than a station.  Used only for the
#: cross-check against EirGrid's own asset register.
CROSSCHECK_KM = 5.0

#: Northern Ireland's transmission buses are named with a four- or five-letter
#: contraction and a digit: ANTR1A, BAFD2-, MAGF2-, KILL1-CL.  The letters are
#: a subsequence of the station's name rather than a prefix of it - BAME is
#: BallyMEna, BNCH is BallyNaCHinch, MAGF is MAGheraFelt - so no amount of
#: fuzzy string matching reaches them, and they are matched by subsequence
#: instead.  The digit is the voltage class, 1 for 110 kV and 2 for 275 kV;
#: that holds for every pair the cases contain (BAFD1/BAFD2, CAST1/CAST2,
#: COOL1/COOL2, KELS1/KELS2, HANA1/HANA2) and it is used as corroboration.
NI_CODE = re.compile(r"^([A-Z]{3,6})([12])$")
NI_CODE_KV = {"1": 110.0, "2": 275.0}


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in km."""
    r, p = 6371.0088, np.pi / 180
    dlat, dlon = (lat2 - lat1) * p, (lon2 - lon1) * p
    a = (np.sin(dlat / 2) ** 2
         + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin(dlon / 2) ** 2)
    return float(2 * r * np.arcsin(np.sqrt(a)))


def _subsequence_span(code: str, name: str):
    """How tightly ``code``'s letters sit in ``name``, in order, from its start.

    ``None`` when the letters are not there in order, or when the name starts
    with a different letter.  Otherwise the index of the last letter used:
    LARN sits in LARNE at span 3 and in LISNABREENY at span 9, and the tight
    one is the contraction while the loose one is a coincidence.
    """
    if not name.startswith(code[0]):
        return None
    position = -1
    for character in code:
        position = name.find(character, position + 1)
        if position < 0:
            return None
    return position


def _rapidfuzz():
    from rapidfuzz import fuzz
    return fuzz


def _expand(candidate_frame: pd.DataFrame) -> pd.DataFrame:
    """One row per (candidate, name key), so every alias is matchable."""
    rows = []
    for i, c in candidate_frame.iterrows():
        for key in str(c["keys"]).split(" | "):
            if key:
                rows.append({"row": i, "key": key})
    return pd.DataFrame(rows)


def stations(case: psse.Case, min_kv: float = pypsa_net.TRANSMISSION_KV
             ) -> pd.DataFrame:
    """The stations to geocode: one row per station name at or above the floor.

    Buses are grouped by :func:`pypsa_net.station_of`, because a station's
    busbar sections are one place.  Clogher's four 110 kV buses are one row
    here, and the report says which buses each row stands for.
    """
    bus = case.bus.copy()
    bus["NAME"] = bus["NAME"].fillna("").astype(str).str.strip()
    bus = bus[bus["BASKV"] >= min_kv]
    bus["station"] = [pypsa_net.station_of(n) for n in bus["NAME"]]
    grouped = bus.groupby("station")
    return pd.DataFrame({
        "station": list(grouped.groups),
        "buses": [",".join(str(int(i)) for i in g["I"]) for _, g in grouped],
        "bus_count": [len(g) for _, g in grouped],
        "psse_names": ["|".join(sorted(set(g["NAME"]))) for _, g in grouped],
        "kv": [";".join(f"{v:g}" for v in sorted(set(g["BASKV"]),
                                                 reverse=True))
               for _, g in grouped],
        "max_kv": [float(g["BASKV"].max()) for _, g in grouped],
        "jurisdiction": [psse.jurisdiction(g["AREA"]).iloc[0]
                         for _, g in grouped],
    }).sort_values("station").reset_index(drop=True)


def _voltage_verdict(station_kv: set[float], candidate_kv: str
                     ) -> tuple[str, bool]:
    """Does the candidate's voltage tag agree with the station's buses?

    Three answers, and the middle one matters: OSM's voltage tag is missing on
    more than half the island's substations, so silence is not disagreement.
    """
    if not candidate_kv:
        return "silent", True
    tagged = {float(v) for v in str(candidate_kv).split(";") if v}
    if station_kv & tagged:
        return "agrees", True
    # 380 kV in the PSS/E cases is the 400 kV network's base voltage, and OSM
    # tags it at its nominal 400 kV.  The two are the same circuits.
    if 380.0 in station_kv and 400.0 in tagged:
        return "agrees (380 kV base / 400 kV nominal)", True
    return "contradicts", False


def _narrow(rows: list[int], frame: pd.DataFrame, station_kv: set[float],
            jurisdiction: str = "", claimed: set[str] = frozenset()
            ) -> tuple[list[int], str]:
    """Reduce several candidates for one name to one, or explain why not.

    Four reductions, in order, and whichever one decided the match is recorded
    on it:

    1. which side of the border - Garvagh is a station in Co. Londonderry and
       a wind farm connection in Co. Leitrim, and TYTFS has both, under
       GARVAGH NI and GARVAGH; the jurisdiction the case gives each bus
       separates them;
    2. the voltage tag - one candidate agreeing with the station's buses and
       the rest not is the station;
    3. what the object is - a ``power=substation`` over a ``power=plant``,
       because a station and the power station beside it share a name;
    4. where they are - objects of the same name within 2 km of each other are
       one site mapped at more than one level of detail, and the
       highest-voltage of them is the one to take.
    """
    if len(rows) <= 1:
        return rows, ""
    unclaimed = [i for i in rows if frame.at[i, "osm"] not in claimed]
    if len(unclaimed) == 1:
        return unclaimed, (f"{len(rows)} objects share this name; the others "
                           "are already matched to a station of their own")
    rows = unclaimed or rows
    if jurisdiction in ("IE", "NI"):
        side = [i for i in rows
                if _jurisdiction_of(frame.at[i, "lat"], frame.at[i, "lon"])
                == jurisdiction]
        if len(side) == 1:
            return side, (f"{len(rows)} objects share this name; only one is "
                          f"in {jurisdiction}")
        rows = side or rows
    agreeing = [i for i in rows
                if _voltage_verdict(station_kv,
                                    frame.at[i, "voltage_kv"])[0]
                .startswith("agrees")]
    if len(agreeing) == 1:
        return agreeing, (f"{len(rows)} objects share this name; only one is "
                          "tagged at this station's voltage")
    rows = agreeing or rows
    if len(rows) == 1:
        return rows, ""
    subs = [i for i in rows if frame.at[i, "power"] == "substation"]
    if len(subs) == 1:
        return subs, (f"{len(rows)} objects share this name; only one is a "
                      "substation rather than a power plant")
    rows = subs or rows
    if len(rows) == 1:
        return rows, ""
    spread = max(_haversine_km(frame.at[a, "lat"], frame.at[a, "lon"],
                               frame.at[b, "lat"], frame.at[b, "lon"])
                 for a in rows for b in rows)
    if spread <= SAME_SITE_KM:
        best = max(rows, key=lambda i: (frame.at[i, "max_kv"]
                                        if np.isfinite(frame.at[i, "max_kv"])
                                        else 0.0))
        return [best], (f"{len(rows)} objects share this name and lie within "
                        f"{spread:.1f} km of each other - one site mapped more "
                        "than once; the highest-voltage of them is taken")
    plain = [i for i in rows if not re.search(
        r"wind farm|solar farm|bess|battery", str(frame.at[i, "name"]),
        re.IGNORECASE)]
    if len(plain) == 1:
        return plain, (f"{len(rows)} objects share this name; only one is not "
                       "a wind farm, solar farm or battery connection")
    return rows, (f"{len(rows)} objects share this name and are up to "
                  f"{spread:.0f} km apart")


#: The Republic's county boundaries, already in this repo for the maps.  Used
#: to put an OSM object on one side of the border or the other, because a name
#: shared across it is otherwise unresolvable.
COUNTIES_GPKG = "data/counties_osi.gpkg"
_REPUBLIC = None


def _jurisdiction_of(lat: float, lon: float) -> str:
    """``IE`` or ``NI`` for a coordinate, from the statutory county boundaries.

    Falls back to ``""`` - no opinion - if the boundary file is not there,
    rather than guessing from latitude.
    """
    global _REPUBLIC
    if not (np.isfinite(lat) and np.isfinite(lon)):
        return ""
    if _REPUBLIC is None:
        try:
            import geopandas as gpd
            from shapely.ops import unary_union
            counties = gpd.read_file(COUNTIES_GPKG).to_crs(4326)
            _REPUBLIC = unary_union(counties.geometry.values)
        except Exception:                                   # noqa: BLE001
            _REPUBLIC = False
    if _REPUBLIC is False:
        return ""
    from shapely.geometry import Point
    return "IE" if _REPUBLIC.covers(Point(lon, lat)) else "NI"


def match(case: psse.Case, candidate_frame: pd.DataFrame,
          min_kv: float = pypsa_net.TRANSMISSION_KV) -> pd.DataFrame:
    """Match every station at or above ``min_kv`` to an OSM object.

    Tried in order, and the method that succeeded is recorded on the row:

    ``alias``
        the name is in :data:`ALIASES`, resolved by hand to a named object.
        An alias is an assertion about names, so it is not second-guessed by
        the voltage check - the three HVDC converter buses are named for their
        DC voltage and would fail it every time.
    ``exact``
        normalised names are equal and the voltage tag agrees.
    ``exact-name``
        normalised names are equal and the candidate carries no voltage tag.
    ``truncated``
        the PSS/E name fills all twelve characters and is a prefix of exactly
        one candidate.  Restricted to full-width names: a short name that
        happens to start a longer one is a different station, not a truncation.
    ``prefix``
        the PSS/E name is at least six characters, is a prefix of exactly one
        candidate, and that candidate's voltage agrees.  The voltage is doing
        the work here; without it this rule is too loose to use.
    ``ni-code``
        a Northern Ireland contraction whose letters are a subsequence of
        exactly one Northern Ireland substation name at the right voltage.
    ``fuzzy``
        token-sort score of at least 92 with at least 6 points over the
        runner-up, resolving to one candidate.
    ``coupled``
        added afterwards by :func:`couple`: the bus is joined to an already
        placed bus by a zero-impedance branch, so it is the same station.

    Everything else is a failure with a reason - ``ambiguous`` where two
    candidates cannot be separated, ``weak`` where nothing scored well enough,
    ``voltage-contradicts`` where the only name match is at the wrong voltage
    class - and a failure gets no coordinate.
    """
    frame = stations(case, min_kv)
    # Two passes.  The first makes every match that needs no tie-breaking; the
    # second reruns the stations it could not place, this time knowing which
    # OSM objects the first pass took.  An object matched to one station by
    # name is not a candidate for another, and that alone settles DRUM1, whose
    # four subsequence hits include Drumkeen and Drumquin - both of which
    # TYTFS names in full elsewhere.
    first = _match_pass(frame, candidate_frame, set())
    claimed = set(first.loc[first["method"].isin(ACCEPTED), "osm"]) - {""}
    unplaced = ~first["method"].isin(ACCEPTED)
    if not unplaced.any():
        return first
    second = _match_pass(frame[unplaced.values], candidate_frame, claimed)
    out = first.copy()
    out.loc[unplaced.values, :] = second.values
    return out.reset_index(drop=True)


def _match_pass(frame: pd.DataFrame, candidate_frame: pd.DataFrame,
                claimed: set[str]) -> pd.DataFrame:
    """One matching pass over ``frame``.  See :func:`match`."""
    fuzz = _rapidfuzz()
    expanded = _expand(candidate_frame)
    by_key: dict[str, list[int]] = {}
    for _, e in expanded.iterrows():
        by_key.setdefault(e["key"], []).append(int(e["row"]))
    keys = sorted(by_key)
    ni_pool = _northern_ireland(candidate_frame)

    rows = []
    for _, s in frame.iterrows():
        key = normalise(s["station"])
        station_kv = {float(v) for v in s["kv"].split(";")}
        raw_names = s["psse_names"].split("|")
        record = {
            "station": s["station"], "buses": s["buses"],
            "bus_count": s["bus_count"], "psse_names": s["psse_names"],
            "kv": s["kv"], "jurisdiction": s["jurisdiction"],
            "osm": "", "osm_name": "", "osm_voltage_kv": "",
            "operator": "", "lat": np.nan, "lon": np.nan,
            "method": "", "score": np.nan, "runner_up": "",
            "runner_up_score": np.nan, "voltage_check": "", "note": "",
        }

        def accept(index, method, score, note="", runner=("", np.nan),
                   check_voltage=True):
            c = candidate_frame.loc[index]
            verdict, ok = _voltage_verdict(station_kv, c["voltage_kv"])
            record.update(osm=c["osm"], osm_name=c["name"],
                          osm_voltage_kv=c["voltage_kv"],
                          operator=c["operator"], lat=c["lat"], lon=c["lon"],
                          method=method, score=score, note=note,
                          voltage_check=verdict if check_voltage
                          else f"{verdict} (not applied: alias)",
                          runner_up=runner[0], runner_up_score=runner[1])
            if check_voltage and not ok:
                record.update(lat=np.nan, lon=np.nan,
                              method="voltage-contradicts",
                              note=(f"{note} - rejected: the only name match "
                                    f"is tagged {c['voltage_kv']} kV"))
            return record

        # 1. the alias table
        alias = None
        for name in [s["station"], *raw_names]:
            if name in ALIASES:
                alias = ALIASES[name]
                break
        if alias is not None:
            target, why = alias
            if not target:
                record.update(method="deliberately-unplaced", note=why)
                rows.append(dict(record))
                continue
            hit = candidate_frame.index[candidate_frame["name"] == target]
            if len(hit) == 1:
                rows.append(dict(accept(hit[0], "alias", 100.0, why,
                                        check_voltage=False)))
                continue
            record.update(method="alias-unresolved",
                          note=f"{why} - but {len(hit)} OSM objects are named "
                               f"{target!r}")
            rows.append(dict(record))
            continue

        # 2 and 3. exact on the normalised name
        exact, why = _narrow(by_key.get(key, []), candidate_frame,
                             station_kv, s["jurisdiction"], claimed)
        if len(exact) == 1:
            c = candidate_frame.loc[exact[0]]
            method = "exact" if c["voltage_kv"] else "exact-name"
            rows.append(dict(accept(exact[0], method, 100.0, why)))
            continue
        if len(exact) > 1:
            record.update(method="ambiguous", score=100.0, note=why)
            rows.append(dict(record))
            continue

        # 4 and 5. prefix, whether or not the name was truncated
        stem = normalise(max(raw_names, key=len))
        truncated = any(len(n) == 12 for n in raw_names)
        if stem and (truncated or len(stem) >= PREFIX_MIN):
            hits = sorted({i for k in keys if k.startswith(stem)
                           for i in by_key[k]})
            hits, hwhy = _narrow(hits, candidate_frame, station_kv,
                                 s["jurisdiction"], claimed)
            if len(hits) == 1:
                index = hits[0]
                agrees = _voltage_verdict(
                    station_kv,
                    candidate_frame.at[index, "voltage_kv"])[0] != "contradicts"
                if truncated:
                    rows.append(dict(accept(
                        index, "truncated", 99.0,
                        f"PSS/E fills all twelve characters with {stem!r}, a "
                        f"prefix of exactly one OSM name. {hwhy}".strip())))
                    continue
                if agrees:
                    rows.append(dict(accept(
                        index, "prefix", 98.0,
                        f"{stem!r} is a prefix of exactly one OSM name and "
                        f"the voltage agrees. {hwhy}".strip())))
                    continue
            elif len(hits) > 1:
                names = ", ".join(candidate_frame.at[i, "name"] for i in hits[:4])
                record.update(method="ambiguous", note=(
                    f"{stem!r} is a prefix of {len(hits)} OSM names: {names}"))
                rows.append(dict(record))
                continue

        # 6. Northern Ireland's contractions
        if s["jurisdiction"] == "NI":
            resolved, nwhy = _ni_code_match(key, station_kv, ni_pool,
                                            candidate_frame, claimed)
            if resolved is not None:
                rows.append(dict(accept(resolved, "ni-code", 97.0, nwhy)))
                continue
            if nwhy and "subsequence of no" not in nwhy:
                record.update(method="ambiguous", note=nwhy)
                rows.append(dict(record))
                continue
            record["note"] = nwhy

        # 7. fuzzy, with the runner-up recorded either way
        scored = sorted(((fuzz.token_sort_ratio(key, k), k) for k in keys),
                        reverse=True)
        if not scored:
            record.update(method="no-candidate",
                          note="no OSM object scored at all")
            rows.append(dict(record))
            continue
        best_score, best_key = scored[0]
        second_score, second_key = scored[1] if len(scored) > 1 else (0.0, "")
        hits, hwhy = _narrow(by_key[best_key], candidate_frame,
                             station_kv, s["jurisdiction"], claimed)
        runner = (second_key, second_score)
        if (best_score >= FUZZY_ACCEPT
                and best_score - second_score >= FUZZY_MARGIN
                and len(hits) == 1):
            rows.append(dict(accept(
                hits[0], "fuzzy", float(best_score),
                f"token-sort score {best_score:.0f} against {best_key!r}. "
                f"{hwhy}".strip(), runner)))
            continue
        if best_score < FUZZY_ACCEPT:
            why = "weak"
            note = ((record["note"] + ". " if record["note"] else "")
                    + f"best candidate {best_key!r} "
                    f"({candidate_frame.at[by_key[best_key][0], 'osm']}) "
                    f"scored {best_score:.0f}, below {FUZZY_ACCEPT}")
        elif len(hits) > 1:
            why, note = "ambiguous", (f"{best_key!r} scores "
                                      f"{best_score:.0f} but {hwhy}")
        else:
            why = "ambiguous"
            note = (f"{best_key!r} scores {best_score:.0f} and "
                    f"{second_key!r} scores {second_score:.0f} - closer than "
                    f"the {FUZZY_MARGIN}-point margin")
        record.update(method=why, score=float(best_score),
                      runner_up=runner[0], runner_up_score=runner[1],
                      note=note)
        rows.append(dict(record))
    return pd.DataFrame(rows)


def _northern_ireland(frame: pd.DataFrame) -> list[int]:
    """Candidate rows that are substations in Northern Ireland.

    Bounded by geography rather than by the operator tag, which is missing on
    a third of them: north of 54.0 N and east of 8.3 W takes in the six
    counties and clips a corner of Donegal and Monaghan, which is harmless
    here because the codes being matched are Northern Ireland's alone.
    """
    return [i for i, c in frame.iterrows()
            if c["power"] == "substation"
            and c["lat"] > 54.0 and c["lon"] > -8.3]


def _ni_code_match(key: str, station_kv: set[float], pool: list[int],
                   frame: pd.DataFrame, claimed: set[str] = frozenset()):
    """Resolve a Northern Ireland contraction, or say why it cannot be.

    Two things separate the real contraction from a coincidence.  The first is
    how tightly the letters sit: LARN is the first four letters of Larne and
    is scattered across nine of Lisnabreeny, and the tight one is the name
    being contracted.  The second is what is left: an object already matched
    to another station by name is that station's, so Drumkeen and Drumquin,
    both of which TYTFS names in full, are not candidates for DRUM1.
    """
    code = NI_CODE.match(key.replace(" ", ""))
    if not code:
        return None, ""
    letters, digit = code.group(1), code.group(2)
    expected = NI_CODE_KV[digit]
    hits = []
    for i in pool:
        if frame.at[i, "osm"] in claimed:
            continue
        spans = [_subsequence_span(letters, n.replace(" ", ""))
                 for n in str(frame.at[i, "keys"]).split(" | ")]
        spans = [x for x in spans if x is not None]
        if not spans:
            continue
        tagged = {float(v) for v in str(frame.at[i, "voltage_kv"]).split(";")
                  if v}
        if tagged and not (tagged & (station_kv | {expected})):
            continue
        hits.append((min(spans), i))
    if not hits:
        return None, (f"{letters!r} is a subsequence of no unclaimed Northern "
                      f"Ireland substation name tagged at {expected:g} kV")
    hits.sort()
    tight = [i for span, i in hits if span == hits[0][0]]
    if len(tight) == 1:
        return tight[0], (
            f"{letters!r} sits in {frame.at[tight[0], 'name']!r} within "
            f"{hits[0][0] + 1} characters, tighter than in any other Northern "
            f"Ireland substation at {expected:g} kV; the code's digit {digit} "
            "is the voltage class")
    names = ", ".join(frame.at[i, "name"] for i in tight[:5])
    return None, (f"{letters!r} sits equally tightly in {len(tight)} Northern "
                  f"Ireland substation names at {expected:g} kV: {names}")


ACCEPTED = ("alias", "exact", "exact-name", "truncated", "prefix",
            "ni-code", "ni-site", "fuzzy", "coupled")


def per_bus(matches: pd.DataFrame) -> pd.DataFrame:
    """The station-level result, expanded back to one row per bus."""
    rows = []
    for _, m in matches.iterrows():
        for bus in str(m["buses"]).split(","):
            row = {"bus": int(bus)}
            row.update({k: m[k] for k in matches.columns if k != "buses"})
            rows.append(row)
    return pd.DataFrame(rows).sort_values("bus").reset_index(drop=True)


def share_ni_sites(matches: pd.DataFrame) -> pd.DataFrame:
    """Place a Northern Ireland station from its own other voltage level.

    In the NIE naming, the letters are the site and the digit is the voltage
    class: HANA1 and HANA2 are the 110 kV and 275 kV yards of Hannahstown,
    CAST1 and CAST2 of Castlereagh, COOL1 and COOL2 of Coolkeeragh, KELS1 and
    KELS2 of Kells, BAFD1 and BAFD2 of Ballylumford.  OSM often maps only one
    of the two - Hannahstown is there at 275 kV and not at 110 kV - and the
    unmapped one is the same fence.

    So a station whose letters match a placed station's takes its coordinate,
    with the voltage class recorded as the thing that differs.  It never
    overwrites a match made on a name.
    """
    placed = {}
    for _, m in matches.iterrows():
        code = NI_CODE.match(str(m["station"]).replace(" ", ""))
        if code and m["method"] in ACCEPTED and np.isfinite(m["lat"]):
            placed.setdefault(code.group(1), m)

    out = matches.copy()
    for index, m in out.iterrows():
        if m["method"] in ACCEPTED:
            continue
        code = NI_CODE.match(str(m["station"]).replace(" ", ""))
        if not code or code.group(1) not in placed:
            continue
        twin = placed[code.group(1)]
        out.loc[index, ["lat", "lon", "osm", "osm_name", "osm_voltage_kv",
                        "operator", "method", "score", "voltage_check",
                        "note"]] = [
            twin["lat"], twin["lon"], twin["osm"], twin["osm_name"],
            twin["osm_voltage_kv"], twin["operator"], "ni-site", 94.0,
            "not applied: the two voltage classes are one site",
            (f"{code.group(1)!r} is the site and {code.group(2)!r} the voltage "
             f"class in the NIE naming; {twin['station']} is the same site, "
             f"matched to {twin['osm_name']!r}, and OSM does not map this "
             "voltage level separately")]
    return out


def couple(case: psse.Case, matches: pd.DataFrame,
           min_kv: float = pypsa_net.TRANSMISSION_KV) -> pd.DataFrame:
    """Place the buses that share a station with one already placed.

    Two kinds of connection put two buses inside the same fence, and neither
    is a name:

    A **zero-impedance branch** is a busbar coupler or a device stub.  A
    capacitor, reactor, SVC or phase-shifter bus carries a name of its own -
    MOB_CAP, CATH_CAP, PBEG REACTOR, ENNK_PST, CBAR_SVC - which no name match
    will ever reach, because it is not the name of a place.  The branch
    section says where it is.

    A **transformer** between two buses that are both at 110 kV or above is
    the station's own transformer, standing in its yard: the busbars either
    side of it are one site, whatever the case calls each of them.  That is
    what places Maynooth A's two voltage levels together, and Poolbeg North
    and South with Poolbeg.

    Both run to a fixed point, so a stub hanging off a stub is placed too, and
    neither overwrites a match made on a name.
    """
    kv = case.bus.set_index("I")["BASKV"]
    placed = {}
    for _, m in matches.iterrows():
        if m["method"] in ACCEPTED and np.isfinite(m["lat"]):
            for bus in str(m["buses"]).split(","):
                placed[int(bus)] = (m["lat"], m["lon"], m["osm"],
                                    m["osm_name"], m["station"])

    neighbours: dict[int, list[tuple[int, str]]] = {}

    def link(i: int, j: int, why: str) -> None:
        neighbours.setdefault(i, []).append((j, why))
        neighbours.setdefault(j, []).append((i, why))

    couplers = case.branch[
        (case.branch["STAT"] == 1)
        & (case.branch["X"].abs() <= pypsa_net.COUPLER_X_PU)
        & (case.branch["LEN"].fillna(0.0) == 0.0)]
    for _, b in couplers.iterrows():
        link(int(b["I"]), int(b["J"]), "a zero-impedance branch")

    for _, t in case.transformer[case.transformer["STAT"] != 0].iterrows():
        ends = [int(t["I"]), int(t["J"])]
        if int(t["WINDINGS"]) == 3:
            ends.append(int(t["K"]))
        ends = [e for e in ends if float(kv.get(e, 0.0)) >= min_kv]
        for a in range(len(ends)):
            for b in range(a + 1, len(ends)):
                link(ends[a], ends[b], "the station's own transformer")

    out = matches.copy()
    changed = True
    while changed:
        changed = False
        for index, m in out.iterrows():
            if m["method"] in ACCEPTED:
                continue
            done = False
            for bus in (int(b) for b in str(m["buses"]).split(",")):
                for other, why in neighbours.get(bus, []):
                    if other not in placed:
                        continue
                    lat, lon, osm, osm_name, station = placed[other]
                    out.loc[index, ["lat", "lon", "osm", "osm_name",
                                    "method", "score", "voltage_check",
                                    "note"]] = [
                        lat, lon, osm, osm_name, "coupled", 95.0,
                        "not applied: placed from a neighbour",
                        (f"bus {bus} is joined to bus {other} ({station}) by "
                         f"{why}, so it is inside the same station")]
                    for b in str(m["buses"]).split(","):
                        placed[int(b)] = (lat, lon, osm, osm_name,
                                          m["station"])
                    changed = done = True
                    break
                if done:
                    break
    return out


# --------------------------------------------------------------------------- #
# Cross-check
#
# The matching has one source and one join key, so it can be confidently
# wrong.  EirGrid publishes its own station layer with names and coordinates,
# and this repo already holds it: 161 stations at 110 kV and above, in
# data/eirgrid_transmission.gpkg.  Where a matched station is in that layer
# too, the two coordinates should be the same place.
# --------------------------------------------------------------------------- #

EIRGRID_GPKG = "data/eirgrid_transmission.gpkg"


def crosscheck(matches: pd.DataFrame, gpkg: str = EIRGRID_GPKG
               ) -> pd.DataFrame:
    """Compare each accepted match against EirGrid's own station coordinates."""
    import geopandas as gpd

    stations_gdf = gpd.read_file(gpkg, layer="stations").to_crs(4326)
    stations_gdf["key"] = [normalise(n) for n in stations_gdf["name"]]
    by_key = {}
    for _, row in stations_gdf.iterrows():
        by_key.setdefault(row["key"], (row.geometry.y, row.geometry.x))

    rows = []
    for _, m in matches.iterrows():
        if m["method"] not in ACCEPTED or not np.isfinite(m["lat"]):
            continue
        key = normalise(m["station"])
        if key not in by_key:
            continue
        lat, lon = by_key[key]
        km = _haversine_km(m["lat"], m["lon"], lat, lon)
        rows.append({"station": m["station"], "method": m["method"],
                     "osm": m["osm"], "osm_name": m["osm_name"],
                     "osm_lat": m["lat"], "osm_lon": m["lon"],
                     "eirgrid_lat": lat, "eirgrid_lon": lon,
                     "distance_km": km, "agrees": km <= CROSSCHECK_KM})
    return pd.DataFrame(rows).sort_values("distance_km", ascending=False)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def report(matches: pd.DataFrame, checks: pd.DataFrame | None = None) -> None:
    """Print the per-station confidence breakdown and every failure."""
    buses = per_bus(matches)
    placed = matches["method"].isin(ACCEPTED)
    print(f"\n{len(matches)} stations, {len(buses)} buses at "
          f"{pypsa_net.TRANSMISSION_KV:g} kV and above")
    print(f"{placed.sum()} stations placed ({placed.sum() / len(matches):.1%}), "
          f"{buses['method'].isin(ACCEPTED).sum()} buses "
          f"({buses['method'].isin(ACCEPTED).mean():.1%})")

    print("\nBy method")
    counts = matches.groupby("method").agg(
        stations=("station", "size"), buses=("bus_count", "sum"))
    order = list(ACCEPTED) + sorted(set(counts.index) - set(ACCEPTED))
    for method in order:
        if method in counts.index:
            mark = "placed " if method in ACCEPTED else "FAILED "
            print(f"  {mark} {method:<22} {counts.at[method, 'stations']:>4} "
                  f"stations  {counts.at[method, 'buses']:>4} buses")

    if placed.any():
        print("\nVoltage corroboration, over the placed stations")
        for verdict, n in matches[placed]["voltage_check"].value_counts().items():
            print(f"  {verdict:<40} {n:>4}")

    failures = matches[~placed]
    print(f"\nEvery failure ({len(failures)} stations, "
          f"{failures['bus_count'].sum()} buses)")
    if failures.empty:
        print("  none")
    for _, f in failures.sort_values(["method", "station"]).iterrows():
        print(f"  {f['station']:<16} {f['kv']:>10} kV  {f['method']:<22} "
              f"buses {f['buses']}")
        if f["note"]:
            print(f"      {f['note']}")

    if checks is not None and len(checks):
        bad = checks[~checks["agrees"]]
        print(f"\nCross-check against EirGrid's own station register: "
              f"{len(checks)} stations in both")
        print(f"  median separation {checks['distance_km'].median():.2f} km, "
              f"95th percentile {checks['distance_km'].quantile(0.95):.2f} km, "
              f"worst {checks['distance_km'].max():.2f} km")
        print(f"  {len(bad)} more than {CROSSCHECK_KM:g} km apart")
        for _, b in bad.iterrows():
            print(f"    {b['station']:<16} {b['distance_km']:>7.1f} km  "
                  f"OSM {b['osm_name']!r} ({b['osm']})")


# --------------------------------------------------------------------------- #
# Putting the coordinates onto a network
# --------------------------------------------------------------------------- #

def apply_to(model, matches: pd.DataFrame):
    """Write the matched coordinates onto a built network's buses.

    PyPSA holds bus coordinates in ``x`` and ``y``, longitude and latitude.  A
    bus with no accepted match keeps the NaN it was built with: an unplaced
    bus stays unplaced rather than being dropped or moved to the mean of its
    neighbours.
    """
    placed = per_bus(matches)
    placed = placed[placed["method"].isin(ACCEPTED)]
    lon = dict(zip(placed["bus"].astype(str), placed["lon"]))
    lat = dict(zip(placed["bus"].astype(str), placed["lat"]))
    network = model.network
    network.buses["x"] = [lon.get(b, np.nan) for b in network.buses.index]
    network.buses["y"] = [lat.get(b, np.nan) for b in network.buses.index]
    network.buses["geocode_method"] = [
        dict(zip(placed["bus"].astype(str), placed["method"])).get(b, "")
        for b in network.buses.index]
    return model


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

DEFAULT_CASE = "data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw"


def load_candidates(path: str = CANDIDATES_PATH) -> pd.DataFrame:
    """The committed candidate table, or build it from the cached download."""
    if os.path.exists(path):
        return pd.read_csv(path, keep_default_na=False,
                           na_values=[""]).fillna({"voltage_kv": "",
                                                   "operator": "",
                                                   "keys": "", "names": ""})
    with open(RAW_PATH) as fh:
        return candidates(json.load(fh))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="download from Overpass into data/raw/")
    sub.add_parser("candidates", help=f"distil the download into "
                                      f"{CANDIDATES_PATH}")
    for cmd in ("match", "report"):
        s = sub.add_parser(cmd, help="match the buses and report")
        s.add_argument("paths", nargs="*", default=[DEFAULT_CASE])
        s.add_argument("--min-kv", type=float,
                       default=pypsa_net.TRANSMISSION_KV)
    args = p.parse_args(argv)

    if args.cmd == "fetch":
        payload = fetch()
        print(f"{len(payload['elements'])} elements -> {RAW_PATH}")
        return 0
    if args.cmd == "candidates":
        with open(RAW_PATH) as fh:
            frame = candidates(json.load(fh))
        frame.to_csv(CANDIDATES_PATH, index=False)
        print(f"{len(frame)} named OSM objects -> {CANDIDATES_PATH}")
        return 0

    frame = load_candidates()
    for path in args.paths:
        case = psse.read_raw(path)
        matches = match(case, frame, args.min_kv)
        matches = couple(case, share_ni_sites(matches), args.min_kv)
        try:
            checks = crosscheck(matches)
        except Exception as exc:                            # noqa: BLE001
            print(f"(cross-check unavailable: {type(exc).__name__}: {exc})")
            checks = None
        if args.cmd == "match":
            os.makedirs(GEOCODING_DIR, exist_ok=True)
            out = os.path.join(GEOCODING_DIR, f"{case.name}.csv")
            per_bus(matches).to_csv(out, index=False)
            if checks is not None:
                checks.to_csv(os.path.join(
                    GEOCODING_DIR, f"{case.name}_crosscheck.csv"), index=False)
            print(f"\n{case.name}: {len(matches)} stations -> {out}")
        report(matches, checks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
