#!/usr/bin/env python3
"""
fetch_acs_components.py
==========================
Pull the raw ACS component indicators behind the Purdue Digital Divide Index
(DDI) so we can run a sensitivity analysis that swaps the composite for its
parts. See DDI/ and 04_tract_ddi_profile.py.

Indicators (census-tract, newest ACS 5-year):
    no_internet  B28002 | no_computer  B28003 | age_65plus  B01001
    lt_highschool B15003 | poverty  B17001 | disability  B18101
The Internet Income Ratio is intentionally NOT reproduced (income bands do not
match PCRD's <$35k / >=$75k cut points).

Output -> ./ACS/acs5_<year>_tract_ddi_components.csv (+ per-table raw files).
GEOID is an 11-digit string; read with dtype={"GEOID": str}.

RUN
    pip install pandas certifi
    export CENSUS_API_KEY=xxxx     # optional, free: https://api.census.gov/data/key_signup.html
    python fetch_acs_components.py

If you are behind a network that inspects SSL (common on campus) and still get
certificate errors after installing certifi, you can bypass verification:
    export ACS_INSECURE=1
    python fetch_acs_components.py
"""

import os
import re
import ssl
import sys
import json
import time
import urllib.request
import urllib.error
import pandas as pd

API_KEY = os.environ.get("CENSUS_API_KEY", "").strip()
INSECURE = os.environ.get("ACS_INSECURE", "").strip() == "1"
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT_DIR, "ACS")
os.makedirs(OUT_DIR, exist_ok=True)

# --- Build one SSL context, preferring certifi's up-to-date CA bundle --------
def _make_ctx():
    if INSECURE:
        print("  WARNING: ACS_INSECURE=1 -> SSL certificate verification is OFF.")
        return ssl._create_unverified_context()
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

_CTX = _make_ctx()
_UA = {"User-Agent": "cards-digital-readiness/1.0 (research; +https://github.com/CarDS-Yale)"}


def _get(url, quiet=False):
    """GET JSON with a real User-Agent, the chosen SSL context, and retries.
    Reads the raw body so a non-JSON response (e.g. an unreleased year) is shown."""
    full = url + (("&" if "?" in url else "?") + "key=" + API_KEY if API_KEY else "")
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(full, headers=_UA)
            with urllib.request.urlopen(req, timeout=120, context=_CTX) as r:
                raw = r.read()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                body = raw.decode("utf-8", "replace").strip()
                raise RuntimeError(f"non-JSON response ({len(raw)} bytes): {body[:200]!r}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except Exception as e:
            last = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"request failed: {url}\n    -> {type(last).__name__}: {last}")


def newest_acs5_year():
    errors = []
    for yr in range(2024, 2018, -1):
        try:
            d = _get(f"https://api.census.gov/data/{yr}/acs/acs5?get=NAME&for=state:01", quiet=True)
            if isinstance(d, list) and len(d) > 1:
                return yr
            errors.append(f"{yr}: unexpected response shape")
        except urllib.error.HTTPError as e:
            errors.append(f"{yr}: HTTP {e.code} (not yet published)")
        except Exception as e:
            errors.append(f"{yr}: {type(e).__name__}: {str(e)[:80]}")
    detail = "\n    ".join(errors)
    raise RuntimeError(
        "Could not reach the Census ACS 5-year API. Underlying attempts:\n    "
        + detail
        + "\n\n  If these are SSL certificate errors: `pip install certifi`, or on a "
          "campus network set `export ACS_INSECURE=1` and rerun."
    )


def table_vars(year, table):
    meta = _get(f"https://api.census.gov/data/{year}/acs/acs5/groups/{table}.json")
    # keep only real estimate variables for THIS table (excludes NAME, GEO_ID, etc.)
    return {c: v["label"] for c, v in meta["variables"].items()
            if c.startswith(table + "_") and c.endswith("E")}


AGE65_TOKENS = ("65 and 66 years", "67 to 69 years", "70 to 74 years",
                "75 to 79 years", "80 to 84 years", "85 years and over")

