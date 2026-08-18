"""
build_burden_and_workforce.py
============================
Builds the tract burden composite and the county workforce summary that the
rest of the pipeline reads. Writes everything under outputs/burden_workforce/.

Burden is treated as a level, not a trend
-----------------------------------------
- CDC PLACES is treated as POINT-IN-TIME (mean of 2022 and 2023), not a trend.
  Two years of PLACES data isn't enough to fit a defensible trend, so we
  just use the level — average across the two observed years per tract per
  measure, then build a composite z-score across measures.

Pipeline
--------
For each tract:
  prevalence_avg(i, m) = mean( prevalence(i, m, 2022), prevalence(i, m, 2023) )
  z(i, m)              = ( prevalence_avg(i, m) − μ(m) ) / σ(m)
                         (z-score across all tracts)
  burden_z(i)          = mean over m of z(i, m)
  burden_rank(i)       = national rank by burden_z, 1 = highest burden

For each county:
  card_last  = cardiologist count in 2023 (or latest observed AHRF year)
  card_first = cardiologist count in 2010 (or first observed AHRF year)
  per_100k_last  = card_last / county_pop_last  × 100,000
  per_100k_first = card_first / county_pop_first × 100,000

Then split into TWO groups:
  Group A — NO CARDIOLOGISTS now:  counties with card_last == 0
  Group B — DECLINING WORKFORCE:   counties with card_last > 0 AND
                                   (workforce_slope < 0 if mean ≥ 3,
                                    OR card_last < card_first if mean < 3)

Within each group, rank constituent tracts by burden_z nationally and
report the top tracts with parent-county context + DDI ranking & tier.

DDI ranking convention
----------------------
The Digital Divide Index runs 0-100, HIGHER = greater divide = LOWER readiness.
For each tract:
  ddi_rank     = rank where 1 = lowest DDI (best readiness)
  ddi_pct      = percentile rank in [0, 100]
  ddi_tier     = "Top tier (best readiness, deploy)"     if DDI ≤ p33
                 "Middle tier"                           if p33 < DDI ≤ p66
                 "Bottom tier (worst readiness, invest)" if DDI > p66

Outputs
-------
outputs/burden_workforce/
  burden_tracts.csv       Per-tract burden composite + national rank
  county_workforce_summary.csv         Per-county card_first/last (counts + per-100k)
  table1_no_cardiologists_top_tracts.csv          Group A, top 50 tracts
  table2_declining_workforce_top20_tracts.csv     Group B, top 20 tracts
  README.md                             Methodology + tables in markdown
"""

import os
import numpy as np
import pandas as pd

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V1_OUT      = os.path.join(PROJECT_DIR, "outputs")
OUT_DIR     = os.path.join(V1_OUT, "burden_workforce")
os.makedirs(OUT_DIR, exist_ok=True)

PANEL_FILE   = os.path.join(V1_OUT, "ahrf_card_dis_panel_2010_2023.csv")
PLACES_FILE  = os.path.join(V1_OUT, "cdc_places_cv_tract_long.csv")
DDI_FILE     = os.path.join(PROJECT_DIR, "DDI", "2022-2024 US DDI.xlsx")
GEO_FILE     = os.path.join(PROJECT_DIR, "AHRF",
                            "NCHWA-2024-2025+AHRF+COUNTY+CSV",
                            "AHRF2025geo.csv")
WF_TREND_V1  = os.path.join(V1_OUT, "ahrf_workforce_trend_summary.csv")

TABLE1_N = 50    # top-N tracts in counties-with-no-cardiologists table
TABLE2_N = 20    # top-N tracts in declining-workforce table


# =============================================================================
# 1. PER-COUNTY workforce summary (first/last year, count + per-100k)
# =============================================================================

