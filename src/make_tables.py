"""
make_tables.py
==============
Ranked tract lists and the threshold grid, written as CSVs to outputs/tables/
and numbered as in the supplement.

  S1, S2      top 25 investment and deployment tracts, primary analysis
  S9, S10     readiness rebuilt from six ACS indicators plus FCC availability
  S11, S12    readiness = infrastructure/adoption subscore alone
  S13, S14    readiness = socioeconomic subscore alone
  S15, S16    workforce = cardiologists plus cardiology NPs and PAs
  S17, S18    workforce = cardiologists and endocrinologists (joint absence)
  S19, S20    workforce pool rebuilt on primary care physicians
  S21, S22    all tracts, no workforce screen
  S23, S24    25-mile cross-county workforce access
  S25         the 3 x 3 grid of burden and readiness cutoffs

Odd numbers are investment lists, even numbers deployment lists, 25 rows
each. Every ranked list drops Kentucky and Pennsylvania (single-measure
burden). Variant lists flag whether each tract also sits in the primary
top 25.

Needs the master cache, the ACS and FCC component files, and the county
tables cached by sens_thresholds, sens_workforce_primary_care,
sens_workforce_distance, process_clinicians and sens_workforce_endocrinology.
"""
import os

import numpy as np
import pandas as pd

from build_master import (load_master, matrix_boxes, rank_eligible, acs_components,
                          fcc_availability, OUT_DIR as MASTER_DIR, PROJECT_DIR)
from sens_workforce_primary_care import pool_from_panel, PANEL_FILE
from sens_workforce_distance import ACCESS_FILE

OUT = os.path.join(PROJECT_DIR, "outputs", "tables")
os.makedirs(OUT, exist_ok=True)

ACS_COMPS = ["no_internet_pct", "no_computer_pct", "poverty_pct",
             "disability_pct", "age_65plus_pct", "lt_highschool_pct"]
N = 25


