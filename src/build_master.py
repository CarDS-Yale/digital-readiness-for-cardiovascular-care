"""
Builds the cached tract-level master table that every other script reads.

Joins cardiometabolic burden, the Digital Divide Index and its subscores, and
the county workforce summary into one row per census tract, then records the
national anchors used for classification. Running this once keeps the 19 MB
Divide Index workbook and the high-need pool derivation out of every
downstream script, so the whole suite shares a single data path.

Also defines the logic reused throughout:
  matrix_boxes()   the 2x2 classification, applied to any readiness measure
  rank_eligible()  drops single-measure-burden states from ranked lists
  compare_runs()   box agreement, retention and top-N overlap versus a baseline

Outputs (outputs/master/)
  tract_master.csv   one row per tract with burden, readiness, flags
  anchors.csv        national medians and pool counts, single row

Run this before anything else; downstream scripts refuse to start without the
cache so results stay consistent.
"""
import os
import numpy as np
import pandas as pd

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V1_OUT = os.path.join(PROJECT_DIR, "outputs")
V3_OUT = os.path.join(V1_OUT, "burden_workforce")
OUT_DIR = os.path.join(V1_OUT, "master")
os.makedirs(OUT_DIR, exist_ok=True)

BURDEN_FILE = os.path.join(V3_OUT, "burden_tracts.csv")
WF_FILE     = os.path.join(V3_OUT, "county_workforce_summary.csv")
WF_TREND_V1 = os.path.join(V1_OUT, "ahrf_workforce_trend_summary.csv")
DDI_FILE    = os.path.join(PROJECT_DIR, "DDI", "2022-2024 US DDI.xlsx")
GEO_FILE    = os.path.join(PROJECT_DIR, "AHRF",
                           "NCHWA-2024-2025+AHRF+COUNTY+CSV", "AHRF2025geo.csv")

MASTER_FILE  = os.path.join(OUT_DIR, "tract_master.csv")
ANCHORS_FILE = os.path.join(OUT_DIR, "anchors.csv")


