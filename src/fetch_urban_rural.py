#!/usr/bin/env python3
"""
fetch_urban_rural.py
=======================
Pull the urban/rural reference data needed to describe the priority groups:

  1. NCHS Urban-Rural Classification Scheme for Counties (1990/2006/2013/2023)
     county-level; the convention in the health services literature
     -> GEO/nchs_urban_rural_county.csv

  2. 2020 Census urban/rural population, table P2, at census-tract level
     2020-vintage tracts, so it joins our master directly with no crosswalk
     -> GEO/census2020_tract_urban_rural.csv

Table P2 of the 2020 DHC also carries total tract population, saved alongside
as an independent check on the ACS population weights.

A CENSUS API KEY IS REQUIRED. The 2020 DHC endpoint rejects unauthenticated
requests with "Missing Key" (returned as HTML, not JSON). Free, instant:
    https://api.census.gov/data/key_signup.html

Per-state Census responses are cached under GEO/_census_cache/, so an
interrupted run resumes where it left off instead of restarting.

RUN (on a machine with internet)
    cd path/to/digital-readiness
    export CENSUS_API_KEY=xxxxxxxx
    .venv/bin/python fetch_urban_rural.py

Needs only requests + pandas (both already in the project venv).
"""
import os
import sys
import time

import numpy as np
import pandas as pd
import requests

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT_DIR, "GEO")
CACHE_DIR = os.path.join(OUT_DIR, "_census_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

NCHS_CSV = os.path.join(OUT_DIR, "nchs_urban_rural_county.csv")
TRACT_CSV = os.path.join(OUT_DIR, "census2020_tract_urban_rural.csv")

API_KEY = os.environ.get("CENSUS_API_KEY", "").strip()
DHC = "https://api.census.gov/data/2020/dec/dhc"

# P2 confirmed as "URBAN AND RURAL" in the 2020 DHC group list:
#   P2_001N total | P2_002N urban | P2_003N rural
VARS = ["P2_001N", "P2_002N", "P2_003N"]

# 50 states + DC; territories are outside the analysis.
STATES = [f"{s:02d}" for s in range(1, 57) if s not in (3, 7, 14, 43, 52)]

# Current NCHS distribution: one CSV holding all vintages.
NCHS_URL = "https://www.cdc.gov/nchs/data/data-analysis/NCHSurb-rural-codes.csv"
NCHS_LOCAL = os.path.join(OUT_DIR, "NCHSurb-rural-codes.csv")

NCHS_LABELS = {
    1: "Large central metro",
    2: "Large fringe metro",
    3: "Medium metro",
    4: "Small metro",
    5: "Micropolitan",
    6: "Noncore (rural)",
}


# ── 1. NCHS county classification ───────────────────────────────────────────
def fetch_nchs():
    if os.path.exists(NCHS_CSV):
        print(f"[nchs]  cached -> {NCHS_CSV}")
        return

    raw = None
    if os.path.exists(NCHS_LOCAL):
        print(f"[nchs]  using local copy {NCHS_LOCAL}")
        raw = open(NCHS_LOCAL, "rb").read()
    else:
        try:
            print(f"[nchs]  downloading {NCHS_URL}")
            r = requests.get(NCHS_URL, timeout=120, headers={
                "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/124.0 Safari/537.36"),
                "Accept": "text/csv,*/*"})
            r.raise_for_status()
            raw = r.content
            with open(NCHS_LOCAL, "wb") as f:
                f.write(raw)
        except Exception as e:                                   # noqa: BLE001
            print(f"[nchs]  download failed: {type(e).__name__}: {e}")
            print("\n" + "=" * 72)
            print("[nchs]  DOWNLOAD BLOCKED - do this once, manually:")
            print("  1. Open https://www.cdc.gov/nchs/data-analysis-tools/"
                  "urban-rural.html")
            print("  2. Download 'NCHS Urban-Rural codes (1990, 2006, 2013 "
                  "and 2023)' (.csv)")
            print(f"  3. Save it as: {NCHS_LOCAL}")
            print("  4. Re-run this script")
            print("=" * 72 + "\n")
            return

    df = pd.read_csv(pd.io.common.BytesIO(raw), dtype=str,
                     encoding_errors="replace")
    print(f"[nchs]  columns: {list(df.columns)}")

    low = {c.lower().strip(): c for c in df.columns}

    def find(*frags, exclude=()):
        for lc, orig in low.items():
            if all(f in lc for f in frags) and not any(x in lc for x in exclude):
                return orig
        return None

    # NCHS ships state and county FIPS in SEPARATE columns (STFIPS, CTYFIPS).
    # Matching a bare "fips" would grab STFIPS alone and yield 00001 instead
    # of 01001, so resolve the two-column form first.
    st_col = find("stfips") or find("state", "fips")
    cty_col = (find("ctyfips") or find("cty", "fips")
               or find("county", "fips") or find("cnty", "fips"))
    combined_col = find("fips", exclude=("st", "cty", "cnty", "state",
                                         "county")) or find("geoid")

    code_2023 = find("2023")
    code_2013 = find("2013")

    if code_2023 is None and code_2013 is None:
        raise SystemExit(
            f"[nchs]  no urban-rural code column in {list(df.columns)}")

    def digits(col, width):
        return df[col].astype(str).str.extract(r"(\d+)")[0].str.zfill(width)

    if st_col and cty_col:
        fips = digits(st_col, 2) + digits(cty_col, 3)
        print(f"[nchs]  FIPS from {st_col} + {cty_col}")
    elif combined_col:
        fips = digits(combined_col, 5)
        print(f"[nchs]  FIPS from {combined_col}")
    else:
        raise SystemExit(
            f"[nchs]  could not identify FIPS columns in {list(df.columns)}")

    out = pd.DataFrame({"fips_st_cnty": fips})
    for label, col in [("nchs_code_2023", code_2023), ("nchs_code_2013", code_2013)]:
        if col is not None:
            out[label] = pd.to_numeric(df[col], errors="coerce")

    # primary = most recent vintage available
    primary = "nchs_code_2023" if code_2023 is not None else "nchs_code_2013"
    out["nchs_code"] = out[primary]
    out = out.dropna(subset=["nchs_code"])
    out["nchs_code"] = out["nchs_code"].astype(int)
    out["nchs_label"] = out["nchs_code"].map(NCHS_LABELS)
    out = out.drop_duplicates("fips_st_cnty").sort_values("fips_st_cnty")

    # guard: a county file must have ~3,100+ rows and real 5-digit FIPS.
    # Catches the STFIPS-only failure mode, which collapsed to ~56 rows.
    if len(out) < 2500 or (out["fips_st_cnty"].str[:2] == "00").any():
        raise SystemExit(
            f"[nchs]  parsed only {len(out):,} counties - FIPS assembly looks "
            f"wrong.\n        sample: {out['fips_st_cnty'].head(3).tolist()}\n"
            f"        source columns: {list(df.columns)}")

    out.to_csv(NCHS_CSV, index=False)
    print(f"[nchs]  {len(out):,} counties (primary vintage: {primary}) "
          f"-> {NCHS_CSV}")
    print(out["nchs_label"].value_counts().to_string())


