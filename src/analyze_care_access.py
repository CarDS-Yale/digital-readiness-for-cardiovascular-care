"""
analyze_care_access.py
======================
Access across county lines and through primary care.

Residents of priority tracts may see cardiologists in neighbouring counties
or rely on primary care. This script measures both county-based proxies for
every priority tract and counts the tracts and residents that have neither.

Primary care supply comes from the AHRF panel that sens_workforce_primary_care
builds (non-federal MD and DO primary care physicians in patient care,
excluding residents). Three county definitions:

  PCP_pool    the sensitivity-analysis rule: no primary care physician in 2023
              or a declining per-capita rate (mirrors the cardiology rule)
  PCP_short   fewer than 28.57 physicians per 100,000 in 2023, which is a
              population-to-physician ratio above 3,500:1, the figure HRSA
              uses for geographic primary care shortage designation. This is a
              headcount proxy, not a formal shortage-area determination.
  PCP_zero    no primary care physician in 2023

Cardiology access beyond the county uses the 25-mile county-centroid pooling
from sens_workforce_distance (cardiologists summed over every county whose
centroid lies within 25 miles).

Run sens_workforce_primary_care.py and sens_workforce_distance.py first; both
cache the county tables this script reads.

Outputs (outputs/care_access/)
  county_primary_care_by_cardiology_status.csv
  county_crosstab.csv                  cardiology constraint x each PCP rule
  tracts_by_primary_care_backstop.csv  priority tracts with and without a backstop
  access_constraints.csv               tracts and residents meeting each
                                       combination of constraints (the main table)
  dual_constrained_by_state.csv, dual_constrained_by_class.csv,
  dual_constrained_top_counties.csv
  leading_tracts_access_flags.csv      the top-10 lists with their county flags
  tract_access_flags.csv               one row per priority tract
  care_access_summary.md
"""
import os

import numpy as np
import pandas as pd

from build_master import (load_master, matrix_boxes, box_label, rank_eligible,
                          acs_population, nchs_classes, markdown_table as md,
                          NCHS_ORDER, PROJECT_DIR)
from sens_workforce_primary_care import pool_from_panel, PANEL_FILE
from sens_workforce_distance import ACCESS_FILE

OUT = os.path.join(PROJECT_DIR, "outputs", "care_access")
os.makedirs(OUT, exist_ok=True)
SHORTAGE_RATE = 1e5 / 3500          # 28.57 physicians per 100,000
LOG = []


def log(s=""):
    print(s)
    LOG.append(s)


def iqr(s, nd=2):
    if not len(s):
        return ""
    return f"{s.median():.{nd}f} ({s.quantile(.25):.{nd}f} to {s.quantile(.75):.{nd}f})"