def build_master():
    burden = pd.read_csv(BURDEN_FILE, dtype={"fips_tract": str, "fips_county": str})
    burden["fips_tract"] = burden["fips_tract"].str.zfill(11)
    burden["fips_county"] = burden["fips_county"].str.zfill(5)

    ddi = pd.read_excel(DDI_FILE, sheet_name="Tracts 22", dtype={"FIPS": str})
    ddi["FIPS"] = ddi["FIPS"].str.zfill(11)
    nat_med_ddi  = float(ddi["DDI"].median())
    nat_med_infa = float(ddi["INFA"].median())
    nat_med_se   = float(ddi["SE"].median())
    ddi = ddi.rename(columns={"FIPS": "fips_tract", "DDI": "ddi",
                              "SE": "se", "INFA": "infa"})
    ddi["ddi_pct_nat"] = (ddi["ddi"].rank(pct=True) * 100).round(1)
    ddi = ddi[["fips_tract", "ddi", "se", "infa", "ddi_pct_nat"]]

    wf = pd.read_csv(WF_FILE, dtype={"fips_st_cnty": str})
    wf["fips_st_cnty"] = wf["fips_st_cnty"].str.zfill(5)
    wt = pd.read_csv(WF_TREND_V1, dtype={"fips_st_cnty": str})
    wt["fips_st_cnty"] = wt["fips_st_cnty"].str.zfill(5)
    wf = wf.merge(wt[["fips_st_cnty", "workforce_slope", "workforce_slope_pc"]],
                  on="fips_st_cnty", how="left")

    # combined high-need pool (per-capita decline rule)
    no_card = wf["card_last"] == 0
    has = wf["card_last"] > 0
    dec_ols = wf["workforce_slope_pc"].notna() & (wf["workforce_slope_pc"] < 0)
    dec_small = (wf["mean_card_dis"] < 3) & (wf["card_per_100k_last"] < wf["card_per_100k_first"])
    declining = has & (dec_ols | dec_small)
    wf["pool_nocard"] = no_card
    wf["pool_declining"] = declining
    wf["in_pool"] = no_card | declining

    geo = pd.read_csv(GEO_FILE, low_memory=False)
    geo.columns = [c.strip('"').strip() for c in geo.columns]
    geo["fips_st_cnty"] = geo["fips_st_cnty"].astype(str).str.zfill(5)
    names = geo[["fips_st_cnty", "cnty_name_st_abbrev", "st_name_abbrev"]].rename(
        columns={"cnty_name_st_abbrev": "county_state", "st_name_abbrev": "state_abbr"})

    keep_wf = ["fips_st_cnty", "card_last", "card_per_100k_last",
               "county_pop_last", "mean_card_dis", "workforce_slope_pc",
               "pool_nocard", "pool_declining", "in_pool"]
    tracts = (burden
              .merge(ddi, on="fips_tract", how="left")
              .merge(wf[keep_wf], left_on="fips_county", right_on="fips_st_cnty", how="left")
              .drop(columns=["fips_st_cnty"])
              .merge(names, left_on="fips_county", right_on="fips_st_cnty", how="left")
              .drop(columns=["fips_st_cnty"])
              .drop_duplicates("fips_tract"))
    tracts[["pool_nocard", "pool_declining", "in_pool"]] = (
        tracts[["pool_nocard", "pool_declining", "in_pool"]].fillna(False))

    anchors = {
        "nat_med_ddi": round(nat_med_ddi, 4),
        "nat_med_infa": round(nat_med_infa, 4),
        "nat_med_se": round(nat_med_se, 4),
        "n_counties_pool": int(wf["in_pool"].sum()),
        "n_counties_nocard": int(wf["pool_nocard"].sum()),
        "n_counties_declining": int(wf["pool_declining"].sum()),
        "n_tracts_master": len(tracts),
        "n_tracts_pool": int(tracts["in_pool"].sum()),
    }
    return tracts, anchors


def load_master():
    """Downstream entry point: read the cached master + anchors."""
    if not (os.path.exists(MASTER_FILE) and os.path.exists(ANCHORS_FILE)):
        raise SystemExit("master cache missing. Run build_master.py first.")
    tracts = pd.read_csv(MASTER_FILE, dtype={"fips_tract": str, "fips_county": str})
    tracts["fips_tract"] = tracts["fips_tract"].str.zfill(11)
    tracts["fips_county"] = tracts["fips_county"].str.zfill(5)
    anchors = pd.read_csv(ANCHORS_FILE).iloc[0].to_dict()
    return tracts, anchors


def matrix_boxes(pool_df, ready_col, ready_cut, burden_cut=0.0):
    """2x2 classification on any readiness column (higher = worse). Returns (inv, dep)."""
    d = pool_df.dropna(subset=["burden_z", ready_col]).drop_duplicates("fips_tract").copy()
    d["high_burden"] = d["burden_z"] > burden_cut
    d["ready"] = d[ready_col] <= ready_cut
    zb = (d["burden_z"] - d["burden_z"].mean()) / d["burden_z"].std()
    zr = (d[ready_col] - d[ready_col].mean()) / d[ready_col].std()
    d["deploy_score"] = zb - zr
    d["invest_score"] = zb + zr
    inv = (d[d["high_burden"] & ~d["ready"]]
           .sort_values("invest_score", ascending=False).reset_index(drop=True))
    dep = (d[d["high_burden"] & d["ready"]]
           .sort_values("deploy_score", ascending=False).reset_index(drop=True))
    inv.insert(0, "rank", inv.index + 1)
    dep.insert(0, "rank", dep.index + 1)
    return inv, dep


