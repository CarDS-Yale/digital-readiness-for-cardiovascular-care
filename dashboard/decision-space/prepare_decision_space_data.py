"""Build the compact dataset for the decision-space page.

One record per tract in the workforce-constrained pool, with the fields the
page needs to redraw the classification under user-chosen thresholds: the
standardized burden and readiness values behind the priority scores, the
national cut points the threshold presets use, and the county's state and
metropolitan area for the scope control. Kentucky and Pennsylvania tracts are
carried as hidden rows so national counts stay right when the thresholds
move; the page never plots or ranks them.
"""
import json, os
import numpy as np, pandas as pd

import pathlib
UP = str(pathlib.Path(__file__).resolve().parents[2])
OUT = str(pathlib.Path(__file__).resolve().parent / "data")
os.makedirs(OUT, exist_ok=True)

# ── load ──────────────────────────────────────────────────────────────
burden = pd.read_csv(f"{UP}/outputs/burden_workforce/burden_tracts.csv",
                     dtype={"fips_tract": str, "fips_county": str})
burden["fips_tract"] = burden["fips_tract"].str.zfill(11)
burden["fips_county"] = burden["fips_county"].str.zfill(5)

ddi = pd.read_excel(f"{UP}/DDI/2022-2024 US DDI.xlsx", dtype={"FIPS": str})
ddi["FIPS"] = ddi["FIPS"].str.zfill(11)
nat_med = float(ddi["DDI"].median())
ddi = ddi.rename(columns={"FIPS": "fips_tract", "DDI": "ddi"})
ddi["ddi_pct_nat"] = (ddi["ddi"].rank(pct=True) * 100).round(1)
ddi = ddi[["fips_tract", "ddi", "ddi_pct_nat"]]

wf = pd.read_csv(f"{UP}/outputs/burden_workforce/county_workforce_summary.csv",
                 dtype={"fips_st_cnty": str})
wf["fips_st_cnty"] = wf["fips_st_cnty"].str.zfill(5)
wt = pd.read_csv(f"{UP}/outputs/ahrf_workforce_trend_summary.csv", dtype={"fips_st_cnty": str})
wt["fips_st_cnty"] = wt["fips_st_cnty"].str.zfill(5)
wf = wf.merge(wt[["fips_st_cnty", "workforce_slope_pc", "workforce_trend_pc"]],
              on="fips_st_cnty", how="left")

# ── pool (mirrors build_master.combined_pool) ───────────────────
no_card = wf["card_last"] == 0
has = wf["card_last"] > 0
dec_ols = wf["workforce_slope_pc"].notna() & (wf["workforce_slope_pc"] < 0)
dec_small = (wf["mean_card_dis"] < 3) & (wf["card_per_100k_last"] < wf["card_per_100k_first"])
declining = has & (dec_ols | dec_small)
wf["pool_reason"] = np.where(no_card, "no_card", np.where(declining, "declining", ""))
pool = set(wf[no_card | declining]["fips_st_cnty"])
print(f"pool counties {len(pool):,}  (no-card {int(no_card.sum()):,} declining {int(declining.sum()):,})")

tracts = burden.merge(ddi, on="fips_tract", how="left")
# national cut points for the threshold presets, taken over every tract with
# the measure, the same way sens_thresholds.py takes them
nat_b = tracts.drop_duplicates("fips_tract")["burden_z"].dropna()
nat_d = tracts.drop_duplicates("fips_tract")["ddi"].dropna()
cuts = {
    "burdenP75": round(float(nat_b.quantile(0.75)), 4),
    "burdenP90": round(float(nat_b.quantile(0.90)), 4),
    "ddiP10": round(float(nat_d.quantile(0.10)), 3),
    "ddiP25": round(float(nat_d.quantile(0.25)), 3),
    "ddiP75": round(float(nat_d.quantile(0.75)), 3),
    "ddiP90": round(float(nat_d.quantile(0.90)), 3),
}
P = (tracts[tracts["fips_county"].isin(pool)]
     .dropna(subset=["burden_z", "ddi"]).drop_duplicates("fips_tract").copy())