def county_table(tracts):
    """One row per county with cardiology data: pool flags, PCP supply, 25-mile access."""
    for f, script in ((PANEL_FILE, "sens_workforce_primary_care.py"),
                      (ACCESS_FILE, "sens_workforce_distance.py")):
        if not os.path.exists(f):
            raise SystemExit(f"{os.path.basename(f)} missing. Run {script} first.")
    panel = pd.read_csv(PANEL_FILE, dtype={"fips_st_cnty": str})
    panel["fips_st_cnty"] = panel["fips_st_cnty"].str.zfill(5)
    pcp = pool_from_panel(panel, "PCP")
    pcp["fips_st_cnty"] = pcp["fips_st_cnty"].astype(str).str.zfill(5)
    p23 = (panel[(panel["workforce"] == "PCP") & (panel["year"] == 2023)]
           [["fips_st_cnty", "count", "rate_100k"]]
           .rename(columns={"count": "pcp_2023", "rate_100k": "pcp_per_100k_2023"}))
    pcp = pcp.merge(p23, on="fips_st_cnty", how="left")
    pcp["PCP_pool"] = pcp["pool_zero"] | pcp["pool_declining"]
    pcp["PCP_short"] = pcp["pcp_per_100k_2023"] < SHORTAGE_RATE
    pcp["PCP_zero"] = pcp["pcp_2023"] == 0

    acc = pd.read_csv(ACCESS_FILE, dtype={"fips_st_cnty": str})
    acc["fips_st_cnty"] = acc["fips_st_cnty"].str.zfill(5)

    cty = (tracts.drop_duplicates("fips_county")
           [["fips_county", "county_state", "state_abbr", "card_last",
             "card_per_100k_last", "county_pop_last", "pool_nocard",
             "pool_declining", "in_pool"]]
           .merge(pcp[["fips_st_cnty", "pcp_2023", "pcp_per_100k_2023",
                       "PCP_pool", "PCP_short", "PCP_zero"]],
                  left_on="fips_county", right_on="fips_st_cnty", how="left")
           .drop(columns="fips_st_cnty")
           .merge(acc[["fips_st_cnty", "card_25mi_last", "pool_zero_25mi"]],
                  left_on="fips_county", right_on="fips_st_cnty", how="left")
           .drop(columns="fips_st_cnty")
           .merge(nchs_classes()[["fips_st_cnty", "nchs_label"]],
                  left_on="fips_county", right_on="fips_st_cnty", how="left")
           .drop(columns="fips_st_cnty"))
    cty = cty[cty["card_last"].notna()].copy()
    for c in ("in_pool", "pool_nocard", "pool_declining"):
        cty[c] = cty[c].astype(bool)
    log(f"Counties with cardiology data: {len(cty):,}; with primary care data: "
        f"{cty['pcp_2023'].notna().sum():,}; with 25-mile access: "
        f"{cty['card_25mi_last'].notna().sum():,}")
    return cty


def county_level(cty):
    log("\n## Primary care supply by cardiology status, 2023")
    groups = [("Workforce-constrained (pool)", cty["in_pool"]),
              ("  no cardiologist", cty["pool_nocard"]),
              ("  declining per capita", cty["pool_declining"]),
              ("Not constrained", ~cty["in_pool"]),
              ("All counties", pd.Series(True, index=cty.index))]
    rows = []
    for name, m in groups:
        s = cty[m & cty["pcp_2023"].notna() & cty["county_pop_last"].notna()]
        rows.append({"cardiology_status": name, "counties": len(s),
                     "PCP per 100,000, median (IQR)": iqr(s["pcp_per_100k_2023"], 1),
                     "PCP per 100,000, population-weighted mean":
                         round(np.average(s["pcp_per_100k_2023"], weights=s["county_pop_last"]), 1),
                     "pct_below_shortage_ratio": round(100 * s["PCP_short"].mean(), 1),
                     "pct_no_PCP": round(100 * s["PCP_zero"].mean(), 1)})
    S = pd.DataFrame(rows).set_index("cardiology_status")
    S.to_csv(os.path.join(OUT, "county_primary_care_by_cardiology_status.csv"))
    log(md(S))

    rows = []
    for rule in ("PCP_pool", "PCP_short", "PCP_zero"):
        for name, m in groups:
            s = cty[m & cty["pcp_2023"].notna()]
            rows.append({"pcp_rule": rule, "cardiology_status": name, "counties": len(s),
                         "pcp_constrained": int(s[rule].sum()),
                         "pct_counties": round(100 * s[rule].mean(), 1),
                         "pct_population": round(100 * s.loc[s[rule], "county_pop_last"].sum()
                                                 / s["county_pop_last"].sum(), 1)})
    X = pd.DataFrame(rows)
    X.to_csv(os.path.join(OUT, "county_crosstab.csv"), index=False)
    log("\nCardiology constraint by primary care rule:")
    log(md(X.set_index(["pcp_rule", "cardiology_status"])))