def summarise_county_workforce(panel: pd.DataFrame) -> pd.DataFrame:
    """For each county, return first/last year counts + per-100k rates."""
    p = panel.copy()
    p = p.dropna(subset=["md_nf_card_dis"])
    p = p.sort_values(["fips_st_cnty", "year"])
    grp = p.groupby("fips_st_cnty")

    def _first(s): return s.iloc[0]  if len(s) else np.nan
    def _last(s):  return s.iloc[-1] if len(s) else np.nan

    out = grp.agg(
        n_years          = ("year", "count"),
        first_year       = ("year", _first),
        last_year        = ("year", _last),
        card_first       = ("md_nf_card_dis", _first),
        card_last        = ("md_nf_card_dis", _last),
        card_per_100k_first = ("card_per_100k_year", _first),
        card_per_100k_last  = ("card_per_100k_year", _last),
        mean_card_dis    = ("md_nf_card_dis", "mean"),
        county_pop_first = ("county_pop_year", _first),
        county_pop_last  = ("county_pop_year", _last),
    ).reset_index()
    return out


# =============================================================================
# 2. PLACES point-in-time tract burden composite
# =============================================================================

def compute_point_in_time_burden(places: pd.DataFrame) -> pd.DataFrame:
    """
    Average each measure's prevalence across years per tract,
    z-score across tracts per measure, average across measures = composite.
    """
    df = places.copy()
    df = df.dropna(subset=["prevalence"])
    # Average across years per (tract, measure)
    avg = (df.groupby(["fips", "fips_county", "measure_id"], as_index=False)
             .agg(prevalence_avg=("prevalence", "mean"),
                  n_years=("year", "nunique")))

    # Z-score across tracts within measure
    avg["z"] = (avg.groupby("measure_id")["prevalence_avg"]
                 .transform(lambda s: (s - s.mean()) / s.std(ddof=0)))

    # Average z across measures → composite per tract
    composite = (avg.groupby(["fips", "fips_county"], as_index=False)
                   .agg(burden_z=("z", "mean"),
                        measures_observed=("measure_id", "nunique")))
    composite["burden_z"] = composite["burden_z"].round(4)
    # National rank by burden (1 = highest burden)
    composite["burden_rank"] = composite["burden_z"].rank(
        method="dense", ascending=False).astype(int)
    composite["burden_pct"]  = (composite["burden_z"].rank(pct=True) * 100).round(1)
    composite = composite.rename(columns={"fips": "fips_tract"})
    return composite


# =============================================================================
# 3. DDI lookup w/ national rank + tier
# =============================================================================

def load_ddi_with_rank(path: str) -> pd.DataFrame:
    ddi = pd.read_excel(path, dtype={"FIPS": str})
    ddi["FIPS"] = ddi["FIPS"].str.zfill(11)
    ddi = ddi.rename(columns={"FIPS": "fips_tract",
                              "SE": "ddi_se", "INFA": "ddi_infa", "DDI": "ddi"})
    ddi["fips_county"] = ddi["fips_tract"].str[:5]

    # Lower DDI = better readiness → rank 1 is lowest DDI
    ddi["ddi_rank"] = ddi["ddi"].rank(method="dense", ascending=True).astype(int)
    ddi["ddi_pct"]  = (ddi["ddi"].rank(pct=True) * 100).round(1)
    p33, p66 = ddi["ddi"].quantile([1/3, 2/3])
    def tier(v):
        if pd.isna(v): return None
        if v <= p33:   return "Top tier (best readiness, deploy)"
        if v <= p66:   return "Middle tier"
        return "Bottom tier (worst readiness, invest)"
    ddi["ddi_tier"] = ddi["ddi"].apply(tier)
    ddi["ddi"] = ddi["ddi"].round(2)
    return ddi[["fips_tract", "fips_county", "ddi", "ddi_rank", "ddi_pct", "ddi_tier"]]


# =============================================================================
# 4. County name lookup
# =============================================================================

