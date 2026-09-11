"""
prepare_priority_layers.py
====================
Augment the dashboard data files with the **priority matrix targeting** layer,
the framing the manuscript uses (build_master.py).

It injects ``priority_*`` fields into:

  dashboard/data/counties.geojson   (feature.properties)
  dashboard/data/county_data.json   (per-county lookup)
  dashboard/data/tract_data.json    (per-tract records, grouped by county)

It also writes a compact:

  dashboard/data/priority_summary.json    national KPI figures + top-N leaderboards

Run AFTER prepare_dashboard_data.py (and prepare_metric_extras.py):

    cd dashboard
    python prepare_dashboard_data.py
    python prepare_metric_extras.py
    python prepare_priority_layers.py

Method (mirrors build_master.py and the manuscript)
---------------------------------------------------------
High-need county pool = union of
    (a) counties with NO cardiologists in the latest panel year, and
    (b) counties with a DECLINING PER-CAPITA cardiology workforce
        (OLS slope of cardiologists per 100k < 0; small counties with
        mean < 3 use last-vs-first rate).

Within the pool, two anchored cuts form a 2x2 matrix:
    high burden : burden_z > 0 (above the national-average tract)
    ready       : DDI <= national median (18.77)

    DEPLOY = high burden and ready       (4,765 tracts)
    INVEST = high burden and not ready   (21,752 tracts)

The boxes are disjoint; there is no "both" bucket in priority.
"""

import os
import json
import pandas as pd
import numpy as np

DASH_DIR    = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(DASH_DIR)
OUT_DIR     = os.path.join(PROJECT_DIR, "outputs")
DATA_DIR    = os.path.join(DASH_DIR, "data")
V3_OUT      = os.path.join(OUT_DIR, "burden_workforce")
PRIORITY_OUT      = os.path.join(OUT_DIR, "master")

WF_FILE       = os.path.join(V3_OUT, "county_workforce_summary.csv")
WF_TREND_FILE = os.path.join(OUT_DIR, "ahrf_workforce_trend_summary.csv")
DEPLOY_FILE   = os.path.join(PRIORITY_OUT, "priority_DEPLOY_ranked.csv")
INVEST_FILE   = os.path.join(PRIORITY_OUT, "priority_INVEST_ranked.csv")
THRESH_FILE   = os.path.join(PRIORITY_OUT, "priority_thresholds.csv")

# States whose PLACES tract burden rests on a single measure (short sleep).
# They keep box membership and counts but are ineligible for the ranked
# national top-N lists (mirrors build_master.RANK_EXCLUDE_STATES).
RANK_EXCLUDE_STATES = ("21", "42")   # KY, PA


def rank_eligible(df):
    """Drop single-measure-burden states and re-rank 1..n contiguously."""
    st = df["fips_tract"].astype(str).str.zfill(11).str[:2]
    out = df[~st.isin(RANK_EXCLUDE_STATES)].reset_index(drop=True)
    out["rank"] = out.index + 1
    return out


# =============================================================================
# 1. Reproduce the per-capita high-need pool (identical to build_master)
# =============================================================================
def build_pool():
    wf = pd.read_csv(WF_FILE, dtype={"fips_st_cnty": str})
    wf["fips_st_cnty"] = wf["fips_st_cnty"].str.zfill(5)

    wf_t = pd.read_csv(WF_TREND_FILE, dtype={"fips_st_cnty": str})
    wf_t["fips_st_cnty"] = wf_t["fips_st_cnty"].str.zfill(5)
    wf = wf.merge(wf_t[["fips_st_cnty", "workforce_slope_pc"]],
                  on="fips_st_cnty", how="left")

    no_card       = wf["card_last"] == 0
    has_cards     = wf["card_last"] > 0
    decline_ols   = wf["workforce_slope_pc"].notna() & (wf["workforce_slope_pc"] < 0)
    decline_small = ((wf["mean_card_dis"] < 3)
                     & (wf["card_per_100k_last"] < wf["card_per_100k_first"]))
    declining     = has_cards & (decline_ols | decline_small)

    wf["priority_in_pool"] = no_card | declining
    wf["priority_pool_reason"] = np.where(
        no_card, "no_cardiologist",
        np.where(declining, "declining_workforce", None))

    pool = wf[wf["priority_in_pool"]].copy()
    reason = dict(zip(pool["fips_st_cnty"], pool["priority_pool_reason"]))
    print(f"[1] High-need pool: {len(pool):,} counties "
          f"({int(no_card.sum()):,} no-cardiologist + "
          f"{int(declining.sum()):,} declining per capita)")
    return set(pool["fips_st_cnty"]), reason