print(f"pool tracts {len(P):,}  nat median DDI {nat_med:.2f}")

# ── boxes + scores (mirrors matrix_targets) ───────────────────────────
P["high_burden"] = P["burden_z"] > 0
P["ready"] = P["ddi"] <= nat_med
zb = (P["burden_z"] - P["burden_z"].mean()) / P["burden_z"].std()
zr = (P["ddi"] - P["ddi"].mean()) / P["ddi"].std()
P["zb"], P["zr"] = zb, zr          # the page rebuilds both scores from these
P["deploy_score"] = zb - zr
P["invest_score"] = zb + zr
P["bucket"] = np.where(P["high_burden"] & P["ready"], 1,
              np.where(P["high_burden"] & ~P["ready"], 2, 0))
print("boxes:", P["bucket"].value_counts().to_dict())

# cross-check against published priority CSVs
dep_pub = pd.read_csv(f"{UP}/outputs/master/priority_DEPLOY_ranked.csv",
                      dtype={"fips_tract": str})
inv_pub = pd.read_csv(f"{UP}/outputs/master/priority_INVEST_ranked.csv",
                      dtype={"fips_tract": str})
dep_pub["fips_tract"] = dep_pub["fips_tract"].str.zfill(11)
inv_pub["fips_tract"] = inv_pub["fips_tract"].str.zfill(11)
assert set(P[P.bucket == 1]["fips_tract"]) == set(dep_pub["fips_tract"]), "deploy mismatch"
assert set(P[P.bucket == 2]["fips_tract"]) == set(inv_pub["fips_tract"]), "invest mismatch"
print("bucket membership matches published priority CSVs")

# States whose PLACES tract burden rests on a single measure (short sleep).
# Their tracts keep box membership and the box counts, but they leave the
# plotted cloud and the ranked lists (mirrors build_master /
# make_figure2: rank_eligible + the Pbg background filter).
RANK_EXCLUDE_STATES = ("21", "42")   # KY, PA

n_dep_full, n_inv_full = len(dep_pub), len(inv_pub)


def rank_eligible(df):
    st = df["fips_tract"].astype(str).str.zfill(11).str[:2]
    out = df[~st.isin(RANK_EXCLUDE_STATES)].reset_index(drop=True)
    out["rank"] = out.index + 1
    return out


dep_e, inv_e = rank_eligible(dep_pub), rank_eligible(inv_pub)

# ranks from the eligible re-ranked lists (KY/PA carry no rank)
rank_map = {}
for df in (dep_e, inv_e):
    for f, r in zip(df["fips_tract"], df["rank"]):
        rank_map[f] = int(r)
P["rank"] = P["fips_tract"].map(rank_map)

# KY/PA stay in the file as hidden rows (single-measure burden axis): they
# count toward the totals but are never plotted or ranked
n_before = len(P)
P["hidden"] = P["fips_tract"].str[:2].isin(RANK_EXCLUDE_STATES).astype(int)
n_shown = int((P["hidden"] == 0).sum())
print(f"KY/PA hidden from plot: {n_before - n_shown:,} tracts "
      f"(deploy ranked {len(dep_e):,}/{n_dep_full:,}, "
      f"invest ranked {len(inv_e):,}/{n_inv_full:,})")

# ── sidebar detail fields ─────────────────────────────────────────────
td = json.load(open(f"{UP}/dashboard/data/tract_data.json"))
cd = json.load(open(f"{UP}/dashboard/data/county_data.json"))
wfi = wf.set_index("fips_st_cnty")

TREND = {"increasing": 1, "stable": 0, "improving": -1, "decreasing": -1}
WTREND = {"growing": 1, "stagnant": 0, "declining": -1, "insufficient_data": 9}
TIER = {"Tier1_high_readiness": 1, "Tier2_moderate_readiness": 2, "Tier3_low_readiness": 3}
REASON = {"no_card": 1, "declining": 2, "": 0}

def rnd(v, n):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return None
    return round(float(v), n)

