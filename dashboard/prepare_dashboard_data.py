"""
prepare_dashboard_data.py
=========================
Prepare data files for the public dashboard. Outputs to dashboard/data/:

  counties.geojson  – county GeoJSON with all analytic properties merged into
                      feature.properties (workforce, burden, DDI, quadrant,
                      population, etc.). Source: user-provided
                      geojson-counties-fips.json.

  county_data.json  – JSON object keyed by 5-digit county FIPS; full per-county
                      analytic record (separate from geometry to allow lookup
                      without re-parsing the geojson).

  tract_data.json   – Two-level JSON: { fips_county: { fips_tract: {…} } }.
                      Allows the dashboard to fetch all tracts in a county in
                      one lookup when the user clicks a county.
"""

import os
import json
import pandas as pd
import numpy as np

PROJECT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR   = os.path.join(PROJECT_DIR, "outputs")
DASH_DATA    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DASH_DATA, exist_ok=True)

COUNTY_GEOJSON  = os.path.join(PROJECT_DIR, "geojson-counties-fips.json")
COUNTY_ANALYTIC = os.path.join(OUTPUT_DIR,  "county_analytic_dataset.csv")
TRACT_ANALYTIC  = os.path.join(OUTPUT_DIR,  "tract_analytic_dataset.csv")
AHRF_PANEL      = os.path.join(OUTPUT_DIR,  "ahrf_card_dis_panel_2010_2023.csv")
GEO_FILE        = os.path.join(PROJECT_DIR, "AHRF",
                               "NCHWA-2024-2025+AHRF+COUNTY+CSV",
                               "AHRF2025geo.csv")


# =============================================================================
# 1. Load all sources
# =============================================================================

print("[1/5] Loading sources...")

with open(COUNTY_GEOJSON, "r") as f:
    counties_gj = json.load(f)
print(f"  counties geojson: {len(counties_gj['features']):,} features")

county = pd.read_csv(COUNTY_ANALYTIC, dtype={"fips_st_cnty": str}, low_memory=False)
county["fips_st_cnty"] = county["fips_st_cnty"].str.zfill(5)
print(f"  county analytic dataset: {len(county):,} rows")

tract = pd.read_csv(TRACT_ANALYTIC,
                    dtype={"fips_tract": str, "fips_st_cnty": str},
                    low_memory=False)
tract["fips_tract"]   = tract["fips_tract"].str.zfill(11)
tract["fips_st_cnty"] = tract["fips_st_cnty"].str.zfill(5)
print(f"  tract analytic dataset: {len(tract):,} rows")

# Latest-year cardiologist count (2023) from the AHRF panel
panel = pd.read_csv(AHRF_PANEL, dtype={"fips_st_cnty": str}, low_memory=False)
panel["fips_st_cnty"] = panel["fips_st_cnty"].str.zfill(5)
latest_year = panel["year"].max()
latest = (panel[panel["year"] == latest_year]
          [["fips_st_cnty", "md_nf_card_dis",
            "card_per_100k_year", "county_pop_year",
            "workforce_aging_share_ge55"]]
          .rename(columns={
              "md_nf_card_dis":             "cards_latest",
              "card_per_100k_year":         "cards_per_100k_latest",
              "county_pop_year":            "county_pop_latest",
              "workforce_aging_share_ge55": "aging_share_latest",
          }))
print(f"  latest year (panel): {int(latest_year)}; rows: {len(latest):,}")

# County name / state from AHRF geo
geo = pd.read_csv(GEO_FILE, low_memory=False)
geo.columns = [c.strip('"').strip() for c in geo.columns]
geo["fips_st_cnty"] = geo["fips_st_cnty"].astype(str).str.zfill(5)
geo_sub = geo[["fips_st_cnty", "cnty_name", "st_name", "st_name_abbrev",
               "cbsa_name_23", "rural_urban_contnm_23"]].rename(columns={
    "cnty_name": "county_name",
    "st_name": "state_name",
    "st_name_abbrev": "state_abbr",
    "cbsa_name_23": "cbsa_name",
    "rural_urban_contnm_23": "rural_urban_code",
})


# =============================================================================
# 2. Build the per-county analytic record
# =============================================================================

print("\n[2/5] Building per-county analytic record...")

# Round numeric columns sensibly for compact JSON
def round_num(x, n=2):
    if pd.isna(x):
        return None
    if isinstance(x, (int, np.integer)):
        return int(x)
    return round(float(x), n)

county_full = (county
    .merge(geo_sub,  on="fips_st_cnty", how="left", suffixes=("", "__g"))
    .merge(latest,   on="fips_st_cnty", how="left"))

# Keep only the columns we want exposed in the dashboard
KEEP = [
    "fips_st_cnty",
    "county_name", "state_name", "state_abbr", "cbsa_name", "rural_urban_code",
    # Workforce
    "cards_latest", "cards_per_100k_latest", "aging_share_latest",
    "mean_card_dis", "n_years_available",
    "workforce_slope", "workforce_pct_chg", "workforce_trend",
    "card_first", "card_last", "first_year", "last_year",
    # Burden (county rollup)
    "burden_slope", "burden_z_first", "burden_z_last", "burden_z_delta",
    "burden_trend", "n_tracts_burden",
    # Population
    "county_pop_latest",
    # DDI (county mean over its tracts)
    "n_tracts", "mean_ddi_se", "mean_ddi_infa", "mean_ddi_composite",
    "digital_readiness_tier",
    # Combined
    "quadrant", "composite_risk_score",
]
have = [c for c in KEEP if c in county_full.columns]
county_full = county_full[have].copy()