# =============================================================================
# 2. DEPLOY / INVEST tract tags from the published priority ranked tables
# =============================================================================
def load_bucket_tags():
    dep = pd.read_csv(DEPLOY_FILE, dtype={"fips_tract": str})
    inv = pd.read_csv(INVEST_FILE, dtype={"fips_tract": str})
    dep["fips_tract"] = dep["fips_tract"].str.zfill(11)
    inv["fips_tract"] = inv["fips_tract"].str.zfill(11)

    deploy_rank = dict(zip(dep["fips_tract"], dep["rank"].astype(int)))
    invest_rank = dict(zip(inv["fips_tract"], inv["rank"].astype(int)))
    dep_bz  = dict(zip(dep["fips_tract"], dep["burden_z"]))
    dep_ddi = dict(zip(dep["fips_tract"], dep["ddi"]))
    inv_bz  = dict(zip(inv["fips_tract"], inv["burden_z"]))
    inv_ddi = dict(zip(inv["fips_tract"], inv["ddi"]))
    dep_sc  = dict(zip(dep["fips_tract"], dep["deploy_score"]))
    inv_sc  = dict(zip(inv["fips_tract"], inv["invest_score"]))

    overlap = set(deploy_rank) & set(invest_rank)
    assert not overlap, f"priority boxes must be disjoint; found {len(overlap)} overlaps"

    # Ranked lists exclude KY/PA and re-rank; membership dicts keep everyone.
    dep_e = rank_eligible(dep)
    inv_e = rank_eligible(inv)
    deploy_rank_e = dict(zip(dep_e["fips_tract"], dep_e["rank"].astype(int)))
    invest_rank_e = dict(zip(inv_e["fips_tract"], inv_e["rank"].astype(int)))
    print(f"[2] DEPLOY tracts: {len(deploy_rank):,} ({len(deploy_rank_e):,} ranked)   "
          f"INVEST tracts: {len(invest_rank):,} ({len(invest_rank_e):,} ranked)")
    return {
        "deploy_rank": deploy_rank, "invest_rank": invest_rank,
        "deploy_rank_e": deploy_rank_e, "invest_rank_e": invest_rank_e,
        "dep_bz": dep_bz, "dep_ddi": dep_ddi, "inv_bz": inv_bz, "inv_ddi": inv_ddi,
        "dep_sc": dep_sc, "inv_sc": inv_sc,
        "deploy_df": dep, "invest_df": inv,
        "deploy_df_e": dep_e, "invest_df_e": inv_e,
    }


def tract_bucket(tfips, county_in_pool, tags):
    if tfips in tags["deploy_rank"]:
        return "deploy"
    if tfips in tags["invest_rank"]:
        return "invest"
    if county_in_pool:
        return "pool_other"
    return None


# =============================================================================
# 3. Augment tract_data.json (inject priority_*, strip v5_*)
# =============================================================================
def augment_tracts(pool, tags):
    path = os.path.join(DATA_DIR, "tract_data.json")
    with open(path) as f:
        tract_by_county = json.load(f)

    counts = {}
    n_tract = 0
    for fips_c, tracts in tract_by_county.items():
        in_pool = fips_c in pool
        c = {"deploy": 0, "invest": 0, "pool_other": 0}
        for tfips, rec in tracts.items():
            for k in [k for k in rec if k.startswith("v5_")]:
                del rec[k]
            b = tract_bucket(tfips, in_pool, tags)
            rec["priority_bucket"] = b
            rec["priority_single_measure"] = tfips[:2] in RANK_EXCLUDE_STATES
            # ranks are the KY/PA-excluded contiguous ranks; None for KY/PA
            rec["priority_deploy_rank"] = tags["deploy_rank_e"].get(tfips)
            rec["priority_invest_rank"] = tags["invest_rank_e"].get(tfips)
            rec["priority_burden_z"] = tags["dep_bz"].get(tfips, tags["inv_bz"].get(tfips))
            rec["priority_ddi"]      = tags["dep_ddi"].get(tfips, tags["inv_ddi"].get(tfips))
            rec["priority_score"]    = tags["dep_sc"].get(tfips, tags["inv_sc"].get(tfips))
            if b in c:
                c[b] += 1
            n_tract += 1
        counts[fips_c] = c

    with open(path, "w") as f:
        json.dump(tract_by_county, f, separators=(",", ":"), default=str)
    print(f"[3] tract_data.json augmented ({n_tract:,} tracts)")
    return counts


# =============================================================================
# 4. County-level roll-up class
# =============================================================================
def county_class(fips, in_pool, reason, counts):
    if not in_pool:
        return {"priority_in_pool": False, "priority_pool_reason": None,
                "priority_n_deploy": 0, "priority_n_invest": 0, "priority_county_class": None}
    c = counts.get(fips, {"deploy": 0, "invest": 0})
    nd, ni = c.get("deploy", 0), c.get("invest", 0)
    if nd > 0 and ni > 0:
        cls = "mixed"
    elif nd > 0:
        cls = "deploy_lean"
    elif ni > 0:
        cls = "invest_lean"
    else:
        cls = "high_need_other"
    return {"priority_in_pool": True, "priority_pool_reason": reason.get(fips),
            "priority_n_deploy": int(nd), "priority_n_invest": int(ni),
            "priority_county_class": cls}