def priority_tracts(cty):
    tracts, anchors = load_master()
    nat = float(anchors["nat_med_ddi"])
    pool = (tracts[tracts["in_pool"]].dropna(subset=["burden_z", "ddi"])
            .drop_duplicates("fips_tract").copy())
    inv, dep = matrix_boxes(pool, "ddi", nat)
    pool["group"] = box_label(pool, inv, dep)
    L = pool[pool["group"].isin(["INVEST", "DEPLOY"])].copy()
    L = L.merge(cty[["fips_county", "pcp_2023", "pcp_per_100k_2023", "PCP_pool",
                     "PCP_short", "PCP_zero", "card_25mi_last", "pool_zero_25mi",
                     "nchs_label"]], on="fips_county", how="left")
    L["pop"] = L["fips_tract"].map(acs_population())
    L["is_invest"] = L["group"].eq("INVEST")
    L["no_card_25mi"] = L["pool_zero_25mi"] == True
    L["dual_constrained"] = L["no_card_25mi"] & (L["PCP_short"] == True)
    log(f"\nPriority tracts {len(L):,}; primary care data matched "
        f"{L['pcp_2023'].notna().mean() * 100:.1f}%; 25-mile data matched "
        f"{L['card_25mi_last'].notna().mean() * 100:.1f}%")
    return L, inv, dep


def by_backstop(L):
    log("\n## Priority tracts by primary care backstop")
    rows = []
    for grp in ("INVEST", "DEPLOY", "Both"):
        d = L if grp == "Both" else L[L["group"] == grp]
        tot_p = d["pop"].sum()
        for rule in ("PCP_pool", "PCP_short", "PCP_zero"):
            dual, single = d[d[rule] == True], d[d[rule] == False]
            rows.append({"group": grp, "pcp_rule": rule,
                         "tracts": len(dual), "pct_tracts": round(100 * len(dual) / len(d), 1),
                         "residents_millions": round(dual["pop"].sum() / 1e6, 2),
                         "pct_residents": round(100 * dual["pop"].sum() / tot_p, 1),
                         "counties": dual["fips_county"].nunique(),
                         "burden_z, constrained": iqr(dual["burden_z"]),
                         "burden_z, other": iqr(single["burden_z"]),
                         "DDI, constrained": iqr(dual["ddi"], 1),
                         "DDI, other": iqr(single["ddi"], 1)})
    B = pd.DataFrame(rows)
    B.to_csv(os.path.join(OUT, "tracts_by_primary_care_backstop.csv"), index=False)
    log(md(B.set_index(["group", "pcp_rule"])))


def access_constraints(L):
    log("\n## Tracts and residents by access constraint")
    rows = []
    for grp in ("INVEST", "DEPLOY", "Both"):
        d = L if grp == "Both" else L[L["group"] == grp]
        tot_p = d["pop"].sum()
        conds = [
            ("No cardiologist in county", d["pool_nocard"].astype(bool)),
            ("No cardiologist within 25 miles", d["no_card_25mi"]),
            ("No cardiologist within 25 miles and primary care below threshold",
             d["dual_constrained"]),
            ("No cardiologist within 25 miles and primary care pool rule",
             d["no_card_25mi"] & (d["PCP_pool"] == True)),
            ("No cardiologist within 25 miles and no primary care physician",
             d["no_card_25mi"] & (d["PCP_zero"] == True)),
            ("No cardiologist in county and primary care below threshold",
             d["pool_nocard"].astype(bool) & (d["PCP_short"] == True)),
        ]
        for name, m in conds:
            s = d[m]
            rows.append({"group": grp, "constraint": name, "tracts": len(s),
                         "pct_tracts": round(100 * len(s) / len(d), 1),
                         "residents_millions": round(s["pop"].sum() / 1e6, 2),
                         "pct_residents": round(100 * s["pop"].sum() / tot_p, 1),
                         "counties": s["fips_county"].nunique(),
                         "states": s["state_abbr"].nunique(),
                         "burden_z": iqr(s["burden_z"]), "DDI": iqr(s["ddi"], 1)})
    C = pd.DataFrame(rows)
    C.to_csv(os.path.join(OUT, "access_constraints.csv"), index=False)
    log(md(C.set_index(["group", "constraint"])))

    rest = L[~L["dual_constrained"]]
    dual = L[L["dual_constrained"]]
    log(f"\nDual-constrained tracts: burden z {iqr(dual['burden_z'])} vs "
        f"{iqr(rest['burden_z'])} in the remaining priority tracts; "
        f"DDI {iqr(dual['ddi'], 1)} vs {iqr(rest['ddi'], 1)}")