# ── 2. Census 2020 tract urban/rural (DHC table P2) ─────────────────────────
def fetch_state(st):
    """One state's tracts, cached to disk so runs resume."""
    cache = os.path.join(CACHE_DIR, f"{st}.csv")
    if os.path.exists(cache):
        return pd.read_csv(cache, dtype=str)

    params = [("get", ",".join(VARS)), ("for", "tract:*"),
              ("in", f"state:{st}"), ("in", "county:*"), ("key", API_KEY)]

    for attempt in (1, 2, 3):
        try:
            r = requests.get(DHC, params=params, timeout=180)
            if r.status_code == 204:
                pd.DataFrame().to_csv(cache, index=False)
                return pd.DataFrame()
            if not r.text.lstrip().startswith("["):
                # Census returns HTML/plain text for errors; surface it
                raise ValueError(
                    f"non-JSON response ({r.status_code}): "
                    f"{r.text.strip()[:200]}")
            rows = r.json()
            df = pd.DataFrame(rows[1:], columns=rows[0])
            df.to_csv(cache, index=False)
            return df
        except Exception as e:                                   # noqa: BLE001
            print(f"[census] {st}: attempt {attempt} failed "
                  f"({type(e).__name__}: {e})")
            if attempt == 3:
                raise SystemExit(
                    f"[census] giving up on state {st}. Completed states are "
                    f"cached in {CACHE_DIR}; fix the issue and re-run to "
                    "resume.")
            time.sleep(3 * attempt)


def fetch_tracts():
    if os.path.exists(TRACT_CSV):
        print(f"[census] cached -> {TRACT_CSV}")
        return

    if not API_KEY:
        raise SystemExit(
            "\n[census] CENSUS_API_KEY is not set, and the 2020 DHC endpoint "
            "rejects\n         unauthenticated requests ('Missing Key').\n\n"
            "  Get one free and instantly at:\n"
            "      https://api.census.gov/data/key_signup.html\n\n"
            "  Then:\n"
            "      export CENSUS_API_KEY=xxxxxxxx\n"
            "      .venv/bin/python fetch_urban_rural.py\n")

    frames = []
    for i, st in enumerate(STATES, 1):
        df = fetch_state(st)
        frames.append(df)
        print(f"[census] {st}: {len(df):,} tracts   ({i}/{len(STATES)})")

    d = pd.concat([f for f in frames if len(f)], ignore_index=True)
    d["GEOID"] = (d["state"].str.zfill(2) + d["county"].str.zfill(3)
                  + d["tract"].str.zfill(6))
    for v in VARS:
        d[v] = pd.to_numeric(d[v], errors="coerce")

    out = pd.DataFrame({
        "GEOID": d["GEOID"],
        "pop_total_2020": d[VARS[0]],
        "pop_urban_2020": d[VARS[1]],
        "pop_rural_2020": d[VARS[2]],
    })
    # plain float math; pd.NA has no __round__, so keep this in numpy space
    tot = out["pop_total_2020"].astype("float64")
    urb = out["pop_urban_2020"].astype("float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = np.where(tot > 0, urb / tot * 100.0, np.nan)
    out["pct_urban"] = np.round(pct, 1)
    out["urban_flag"] = np.where(np.isnan(pct), None,
                                 np.where(pct >= 50, "Urban", "Rural"))
    out = out.drop_duplicates("GEOID").sort_values("GEOID")

    out.to_csv(TRACT_CSV, index=False)
    print(f"\n[census] {len(out):,} tracts -> {TRACT_CSV}")
    print(f"[census] total 2020 population: {out['pop_total_2020'].sum():,.0f}")
    print(out["urban_flag"].value_counts(dropna=False).to_string())


def main():
    print("=" * 72)
    print("urban/rural reference data for the priority-group summaries")
    print("=" * 72)
    fetch_nchs()
    print()
    fetch_tracts()
    print("\ndone. next:  .venv/bin/python make_table1.py")


if __name__ == "__main__":
    sys.exit(main())