county_fips = sorted(P["fips_county"].unique())
cidx = {f: i for i, f in enumerate(county_fips)}
county_rows = []
for f in county_fips:
    c = cd.get(f, {})
    w = wfi.loc[f] if f in wfi.index else None
    name = c.get("county_name")
    st = c.get("state_abbr")
    if not name:  # counties absent from county_data.json (rare)
        name, st = f, ""
    county_rows.append([
        f, name, st or "",
        REASON.get(w["pool_reason"], 0) if w is not None else 0,
        WTREND.get(str(w["workforce_trend_pc"]), 9) if w is not None else 9,
        rnd(w["card_last"], 0) if w is not None else None,
        rnd(w["card_per_100k_first"], 2) if w is not None else None,
        rnd(w["card_per_100k_last"], 2) if w is not None else None,
        rnd(w["county_pop_last"], 0) if w is not None else None,
        c.get("cbsa_name") or "",
    ])

miss = 0
tract_rows = []
for row in P.itertuples(index=False):
    t = (td.get(row.fips_county) or {}).get(row.fips_tract) or {}
    if not t:
        miss += 1
    score = row.deploy_score if row.bucket == 1 else (row.invest_score if row.bucket == 2 else None)
    tract_rows.append([
        row.fips_tract,
        cidx[row.fips_county],
        rnd(row.ddi, 2),                 # x; two decimals keep the preset cuts honest
        rnd(row.burden_z, 4),            # y
        int(row.bucket),
        int(row.rank) if not pd.isna(row.rank) else None,
        rnd(score, 2),
        rnd(row.zb, 4),
        rnd(row.zr, 4),
        int(row.hidden),
        rnd(row.ddi_pct_nat, 0),
        rnd(row.burden_pct, 1),
        TREND.get(t.get("burden_trend"), None),
        rnd(t.get("burden_z_first"), 2),
        rnd(t.get("burden_z_last"), 2),
        rnd(t.get("burden_z_delta"), 2),
        rnd(t.get("burden_slope"), 3),
        rnd(t.get("ddi_infa"), 1),
        rnd(t.get("ddi_se"), 1),
        TIER.get(t.get("digital_readiness_tier"), None),
        rnd(t.get("composite_risk_score"), 3),
    ])
print(f"tracts without sidebar detail: {miss}")

out = {
    "meta": {
        "natMedianDDI": round(nat_med, 2),
        # full box counts (manuscript numbers, incl. KY/PA membership)
        "nPoolTracts": int(n_before),
        "nPoolCounties": len(pool),
        "nDeploy": n_dep_full,
        "nInvest": n_inv_full,
        # what the page can actually plot and rank (KY/PA out)
        "nPlotted": n_shown,
        "nDeployShown": int(((P.bucket == 1) & (P.hidden == 0)).sum()),
        "nInvestShown": int(((P.bucket == 2) & (P.hidden == 0)).sum()),
        "nDeployRanked": int(len(dep_e)),
        "nInvestRanked": int(len(inv_e)),
        "excludedStates": ["KY", "PA"],
        "nNoCardCounties": int(no_card.sum()),
        "nDecliningCounties": int(declining.sum()),
        # pool standardization behind the priority scores, and the national
        # cut points offered as threshold presets
        "poolBurdenMean": round(float(P["burden_z"].mean()), 4),
        "poolBurdenSd": round(float(P["burden_z"].std()), 4),
        "poolDdiMean": round(float(P["ddi"].mean()), 4),
        "poolDdiSd": round(float(P["ddi"].std()), 4),
        **cuts,
    },
    "countyCols": ["fips", "name", "state", "poolReason", "wfTrendPc", "cardLast",
                   "rateFirst", "rateLast", "pop", "cbsa"],
    "counties": county_rows,
    "tractCols": ["fips", "ci", "ddi", "burdenZ", "bucket", "rank", "score",
                  "zb", "zr", "hidden", "ddiPctNat", "burdenPct", "burdenTrend", "bzFirst", "bzLast",
                  "bzDelta", "bSlope", "ddiInfa", "ddiSe", "tier", "risk"],
    "tracts": tract_rows,
}
path = f"{OUT}/decision_space.json"
json.dump(out, open(path, "w"), separators=(",", ":"))
print(f"wrote {path}  {os.path.getsize(path)/1e6:.1f} MB")