def numerator_codes(table, vars_map):
    denom = f"{table}_001E"
    num = []
    for code, label in vars_map.items():
        if code == denom:
            continue
        if table == "B28002" and label.endswith("With an Internet subscription"):
            num.append(code)   # complement below -> households with NO subscription
        elif table == "B28003" and label.endswith("No computer"):
            num.append(code)
        elif table == "B17001" and label.endswith("below poverty level:"):
            num.append(code)
        elif table == "B18101" and label.endswith("With a disability"):
            num.append(code)
        elif table == "B01001" and any(tok in label for tok in AGE65_TOKENS):
            num.append(code)
        elif table == "B15003":
            m = re.match(r"^B15003_(\d+)E$", code)
            if m and 2 <= int(m.group(1)) <= 16:
                num.append(code)
    return denom, sorted(set(num))


COMPLEMENT = {"no_internet"}   # count = total households - "with an Internet subscription"

INDICATORS = {
    "no_internet": "B28002", "no_computer": "B28003", "poverty": "B17001",
    "disability": "B18101", "age_65plus": "B01001", "lt_highschool": "B15003",
}
EXPECTED = {
    "no_internet": (0.09, 0.20), "no_computer": (0.03, 0.10), "poverty": (0.09, 0.16),
    "disability": (0.10, 0.16), "age_65plus": (0.13, 0.20), "lt_highschool": (0.07, 0.16),
}


def pull_table(year, table, denom, nums):
    getvars = ",".join(["NAME", denom] + nums)
    base = f"https://api.census.gov/data/{year}/acs/acs5"
    try:
        print("        trying nationwide (for=tract:* in=state:*) ...", flush=True)
        rows = _get(f"{base}?get={getvars}&for=tract:*&in=state:*")
    except Exception as e:
        print(f"        wildcard not available ({type(e).__name__}); looping states ...", flush=True)
        states = _get(f"{base}?get=NAME&for=state:*")
        codes = sorted(r[1] for r in states[1:] if r[1] != "72")
        rows = None
        for i, st in enumerate(codes, 1):
            part = _get(f"{base}?get={getvars}&for=tract:*&in=state:{st}")
            rows = part if rows is None else rows + part[1:]
            print(f"          state {st} ({i}/{len(codes)})", flush=True)
            time.sleep(0.2)
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df = df[df["state"] != "72"]
    df["GEOID"] = df["state"].str.zfill(2) + df["county"].str.zfill(3) + df["tract"].str.zfill(6)
    for c in [denom] + nums:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def main():
    print(f"[1/3] Probing for newest ACS 5-year release (secure={not INSECURE}, key={'yes' if API_KEY else 'no'}) ...", flush=True)
    year = newest_acs5_year()
    print(f"      -> using {year}", flush=True)

    combined = None
    for name, table in INDICATORS.items():
        vmap = table_vars(year, table)
        denom, nums = numerator_codes(table, vmap)
        if not nums:
            sys.exit(f"ERROR: no numerator variables matched for {name} ({table}).")
        print(f"[2/3] {name:14s} {table}: denom={denom} numerator_vars={len(nums)}", flush=True)
        df = pull_table(year, table, denom, nums)
        matched = df[nums].sum(axis=1)
        count = (df[denom] - matched) if name in COMPLEMENT else matched
        out = pd.DataFrame({
            "GEOID": df["GEOID"],
            f"{name}_count": count,
            f"{name}_denom": df[denom],
            f"{name}_pct": (count / df[denom]).where(df[denom] > 0),
        })
        out.to_csv(os.path.join(OUT_DIR, f"acs5_{year}_tract_raw_{table}.csv"), index=False)
        nat = count.sum() / df[denom].sum()
        lo, hi = EXPECTED[name]
        print(f"        national share = {nat:6.3f}  expected {lo}-{hi}  {'OK' if lo <= nat <= hi else '!! CHECK'}", flush=True)
        combined = out if combined is None else combined.merge(out, on="GEOID", how="outer")

    combined = combined.sort_values("GEOID").reset_index(drop=True)
    path = os.path.join(OUT_DIR, f"acs5_{year}_tract_ddi_components.csv")
    combined.to_csv(path, index=False)
    print(f"[3/3] Wrote {len(combined):,} tracts x {combined.shape[1]} cols -> {path}", flush=True)


if __name__ == "__main__":
    main()