def augment_counties(pool, reason, counts):
    cd_path = os.path.join(DATA_DIR, "county_data.json")
    with open(cd_path) as f:
        cd = json.load(f)
    classes = {}
    for fips, rec in cd.items():
        for k in [k for k in rec if k.startswith("v5_")]:
            del rec[k]
        cc = county_class(fips, fips in pool, reason, counts)
        rec.update(cc)
        classes[fips] = cc
    with open(cd_path, "w") as f:
        json.dump(cd, f, separators=(",", ":"), default=str)

    gj_path = os.path.join(DATA_DIR, "counties.geojson")
    with open(gj_path) as f:
        gj = json.load(f)
    for feat in gj["features"]:
        fips = str(feat.get("id", "")).zfill(5)
        props = feat.setdefault("properties", {})
        for k in [k for k in props if k.startswith("v5_")]:
            del props[k]
        cc = classes.get(fips) or county_class(fips, fips in pool, reason, counts)
        props.update(cc)
    with open(gj_path, "w") as f:
        json.dump(gj, f, separators=(",", ":"))

    n_pool  = sum(1 for c in classes.values() if c["priority_in_pool"])
    n_mixed = sum(1 for c in classes.values() if c["priority_county_class"] == "mixed")
    print(f"[4] counties augmented: pool={n_pool:,} mixed={n_mixed:,}")
    return classes


# =============================================================================
# 5. National KPI summary + leaderboards
# =============================================================================
def write_summary(pool, reason, classes, tags):
    dep = tags["deploy_df_e"]; inv = tags["invest_df_e"]   # leaderboards: ranked (KY/PA out)
    thr = pd.read_csv(THRESH_FILE).iloc[0].to_dict()

    def top(df, n=15):
        cols = ["rank", "fips_tract", "county_state", "state_abbr",
                "burden_z", "burden_pct", "ddi", "ddi_pct_nat",
                "invest_score", "deploy_score", "card_last"]
        cols = [c for c in cols if c in df.columns]
        out = df.sort_values("rank").head(n)[cols].copy()
        out["fips_tract"] = out["fips_tract"].astype(str).str.zfill(11)
        return out.to_dict(orient="records")

    n_no_card   = sum(1 for r in reason.values() if r == "no_cardiologist")
    n_declining = sum(1 for r in reason.values() if r == "declining_workforce")
    states = set()   # states touched by box MEMBERSHIP (full frames, incl. KY/PA)
    for df in (tags["deploy_df"], tags["invest_df"]):
        states |= {s for s in df.get("state_abbr", pd.Series(dtype=str))
                   if isinstance(s, str) and s}

    summary = {
        "generated_from": "build_master (anchored 2x2 matrix, per-capita pool)",
        "ddi_convention": "Purdue DDI 0-100; HIGHER = worse readiness / bigger divide",
        "pool": {
            "n_counties": len(pool),
            "n_no_cardiologist": n_no_card,
            "n_declining_workforce": n_declining,
        },
        "tracts": {
            "n_deploy": len(tags["deploy_rank"]),
            "n_invest": len(tags["invest_rank"]),
            "n_deploy_ranked": len(tags["deploy_rank_e"]),
            "n_invest_ranked": len(tags["invest_rank_e"]),
            "n_both": 0,
        },
        "rank_exclusion": {
            "states": ["KY", "PA"],
            "state_fips": list(RANK_EXCLUDE_STATES),
            "reason": ("PLACES tract burden in these states rests on a single "
                       "measure (short sleep); tracts keep box membership but "
                       "are ineligible for the ranked national lists"),
        },
        "counties": {
            "n_pool": sum(1 for c in classes.values() if c["priority_in_pool"]),
            "n_mixed": sum(1 for c in classes.values() if c["priority_county_class"] == "mixed"),
            "n_deploy_lean": sum(1 for c in classes.values() if c["priority_county_class"] == "deploy_lean"),
            "n_invest_lean": sum(1 for c in classes.values() if c["priority_county_class"] == "invest_lean"),
            "n_high_need_other": sum(1 for c in classes.values() if c["priority_county_class"] == "high_need_other"),
        },
        "n_states_touched": len(states),
        "cutoffs": {
            "high_burden_cut": float(thr["high_burden_cut"]),
            "ready_cut_national_median_ddi": float(thr["ready_cut_national_median"]),
        },
        "top_deploy": top(dep),
        "top_invest": top(inv),
    }
    path = os.path.join(DATA_DIR, "priority_summary.json")
    with open(path, "w") as f:
        json.dump(summary, f, separators=(",", ":"), default=str)
    print(f"[5] priority_summary.json written "
          f"(pool={summary['pool']['n_counties']:,}, "
          f"deploy={summary['tracts']['n_deploy']:,}, "
          f"invest={summary['tracts']['n_invest']:,}, "
          f"states={summary['n_states_touched']})")
    return summary


def main():
    print("=" * 66)
    print("Augmenting dashboard data with the priority matrix targeting layer")
    print("=" * 66)
    pool, reason = build_pool()
    tags    = load_bucket_tags()
    counts  = augment_tracts(pool, tags)
    classes = augment_counties(pool, reason, counts)
    write_summary(pool, reason, classes, tags)
    print("\npriority layer complete.")


if __name__ == "__main__":
    main()
