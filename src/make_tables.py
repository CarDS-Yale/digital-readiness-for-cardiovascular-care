"""
make_tables.py
=================
Manuscript tables, written as CSVs to outputs/tables/.

  table_1A  top 25 investment tracts, primary analysis
  table_1B  top 25 deployment tracts, primary analysis
  table_2   top 25 per group, readiness = raw components (ACS-6 + FCC)
  table_3A  top 25 per group, readiness = INFA sub-score only
  table_3B  top 25 per group, readiness = SE sub-score only
  table_4   top 25 per group, all US tracts (no workforce screen)
  table_5   top 25 per group, primary care physician workforce pool
  table_6   threshold grid (3x3 national cutoffs)
  table_7   top 25 per group, 25-mile cross-county workforce access
  table_8   top 25 per group, composite cardiologist + cardiology NP/PA pool

Per user decisions 2026-07-20: top 25 for BOTH groups in every variant
table; the NP/PA profession-total variation gets no table. Requires the
the cached master table, the primary-care county panel, the 25-mile
access table and the CMS county counts and the ACS/FCC component files.
"""
import os, glob
import numpy as np
import pandas as pd

from build_master import (load_master, matrix_boxes, rank_eligible,
                              OUT_DIR as MASTER_DIR, PROJECT_DIR)

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
    d = df.copy()
    cty = d["county_state"].map(lambda s: split_county(s))
    d["County"] = [c[0] for c in cty]
    d["State"] = [c[1] for c in cty]
    d["Tract FIPS"] = d["fips_tract"].astype(str).str.zfill(11)
    return d


def save(name, df):
    df.to_csv(os.path.join(OUT, f"{name}.csv"), index=False)
    print(f"  {name}: {len(df)} rows")