def dual_geography(L):
    log("\n## Where the dual-constrained priority tracts are")
    D = L[L["dual_constrained"]]
    st = (D.groupby("state_abbr")
            .agg(tracts=("pop", "size"), residents=("pop", "sum"),
                 counties=("fips_county", "nunique"))
            .sort_values("residents", ascending=False))
    st["pct_residents"] = (100 * st["residents"] / st["residents"].sum()).round(1)
    st.to_csv(os.path.join(OUT, "dual_constrained_by_state.csv"))
    log("Top 15 states by dual-constrained priority residents:")
    log(md(st.head(15), ".0f"))

    nc = (L.assign(nchs_label=pd.Categorical(L["nchs_label"], NCHS_ORDER))
            .groupby("nchs_label", observed=True)
            .agg(priority_tracts=("pop", "size"), priority_residents=("pop", "sum"),
                 dual_tracts=("dual_constrained", "sum"),
                 dual_residents=("pop", lambda s: s[L.loc[s.index, "dual_constrained"]].sum())))
    nc["pct_priority_residents_dual"] = (100 * nc["dual_residents"] / nc["priority_residents"]).round(1)
    nc.to_csv(os.path.join(OUT, "dual_constrained_by_class.csv"))
    log("\nBy county class:")
    log(md(nc, ".0f"))

    top = (D.groupby(["county_state", "nchs_label"], observed=True)
             .agg(tracts=("pop", "size"), residents=("pop", "sum"),
                  investment=("is_invest", "sum"),
                  pcp_per_100k=("pcp_per_100k_2023", "first"),
                  cardiologists_25mi=("card_25mi_last", "first"),
                  burden_z_median=("burden_z", "median"), ddi_median=("ddi", "median"))
             .sort_values("residents", ascending=False).head(20))
    top.to_csv(os.path.join(OUT, "dual_constrained_top_counties.csv"))
    log("\nCounties with the most dual-constrained priority residents:")
    log(md(top.reset_index().set_index("county_state")))


def leading_tracts(L, inv, dep):
    log("\n## Access flags for the leading tracts")
    flags = L[["fips_tract", "pcp_per_100k_2023", "PCP_pool", "PCP_short", "PCP_zero",
               "card_25mi_last", "no_card_25mi", "dual_constrained"]]
    rows = []
    for grp, ranked in (("INVEST", rank_eligible(inv)), ("DEPLOY", rank_eligible(dep))):
        t = (ranked.head(10)[["rank", "fips_tract", "county_state", "card_last"]]
             .merge(flags, on="fips_tract", how="left"))
        t.insert(0, "group", grp)
        rows.append(t)
    E = pd.concat(rows, ignore_index=True)
    E.to_csv(os.path.join(OUT, "leading_tracts_access_flags.csv"), index=False)
    log(md(E.set_index(["group", "rank"]), ".1f"))


def main():
    tracts, _ = load_master()
    cty = county_table(tracts)
    county_level(cty)
    L, inv, dep = priority_tracts(cty)
    by_backstop(L)
    access_constraints(L)
    dual_geography(L)
    leading_tracts(L, inv, dep)
    L[["fips_tract", "fips_county", "group", "pop", "pcp_per_100k_2023", "PCP_pool",
       "PCP_short", "PCP_zero", "card_25mi_last", "no_card_25mi", "dual_constrained"]
      ].to_csv(os.path.join(OUT, "tract_access_flags.csv"), index=False)
    with open(os.path.join(OUT, "care_access_summary.md"), "w") as fh:
        fh.write("# Access across county lines and through primary care\n\n"
                 "Primary care = AHRF non-federal MD and DO primary care physicians in "
                 f"patient care, excluding residents. Shortage threshold = {SHORTAGE_RATE:.2f} "
                 "per 100,000 (one physician per 3,500 residents). 25-mile access from "
                 "sens_workforce_distance.\n\n")
        fh.write("\n".join(LOG) + "\n")
    print(f"\nwritten -> {OUT}")


if __name__ == "__main__":
    main()