# Compact numeric rounding
NUM_COLS = [
    "cards_per_100k_latest", "aging_share_latest", "mean_card_dis",
    "workforce_slope", "workforce_pct_chg",
    "burden_slope", "burden_z_first", "burden_z_last", "burden_z_delta",
    "mean_ddi_se", "mean_ddi_infa", "mean_ddi_composite",
    "composite_risk_score",
]
for c in NUM_COLS:
    if c in county_full.columns:
        county_full[c] = county_full[c].apply(lambda v: round_num(v, 3))

# Integer-coerce where appropriate
INT_COLS = ["cards_latest", "n_years_available", "first_year", "last_year",
            "n_tracts", "n_tracts_burden", "county_pop_latest",
            "rural_urban_code", "card_first", "card_last"]
for c in INT_COLS:
    if c in county_full.columns:
        county_full[c] = county_full[c].apply(
            lambda v: int(v) if pd.notna(v) else None)


# =============================================================================
# 3. Merge analytic record into county GeoJSON features
# =============================================================================

print("\n[3/5] Merging analytics into county GeoJSON...")

# Build lookup: fips → record
lookup = {row["fips_st_cnty"]: {k: row[k] for k in have}
          for _, row in county_full.iterrows()}

n_matched = 0
for feat in counties_gj["features"]:
    fips = str(feat.get("id", "")).zfill(5)
    rec = lookup.get(fips)
    if rec is None:
        # No analytic data – fill with empty fields the JS can detect as null
        feat["properties"] = {"fips_st_cnty": fips,
                              "county_name": feat.get("properties", {}).get("NAME"),
                              "quadrant": None}
    else:
        # Replace properties with our analytic record
        clean = {k: (v if not (isinstance(v, float) and pd.isna(v)) else None)
                 for k, v in rec.items()}
        # Also preserve the geojson NAME if present
        if "NAME" in (feat.get("properties") or {}):
            clean.setdefault("county_name_geo", feat["properties"]["NAME"])
        feat["properties"] = clean
        n_matched += 1
    # Keep id as 5-char zero-padded string for MapLibre feature-state matching
    feat["id"] = fips

print(f"  matched {n_matched:,} / {len(counties_gj['features']):,} county features")

geojson_path = os.path.join(DASH_DATA, "counties.geojson")
with open(geojson_path, "w") as f:
    json.dump(counties_gj, f, separators=(",", ":"))
print(f"  wrote {geojson_path}  ({os.path.getsize(geojson_path)/1024/1024:.2f} MB)")


# =============================================================================
# 4. Tract data JSON (grouped by parent county)
# =============================================================================

print("\n[4/5] Building tract data JSON (grouped by parent county)...")

TRACT_KEEP = [
    "fips_tract", "fips_st_cnty",
    "burden_slope", "burden_z_first", "burden_z_last", "burden_z_delta",
    "burden_trend", "n_years_burden",
    "ddi_se", "ddi_infa", "ddi_composite", "digital_readiness_tier",
    "workforce_trend", "workforce_slope", "mean_card_dis",
    "quadrant", "composite_risk_score",
]
tract_have = [c for c in TRACT_KEEP if c in tract.columns]
tract_slim = tract[tract_have].copy()

TRACT_NUM = ["burden_slope", "burden_z_first", "burden_z_last", "burden_z_delta",
             "ddi_se", "ddi_infa", "ddi_composite",
             "workforce_slope", "mean_card_dis", "composite_risk_score"]
for c in TRACT_NUM:
    if c in tract_slim.columns:
        tract_slim[c] = tract_slim[c].apply(lambda v: round_num(v, 3))

TRACT_INT = ["n_years_burden"]
for c in TRACT_INT:
    if c in tract_slim.columns:
        tract_slim[c] = tract_slim[c].apply(
            lambda v: int(v) if pd.notna(v) else None)

tract_by_county: dict = {}
for fips_c, grp in tract_slim.groupby("fips_st_cnty"):
    rows = {}
    for _, r in grp.iterrows():
        rec = {k: (None if (isinstance(r[k], float) and pd.isna(r[k]))
                   else r[k]) for k in tract_have}
        rows[rec["fips_tract"]] = rec
    tract_by_county[fips_c] = rows

tract_path = os.path.join(DASH_DATA, "tract_data.json")
with open(tract_path, "w") as f:
    json.dump(tract_by_county, f, separators=(",", ":"), default=str)
print(f"  wrote {tract_path}  ({os.path.getsize(tract_path)/1024/1024:.2f} MB)")
print(f"  counties indexed: {len(tract_by_county):,}")
print(f"  total tracts:     {sum(len(v) for v in tract_by_county.values()):,}")


# =============================================================================
# 5. Stand-alone county lookup JSON (faster than parsing geojson properties)
# =============================================================================

print("\n[5/5] Writing county_data.json lookup...")

county_lookup = {}
for _, r in county_full.iterrows():
    rec = {k: (None if (isinstance(r[k], float) and pd.isna(r[k])) else r[k])
           for k in have}
    county_lookup[rec["fips_st_cnty"]] = rec

cl_path = os.path.join(DASH_DATA, "county_data.json")
with open(cl_path, "w") as f:
    json.dump(county_lookup, f, separators=(",", ":"), default=str)
print(f"  wrote {cl_path}  ({os.path.getsize(cl_path)/1024/1024:.2f} MB)")

print("\n✓ Dashboard data prep complete.")