def load_county_names(path: str) -> pd.DataFrame:
    geo = pd.read_csv(path, low_memory=False)
    geo.columns = [c.strip('"').strip() for c in geo.columns]
    geo["fips_st_cnty"] = geo["fips_st_cnty"].astype(str).str.zfill(5)
    return geo[["fips_st_cnty", "cnty_name", "st_name_abbrev",
                "cnty_name_st_abbrev"]].rename(columns={
        "cnty_name": "county_name",
        "st_name_abbrev": "state_abbr",
        "cnty_name_st_abbrev": "county_state",
    })


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 70)
    print("Point-in-time PLACES burden + county workforce summary")
    print("=" * 70)

    # ── 1. AHRF panel and county workforce summary ─────────────────────
    print("\n[1/5] Loading AHRF panel and summarising per-county workforce...")
    panel = pd.read_csv(PANEL_FILE, dtype={"fips_st_cnty": str}, low_memory=False)
    panel["fips_st_cnty"] = panel["fips_st_cnty"].str.zfill(5)
    cnty_wf = summarise_county_workforce(panel)
    cnty_wf.to_csv(os.path.join(OUT_DIR, "county_workforce_summary.csv"),
                    index=False)
    print(f"  counties: {len(cnty_wf):,}")
    print(f"  first/last year span:  "
          f"{int(cnty_wf['first_year'].min())} → {int(cnty_wf['last_year'].max())}")
    print(f"  counties with card_last == 0:  {(cnty_wf['card_last']==0).sum():,}")
    print(f"  counties with card_last  > 0:  {(cnty_wf['card_last']>0).sum():,}")

    # Bring in the OLS workforce slope (for the "declining ≥3" path)
    wf_v1 = pd.read_csv(WF_TREND_V1, dtype={"fips_st_cnty": str})
    wf_v1["fips_st_cnty"] = wf_v1["fips_st_cnty"].str.zfill(5)
    cnty_wf = cnty_wf.merge(wf_v1[["fips_st_cnty", "workforce_slope",
                                     "workforce_slope_pc", "workforce_trend"]],
                              on="fips_st_cnty", how="left",
                              suffixes=("", "_v1"))

    # ── 2. PLACES burden composite (point-in-time) ─────────────────────
    print("\n[2/5] Computing PLACES point-in-time burden composite per tract...")
    places = pd.read_csv(PLACES_FILE,
                         dtype={"fips": str, "fips_county": str},
                         low_memory=False)
    places["fips"]        = places["fips"].str.zfill(11)
    places["fips_county"] = places["fips_county"].str.zfill(5)
    print(f"  PLACES rows: {len(places):,}; tracts: {places['fips'].nunique():,}")
    print(f"  years used: {sorted(places['year'].unique().tolist())}")

    burden = compute_point_in_time_burden(places)
    print(f"  tracts with composite: {len(burden):,}")
    print(f"  burden_z distribution: "
          f"min {burden['burden_z'].min():.2f}, "
          f"median {burden['burden_z'].median():.2f}, "
          f"max {burden['burden_z'].max():.2f}")
    burden.to_csv(os.path.join(OUT_DIR, "burden_tracts.csv"),
                   index=False)

    # ── 3. DDI + county names ─────────────────────────────────────────
    print("\n[3/5] Loading DDI and county names...")
    ddi = load_ddi_with_rank(DDI_FILE)
    names = load_county_names(GEO_FILE)
    print(f"  DDI tracts: {len(ddi):,}  "
          f"tiers — top: {(ddi['ddi_tier'].str.startswith('Top')).sum():,}, "
          f"middle: {(ddi['ddi_tier'].str.startswith('Middle')).sum():,}, "
          f"bottom: {(ddi['ddi_tier'].str.startswith('Bottom')).sum():,}")

    # Merge tract burden + DDI + parent county summary + county name
    tracts = (burden
              .merge(ddi.drop(columns=["fips_county"]), on="fips_tract", how="left")
              .merge(cnty_wf, left_on="fips_county", right_on="fips_st_cnty", how="left")
              .merge(names,  left_on="fips_county", right_on="fips_st_cnty", how="left"))
    print(f"  merged tract rows: {len(tracts):,}")

    # ── 4. Define the two county groups ───────────────────────────────
    print("\n[4/5] Defining county groups...")
    # Group A: NO cardiologists in latest year
    group_a = cnty_wf[cnty_wf["card_last"] == 0]["fips_st_cnty"].tolist()

    # Group B: WITH cardiologists in latest year AND declining workforce
    has_cards = cnty_wf["card_last"] > 0
    # Decline rule A: OLS slope <0 (mean ≥3 path)
    decline_ols = (cnty_wf["workforce_slope_pc"].notna()
                   & (cnty_wf["workforce_slope_pc"] < 0))
    # Decline rule B: small-county counties (mean <3) whose per-capita rate fell
    decline_small = ((cnty_wf["mean_card_dis"] < 3)
                     & (cnty_wf["card_per_100k_last"] < cnty_wf["card_per_100k_first"]))
    declining = has_cards & (decline_ols | decline_small)
    group_b = cnty_wf[declining]["fips_st_cnty"].tolist()

    print(f"  Group A (no cardiologists 2023):       {len(group_a):,} counties")
    print(f"  Group B (with cards & declining):      {len(group_b):,} counties")
    print(f"     of which classified by OLS rule:    {decline_ols.sum():,}")
    print(f"     of which classified by small rule:  {decline_small.sum():,}")
    overlap = set(group_a) & set(group_b)
    print(f"  Overlap (should be 0):                 {len(overlap)}")

    # ── 5. Build the two ranked tables ────────────────────────────────
    print("\n[5/5] Building Table 1 and Table 2...")

    # Common display columns
    base_cols = ["burden_rank", "fips_tract", "county_state",
                 "burden_z", "burden_pct",
                 "ddi", "ddi_rank", "ddi_pct", "ddi_tier"]

    # Table 1 — Group A, ranked by burden (highest first)
    t1 = (tracts[tracts["fips_county"].isin(group_a)]
            .sort_values("burden_z", ascending=False)
            .reset_index(drop=True))
    t1["group_rank"] = t1.index + 1
    t1 = t1[["group_rank"] + base_cols]
    table1_path = os.path.join(OUT_DIR, "table1_no_cardiologists_top_tracts.csv")
    t1.to_csv(table1_path, index=False)
    print(f"  Table 1 — {len(t1):,} tracts in {len(group_a):,} no-card counties → top {TABLE1_N}")
    print(f"  ✓ {table1_path}")

    # Table 2 — Group B, ranked by burden (highest first), top 20
    t2 = (tracts[tracts["fips_county"].isin(group_b)]
            .sort_values("burden_z", ascending=False)
            .reset_index(drop=True))
    t2["group_rank"] = t2.index + 1
    t2 = t2[["group_rank"] + base_cols
             + ["card_per_100k_first", "card_per_100k_last",
                "card_first", "card_last",
                "first_year", "last_year"]]
    table2_path = os.path.join(OUT_DIR, "table2_declining_workforce_top20_tracts.csv")
    t2.head(200).to_csv(table2_path, index=False)   # save 200 for flexibility
    print(f"  Table 2 — {len(t2):,} tracts in {len(group_b):,} declining-workforce counties → top {TABLE2_N}")
    print(f"  ✓ {table2_path}")

    # ── PRINT THE TABLES (top N each) ─────────────────────────────────
    print("\n" + "═" * 100)
    print(f"TABLE 1 — Top {TABLE1_N} census tracts in counties with ZERO cardiologists (2023)")
    print(f"          Ranked by national CV burden composite z-score (avg 2022-2023, point-in-time)")
    print("═" * 100)
    t1_display = t1.head(TABLE1_N).copy()
    t1_display["fips_tract"] = t1_display["fips_tract"].astype(str)
    print(t1_display.to_string(index=False))

    print("\n" + "═" * 100)
    print(f"TABLE 2 — Top {TABLE2_N} census tracts in counties WITH cardiologists & DECLINING workforce")
    print(f"          Ranked by national CV burden composite z-score")
    print("═" * 100)
    t2_display = t2.head(TABLE2_N).copy()
    t2_display["fips_tract"] = t2_display["fips_tract"].astype(str)
    for col in ["card_per_100k_first", "card_per_100k_last"]:
        t2_display[col] = t2_display[col].round(2)
    print(t2_display.to_string(index=False))

    print("\n✓ Done. See outputs/burden_workforce/ for full ranked CSVs.")


if __name__ == "__main__":
    main()