def main():
    tracts, anchors = load_master()
    nat = anchors["nat_med_ddi"]
    P = (tracts[tracts["in_pool"]]
         .dropna(subset=["burden_z", "ddi"]).drop_duplicates("fips_tract"))
    inv0, dep0 = matrix_boxes(P, "ddi", nat)
    # ranked national lists exclude single-measure-burden states (KY/PA)
    inv0e, dep0e = rank_eligible(inv0), rank_eligible(dep0)
    prim25 = {"Invest": set(inv0e["fips_tract"].head(N)),
              "Deploy": set(dep0e["fips_tract"].head(N))}

    # ── Tables 1A / 1B ──────────────────────────────────────────────────────
    def primary_table(df):
        d = base_cols(df.head(N))
        d["Rank"] = range(1, len(d) + 1)
        out = d[["Rank", "County", "State", "Tract FIPS"]].copy()
        out["DDI (composite)"] = d["ddi"].round(1)
        out["DDI INFA"] = d["infa"].round(1)
        out["DDI SE"] = d["se"].round(1)
        out["Cardiologists per 100,000"] = d["card_per_100k_last"].round(2)
        out["Burden z-score"] = d["burden_z"].round(2)
        return out
    save("table_1A", primary_table(inv0e))
    save("table_1B", primary_table(dep0e))

    # generic variant table: both groups stacked, top 25 each
    def variant_table(inv, dep, extra=None, flag_primary=True, flag_pool=False):
        rows = []
        for grp, df in [("Invest", rank_eligible(inv)),
                        ("Deploy", rank_eligible(dep))]:
            d = base_cols(df.head(N))
            d["Rank"] = range(1, len(d) + 1)
            out = d[["Rank", "County", "State", "Tract FIPS"]].copy()
            out.insert(0, "Group", grp)
            if extra:
                for col_label, src, nd in extra:
                    out[col_label] = d[src].round(nd)
            out["DDI (composite)"] = d["ddi"].round(1)
            out["Burden z-score"] = d["burden_z"].round(2)
            if flag_pool:
                out["In high-need pool"] = np.where(d["in_pool"].astype(bool), "Yes", "No")
            if flag_primary:
                out["In primary top 25"] = np.where(
                    d["fips_tract"].isin(prim25[grp]), "Yes", "No")
            rows.append(out)
        return pd.concat(rows, ignore_index=True)

    # ── Table 2: raw components ─────────────────────────────────────────────
    acs = pd.read_csv(sorted(glob.glob(os.path.join(
        PROJECT_DIR, "ACS", "acs5_*_tract_ddi_components.csv")))[-1],
        dtype={"GEOID": str})
    fcc = pd.read_csv(sorted(glob.glob(os.path.join(
        PROJECT_DIR, "FCC", "fcc_*_tract_availability.csv")))[-1],
        dtype={"GEOID": str})[["GEOID", "terr_unserved_pct"]]
    comp = acs.merge(fcc, on="GEOID", how="inner")
    cols = ACS_COMPS + ["terr_unserved_pct"]
    a = comp.dropna(subset=cols).copy()
    z = (a[cols] - a[cols].mean()) / a[cols].std()
    a["cidx"] = z.mean(axis=1)
    med = float(a["cidx"].median())
    Pv = P.merge(a[["GEOID", "cidx"]], left_on="fips_tract",
                 right_on="GEOID", how="left")
    inv_c, dep_c = matrix_boxes(Pv, "cidx", med)
    save("table_2", variant_table(
        inv_c, dep_c, extra=[("Components index (z)", "cidx", 2)]))

    # ── Tables 3A / 3B: sub-scores ──────────────────────────────────────────
    inv_i, dep_i = matrix_boxes(P, "infa", anchors["nat_med_infa"])
    save("table_3A", variant_table(inv_i, dep_i, extra=[("INFA score", "infa", 1)]))
    inv_s, dep_s = matrix_boxes(P, "se", anchors["nat_med_se"])
    save("table_3B", variant_table(inv_s, dep_s, extra=[("SE score", "se", 1)]))

    # ── Table 4: all tracts ─────────────────────────────────────────────────
    inv_a, dep_a = matrix_boxes(tracts, "ddi", nat)
    save("table_4", variant_table(inv_a, dep_a,
                                  flag_primary=False, flag_pool=True))

    # ── Table 5: PCP workforce pool ─────────────────────────────────────────
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "primary_care", os.path.join(PROJECT_DIR, "sens_workforce_primary_care.py"))
    primary_care = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(primary_care)
    panel = pd.read_csv(primary_care.PANEL_FILE, dtype={"fips_st_cnty": str})
    cp = primary_care.pool_from_panel(panel, "PCP")
    pool_pcp = set(cp.loc[cp["in_pool"], "fips_st_cnty"])
    Pp = tracts[tracts["fips_county"].isin(pool_pcp)]
    inv_p, dep_p = matrix_boxes(Pp, "ddi", nat)
    save("table_5", variant_table(inv_p, dep_p))

    # ── Table 6: threshold grid ─────────────────────────────────────────────
    g = pd.read_csv(os.path.join(MASTER_DIR, "thresholds_grid.csv"))
    lab_b = {"mean": "Above mean (z > 0)", "p75": "Top 25% (z >= 0.43)",
             "p90": "Top 10% (z >= 0.91)"}
    lab_r = {"median": "Median split (18.8)",
             "p25_p75": "Quartile split (14.2 / 24.2)",
             "p10_p90": "Decile split (10.9 / 29.8)"}
    t6 = pd.DataFrame({
        "Burden cutoff": g["burden_cut"].map(lab_b),
        "Readiness cutoff": g["ready_cut"].map(lab_r),
        "Investment tracts": g["n_invest"].map("{:,}".format),
        "Deployment tracts": g["n_deploy"].map("{:,}".format),
        "Primary top-10 investment retained": g["base_inv_top10_surviving"].map(lambda x: f"{x}/10"),
        "Primary top-10 deployment retained": g["base_dep_top10_surviving"].map(lambda x: f"{x}/10"),
    })
    save("table_6", t6)

    # ── Table 7: 25-mile access pool ────────────────────────────────────────
    acc = pd.read_csv(os.path.join(MASTER_DIR, "workforce_distance_county_access.csv"),
                      dtype={"fips_st_cnty": str})
    pool_25 = set(acc.loc[acc["in_pool_25mi"], "fips_st_cnty"])
    P25 = tracts[tracts["fips_county"].isin(pool_25)]
    inv_f, dep_f = matrix_boxes(P25, "ddi", nat)
    save("table_7", variant_table(inv_f, dep_f))

    # ── Table 8: composite cardiologist + cardiology APP pool ───────────────
    app = pd.read_csv(os.path.join(MASTER_DIR, "dac_cardiology_app_county.csv"),
                      dtype={"fips_st_cnty": str})
    app["fips_st_cnty"] = app["fips_st_cnty"].str.zfill(5)
    cnty = (tracts.drop_duplicates("fips_county")
            [["fips_county", "card_last", "pool_declining"]]
            .merge(app, left_on="fips_county", right_on="fips_st_cnty", how="left"))
    cnty["n_app_site_strict"] = cnty["n_app_site_strict"].fillna(0)
    pool_g = set(cnty.loc[
        ((cnty["card_last"].fillna(0) + cnty["n_app_site_strict"]) == 0)
        | cnty["pool_declining"].fillna(False), "fips_county"])
    Pg = tracts[tracts["fips_county"].isin(pool_g)].copy()
    app_n = dict(zip(cnty["fips_county"], cnty["n_app_site_strict"].astype(int)))
    Pg["n_card_app"] = Pg["fips_county"].map(app_n).fillna(0).astype(int)
    inv_g, dep_g = matrix_boxes(Pg, "ddi", nat)
    save("table_8", variant_table(
        inv_g, dep_g, extra=[("Cardiology NP/PA in county", "n_card_app", 0)]))

    print(f"\nall tables -> {OUT}")


if __name__ == "__main__":
    main()