def split_county(cs):
    if pd.isna(cs):
        return "", ""
    parts = str(cs).rsplit(",", 1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


def base_cols(df):
    d = df.head(N).copy()
    cty = d["county_state"].map(split_county)
    d["County"] = [c[0] for c in cty]
    d["State"] = [c[1] for c in cty]
    d["Tract FIPS"] = d["fips_tract"].astype(str).str.zfill(11)
    d["Rank"] = range(1, len(d) + 1)
    return d


def save(name, df):
    df.to_csv(os.path.join(OUT, f"{name}.csv"), index=False)
    print(f"  {name}: {len(df)} rows")


def need(path, script):
    if not os.path.exists(path):
        raise SystemExit(f"{os.path.basename(path)} missing. Run {script} first.")
    return path


def main():
    tracts, anchors = load_master()
    nat = anchors["nat_med_ddi"]
    P = (tracts[tracts["in_pool"]]
         .dropna(subset=["burden_z", "ddi"]).drop_duplicates("fips_tract"))
    inv0, dep0 = matrix_boxes(P, "ddi", nat)
    inv0e, dep0e = rank_eligible(inv0), rank_eligible(dep0)
    prim25 = {"inv": set(inv0e["fips_tract"].head(N)),
              "dep": set(dep0e["fips_tract"].head(N))}

    # ── S1, S2: the primary lists ───────────────────────────────────────────
    def primary_table(df):
        d = base_cols(df)
        out = d[["Rank", "County", "State", "Tract FIPS"]].copy()
        out["DDI (composite)"] = d["ddi"].round(1)
        out["DDI INFA"] = d["infa"].round(1)
        out["DDI SE"] = d["se"].round(1)
        out["Cardiologists per 100,000"] = d["card_per_100k_last"].round(2)
        out["Burden z score"] = d["burden_z"].round(2)
        return out
    save("table_S1_investment_primary", primary_table(inv0e))
    save("table_S2_deployment_primary", primary_table(dep0e))

    # one variant list, either group
    def variant_table(df, group, extra=None, flag_pool=False):
        d = base_cols(rank_eligible(df))
        out = d[["Rank", "County", "State", "Tract FIPS"]].copy()
        if extra:
            for col_label, src, nd in extra:
                out[col_label] = d[src].round(nd)
        out["DDI (composite)"] = d["ddi"].round(1)
        out["Burden z score"] = d["burden_z"].round(2)
        if flag_pool:
            out["In workforce-constrained pool"] = np.where(
                d["in_pool"].astype(bool), "Yes", "No")
        else:
            out["In primary top 25"] = np.where(
                d["fips_tract"].isin(prim25[group]), "Yes", "No")
        return out

    def save_pair(n_inv, n_dep, tag, inv, dep, **kw):
        save(f"table_S{n_inv}_investment_{tag}", variant_table(inv, "inv", **kw))
        save(f"table_S{n_dep}_deployment_{tag}", variant_table(dep, "dep", **kw))

    # ── S9, S10: readiness from raw components ──────────────────────────────
    comp = acs_components().merge(fcc_availability()[["GEOID", "terr_unserved_pct"]],
                                  on="GEOID", how="inner")
    cols = ACS_COMPS + ["terr_unserved_pct"]
    a = comp.dropna(subset=cols).copy()
    z = (a[cols] - a[cols].mean()) / a[cols].std()
    a["cidx"] = z.mean(axis=1)
    Pv = P.merge(a[["GEOID", "cidx"]], left_on="fips_tract", right_on="GEOID", how="left")
    inv_c, dep_c = matrix_boxes(Pv, "cidx", float(a["cidx"].median()))
    save_pair(9, 10, "readiness_components", inv_c, dep_c,
              extra=[("Components index (z)", "cidx", 2)])

    # ── S11 to S14: subscores ───────────────────────────────────────────────
    inv_i, dep_i = matrix_boxes(P, "infa", anchors["nat_med_infa"])
    save_pair(11, 12, "readiness_infa", inv_i, dep_i, extra=[("INFA score", "infa", 1)])
    inv_s, dep_s = matrix_boxes(P, "se", anchors["nat_med_se"])
    save_pair(13, 14, "readiness_se", inv_s, dep_s, extra=[("SE score", "se", 1)])

    # ── S15, S16: cardiologists plus cardiology NPs and PAs ─────────────────
    app = pd.read_csv(need(os.path.join(MASTER_DIR, "dac_cardiology_app_county.csv"),
                           "process_clinicians.py"), dtype={"fips_st_cnty": str})
    app["fips_st_cnty"] = app["fips_st_cnty"].str.zfill(5)
    cnty = (tracts.drop_duplicates("fips_county")
            [["fips_county", "card_last", "pool_declining"]]
            .merge(app, left_on="fips_county", right_on="fips_st_cnty", how="left"))
    cnty["n_app_site_strict"] = cnty["n_app_site_strict"].fillna(0)
    # counties with no AHRF record (the Connecticut planning regions) cannot
    # enter the pool; without this guard a missing count would read as zero
    has_wf = cnty["card_last"].notna()
    pool_g = set(cnty.loc[has_wf & (
        ((cnty["card_last"].fillna(0) + cnty["n_app_site_strict"]) == 0)
        | cnty["pool_declining"].fillna(False)), "fips_county"])
    Pg = tracts[tracts["fips_county"].isin(pool_g)].copy()
    app_n = dict(zip(cnty["fips_county"], cnty["n_app_site_strict"].astype(int)))
    Pg["n_card_app"] = Pg["fips_county"].map(app_n).fillna(0).astype(int)
    inv_g, dep_g = matrix_boxes(Pg, "ddi", nat)
    save_pair(15, 16, "workforce_advanced_practice", inv_g, dep_g,
              extra=[("Cardiology NP/PA in county", "n_card_app", 0)])

    # ── S17, S18: cardiologists and endocrinologists ────────────────────────
    endo = pd.read_csv(need(os.path.join(MASTER_DIR, "workforce_endocrinology_county.csv"),
                            "sens_workforce_endocrinology.py"), dtype={"fips_county": str})
    endo["fips_county"] = endo["fips_county"].str.zfill(5)
    pool_e = set(endo.loc[endo["pool_joint_absence"].astype(bool), "fips_county"])
    Pe = tracts[tracts["fips_county"].isin(pool_e)].copy()
    Pe["n_endo"] = Pe["fips_county"].map(dict(zip(endo["fips_county"], endo["n_endo"])))
    inv_e, dep_e = matrix_boxes(Pe, "ddi", nat)
    save_pair(17, 18, "workforce_endocrinology", inv_e, dep_e,
              extra=[("Endocrinologists in county", "n_endo", 0)])

    # ── S19, S20: primary care pool ─────────────────────────────────────────
    panel = pd.read_csv(need(PANEL_FILE, "sens_workforce_primary_care.py"),
                        dtype={"fips_st_cnty": str})
    cp = pool_from_panel(panel, "PCP")
    pool_pcp = set(cp.loc[cp["in_pool"], "fips_st_cnty"].astype(str).str.zfill(5))
    inv_p, dep_p = matrix_boxes(tracts[tracts["fips_county"].isin(pool_pcp)], "ddi", nat)
    save_pair(19, 20, "workforce_primary_care", inv_p, dep_p)

    # ── S21, S22: all tracts ────────────────────────────────────────────────
    inv_a, dep_a = matrix_boxes(tracts, "ddi", nat)
    save_pair(21, 22, "all_tracts", inv_a, dep_a, flag_pool=True)

    # ── S23, S24: 25-mile access pool ───────────────────────────────────────
    acc = pd.read_csv(need(ACCESS_FILE, "sens_workforce_distance.py"),
                      dtype={"fips_st_cnty": str})
    pool_25 = set(acc.loc[acc["in_pool_25mi"], "fips_st_cnty"].str.zfill(5))
    inv_f, dep_f = matrix_boxes(tracts[tracts["fips_county"].isin(pool_25)], "ddi", nat)
    save_pair(23, 24, "workforce_distance", inv_f, dep_f)

    # ── S25: threshold grid ─────────────────────────────────────────────────
    g = pd.read_csv(need(os.path.join(MASTER_DIR, "thresholds_grid.csv"), "sens_thresholds.py"))
    allt = tracts.dropna(subset=["burden_z", "ddi"]).drop_duplicates("fips_tract")
    bq, dq = allt["burden_z"].quantile, allt["ddi"].quantile
    lab_b = {"mean": "Above mean (z > 0)",
             "p75": f"Top 25% (z >= {bq(.75):.2f})",
             "p90": f"Top 10% (z >= {bq(.90):.2f})"}
    lab_r = {"median": f"Median split ({dq(.5):.1f})",
             "p25_p75": f"Quartile split ({dq(.25):.1f} / {dq(.75):.1f})",
             "p10_p90": f"Decile split ({dq(.10):.1f} / {dq(.90):.1f})"}
    t25 = pd.DataFrame({
        "Burden cutoff": g["burden_cut"].map(lab_b),
        "Readiness cutoff": g["ready_cut"].map(lab_r),
        "Investment tracts": g["n_invest"].map("{:,}".format),
        "Deployment tracts": g["n_deploy"].map("{:,}".format),
        "Primary top-10 investment retained":
            g["base_inv_top10_surviving"].map(lambda x: f"{x}/10"),
        "Primary top-10 deployment retained":
            g["base_dep_top10_surviving"].map(lambda x: f"{x}/10"),
    })
    save("table_S25_threshold_grid", t25)

    print(f"\nall tables -> {OUT}")


if __name__ == "__main__":
    main()