# States whose PLACES burden rests on a single measure (short sleep) because
# CDC suppressed the other 9 measures for insufficient BRFSS collection. Their
# tracts keep box membership and counts but are ineligible for the ranked
# national top-N lists, where a 1-measure composite cannot be compared against
# a 10-measure one. See sens_burden_kypa and sens_burden_kypa_crosswalk.
RANK_EXCLUDE_STATES = ("21", "42")   # KY, PA


def rank_eligible(df):
    """Drop single-measure-burden states from a ranked frame (for top-N lists).

    Box counts and membership use the full frame; only ranked/top-N displays
    call this. Re-ranks 1..n after the drop so 'rank' stays contiguous.
    """
    st = df["fips_tract"].astype(str).str.zfill(11).str[:2]
    out = df[~st.isin(RANK_EXCLUDE_STATES)].reset_index(drop=True)
    if "rank" in out.columns:
        out["rank"] = out.index + 1
    return out


def box_label(df, inv, dep):
    """Label each row of df as INVEST / DEPLOY / other under a given run."""
    s = pd.Series("other", index=df.index)
    s.loc[df["fips_tract"].isin(inv["fips_tract"])] = "INVEST"
    s.loc[df["fips_tract"].isin(dep["fips_tract"])] = "DEPLOY"
    return s


def top_overlap(a, b, n):
    """Overlap of the top-n fips_tract lists of two ranked frames."""
    return len(set(a["fips_tract"].head(n)) & set(b["fips_tract"].head(n)))


def compare_runs(df, inv_ref, dep_ref, inv_new, dep_new):
    """Standard comparison block: box sizes, agreement, top-N overlap."""
    ref = box_label(df, inv_ref, dep_ref)
    new = box_label(df, inv_new, dep_new)
    out = {
        "n_invest_ref": len(inv_ref), "n_deploy_ref": len(dep_ref),
        "n_invest_new": len(inv_new), "n_deploy_new": len(dep_new),
        "box_agree_pct": round((ref == new).mean() * 100, 1),
        "invest_retained_pct": round((new[ref == "INVEST"] == "INVEST").mean() * 100, 1),
        "deploy_retained_pct": round((new[ref == "DEPLOY"] == "DEPLOY").mean() * 100, 1),
    }
    for n in (10, 50, 100):
        out[f"inv_top{n}_overlap"] = top_overlap(inv_ref, inv_new, n)
        out[f"dep_top{n}_overlap"] = top_overlap(dep_ref, dep_new, n)
    return out


def state_mix(ranked, n=None):
    """State composition of a ranked box (share of tracts by state)."""
    d = ranked if n is None else ranked.head(n)
    return (d["state_abbr"].value_counts(normalize=True).mul(100)
            .round(1).rename("pct"))


TIDY_COLS = ["rank", "fips_tract", "county_state", "state_abbr", "burden_z",
             "burden_pct", "ddi", "se", "infa", "ddi_pct_nat",
             "invest_score", "deploy_score", "card_last"]


def tidy(df, extra=None):
    cols = TIDY_COLS + (extra or [])
    out = df[[c for c in cols if c in df.columns]].copy()
    for c in out.columns:
        if out[c].dtype == float:
            out[c] = out[c].round(3)
    return out


def main():
    print("=" * 70)
    print("building the cached tract master table")
    print("=" * 70)
    tracts, anchors = build_master()
    tracts.to_csv(MASTER_FILE, index=False)
    pd.DataFrame([anchors]).to_csv(ANCHORS_FILE, index=False)
    for k, v in anchors.items():
        print(f"  {k}: {v}")

    # sanity check: replicate the published box sizes from the cache
    P = tracts[tracts["in_pool"]]
    inv, dep = matrix_boxes(P, "ddi", anchors["nat_med_ddi"])
    print(f"\nreplication check: INVEST {len(inv):,} (expect 21,752) | "
          f"DEPLOY {len(dep):,} (expect 4,765)")
    print(f"cache -> {MASTER_FILE}")


if __name__ == "__main__":
    main()
