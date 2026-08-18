"""
sens_workforce_primary_care.py
=============================
Additional analysis C2: rebuild the high-need county pool with OTHER
workforces from AHRF, then rerun the classification.

Workforces (county counts)
  PCP    phys_nf_prim_care_pc_exc_rsdt  MD+DO primary care, patient care,
                                        excl residents; years 2020-2023
  NP     np_npi                         nurse practitioners w/ NPI, 2021-2024
  PA     pa_npi                         physician assistants w/ NPI, 2021-2024
  NP_PA  np_npi + pa_npi                combined non-physician workforce

AHRF has no cardiology-specific NP/PA counts, so NP/PA totals proxy the
non-physician workforce. Windows are shorter than cardiology's 2010-2023;
the decline rule mirrors the main analysis on the years available: high-need = zero providers in the last year OR a
declining per-capita rate (OLS slope < 0 with the mean-count>=3 gate; small
counties use last-vs-first rate).

Year -> source (most recent release wins, mirroring fetch_workforce):
  2020: 2022-23 release | 2021: 2023-24 release | 2022+2023: 2024-25 release
  2024 (NP/PA only): 2024-25 release
Populations: popn_20/21 (2022-23 POP), popn_22/23 + popn_est_24 (2024-25 POP).

Outputs (outputs/master/)
  workforce_primary_care_county_panels.csv    county x year x workforce long panel (cached)
  workforce_primary_care_pools.csv            pool definition stats per workforce
  workforce_primary_care_comparison.csv       matrix comparison vs cardiology baseline
  workforce_primary_care_<wf>_INVEST_top.csv / _DEPLOY_top.csv, workforce_primary_care_state_shift.csv
"""
import os
import numpy as np
import pandas as pd

from build_master import (load_master, matrix_boxes, compare_runs,
                              state_mix, tidy, OUT_DIR, PROJECT_DIR)

AHRF_DIR = os.path.join(PROJECT_DIR, "AHRF")
HP_2023 = os.path.join(AHRF_DIR, "AHRF_CSV_2022-2023", "DATA",
                       "CSV Files by Categories", "ahrf2023HP.csv")
HP_2024 = os.path.join(AHRF_DIR, "AHRF 2023-2024 CSV",
                       "CSV Files by Categories", "ahrf2024hp.csv")
HP_2025 = os.path.join(AHRF_DIR, "NCHWA-2024-2025+AHRF+COUNTY+CSV", "AHRF2025hp.csv")
POP_2023 = os.path.join(AHRF_DIR, "AHRF_CSV_2022-2023", "DATA",
                        "CSV Files by Categories", "ahrf2023POP.csv")
POP_2025 = os.path.join(AHRF_DIR, "NCHWA-2024-2025+AHRF+COUNTY+CSV", "AHRF2025pop.csv")

PANEL_FILE = os.path.join(OUT_DIR, "workforce_primary_care_county_panels.csv")

# workforce -> (AHRF base column, {year: source file})
WF_DEFS = {
    "PCP":   ("phys_nf_prim_care_pc_exc_rsdt",
              {2020: HP_2023, 2021: HP_2024, 2022: HP_2025, 2023: HP_2025}),
    "NP":    ("np_npi",
              {2021: HP_2023, 2022: HP_2024, 2023: HP_2025, 2024: HP_2025}),
    "PA":    ("pa_npi",
              {2021: HP_2023, 2022: HP_2024, 2023: HP_2025, 2024: HP_2025}),
}
MIN_COUNT, MIN_YEARS = 3, 3
TOP_N = 10


def _read_cols(path, cols):
    df = pd.read_csv(path, low_memory=False)
    df.columns = [c.strip('"').strip() for c in df.columns]
    keep = ["fips_st_cnty"] + [c for c in cols if c in df.columns]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        print(f"  [warn] {os.path.basename(path)} missing {missing}")
    df = df[keep].copy()
    df["fips_st_cnty"] = df["fips_st_cnty"].astype(str).str.strip('"').str.zfill(5)
    for c in keep[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def build_panel():
    """County x year x workforce long panel with per-100k rates."""
    # populations
    pop23 = _read_cols(POP_2023, ["popn_20", "popn_21"])
    pop25 = _read_cols(POP_2025, ["popn_22", "popn_23", "popn_est_24"])
    pop_long = []
    for yr, (src, col) in {2020: (pop23, "popn_20"), 2021: (pop23, "popn_21"),
                           2022: (pop25, "popn_22"), 2023: (pop25, "popn_23"),
                           2024: (pop25, "popn_est_24")}.items():
        pop_long.append(src[["fips_st_cnty", col]]
                        .rename(columns={col: "pop"}).assign(year=yr))
    pop_long = pd.concat(pop_long, ignore_index=True)

    frames = []
    for wf, (base, year_src) in WF_DEFS.items():
        by_file = {}
        for yr, path in year_src.items():
            by_file.setdefault(path, []).append(yr)
        for path, yrs in by_file.items():
            cols = [f"{base}_{str(y)[-2:]}" for y in yrs]
            d = _read_cols(path, cols)
            for y in yrs:
                col = f"{base}_{str(y)[-2:]}"
                if col not in d.columns:
                    continue
                frames.append(d[["fips_st_cnty", col]]
                              .rename(columns={col: "count"})
                              .assign(year=y, workforce=wf))
    panel = pd.concat(frames, ignore_index=True)
    panel = panel[panel["fips_st_cnty"].str.fullmatch(r"\d{5}")]

    # NP + PA combined
    npa = (panel[panel["workforce"].isin(["NP", "PA"])]
           .pivot_table(index=["fips_st_cnty", "year"], columns="workforce",
                        values="count", aggfunc="first").reset_index())
    npa["count"] = npa[["NP", "PA"]].sum(axis=1, min_count=1)
    npa = npa[["fips_st_cnty", "year", "count"]].assign(workforce="NP_PA")
    panel = pd.concat([panel, npa], ignore_index=True)

    panel = panel.merge(pop_long, on=["fips_st_cnty", "year"], how="left")
    panel["rate_100k"] = np.where(panel["pop"] > 0,
                                  panel["count"] / panel["pop"] * 1e5, np.nan)
    return panel


def pool_from_panel(panel, wf):
    """Mirror the cardiology rule: zero in last year OR declining per-capita."""
    d = panel[panel["workforce"] == wf].dropna(subset=["count"])
    recs = []
    for fips, g in d.groupby("fips_st_cnty"):
        g = g.sort_values("year")
        count_last = float(g["count"].iloc[-1])
        mean_count = g["count"].mean()
        gr = g.dropna(subset=["rate_100k"])
        slope = np.nan
        if len(gr) >= MIN_YEARS and mean_count >= MIN_COUNT:
            slope, _ = np.polyfit(gr["year"].astype(float), gr["rate_100k"], 1)
        declining = (
            (not np.isnan(slope) and slope < 0) or
            (mean_count < MIN_COUNT and len(gr) >= 2
             and gr["rate_100k"].iloc[-1] < gr["rate_100k"].iloc[0]))
        recs.append({"fips_st_cnty": fips, "count_last": count_last,
                     "slope_pc": slope,
                     "pool_zero": count_last == 0,
                     "pool_declining": count_last > 0 and declining})
    out = pd.DataFrame(recs)
    out["in_pool"] = out["pool_zero"] | out["pool_declining"]
    return out


def main():
    tracts, anchors = load_master()
    base = tracts.dropna(subset=["burden_z", "ddi"]).copy()
    P_ref = tracts[tracts["in_pool"]]
    inv_ref, dep_ref = matrix_boxes(P_ref, "ddi", anchors["nat_med_ddi"])
    card_pool = set(tracts.loc[tracts["in_pool"], "fips_county"])

    if os.path.exists(PANEL_FILE):
        panel = pd.read_csv(PANEL_FILE, dtype={"fips_st_cnty": str})
        print(f"loaded cached panel: {PANEL_FILE}")
    else:
        panel = build_panel()
        panel.to_csv(PANEL_FILE, index=False)
        print(f"built panel -> {PANEL_FILE}")

    print("=" * 78)
    print("alternative workforces (pool redefined, matrix unchanged)")
    print("=" * 78)
    print(f"cardiology baseline: pool {len(card_pool):,} counties | "
          f"INVEST {len(inv_ref):,} | DEPLOY {len(dep_ref):,}")

    pool_rows, cmp_rows, mixes = [], [], []
    for wf in ["PCP", "NP", "PA", "NP_PA"]:
        cp = pool_from_panel(panel, wf)
        pool_set = set(cp.loc[cp["in_pool"], "fips_st_cnty"])
        jac = len(pool_set & card_pool) / len(pool_set | card_pool)
        pool_rows.append({
            "workforce": wf, "n_counties_pool": len(pool_set),
            "n_zero": int(cp["pool_zero"].sum()),
            "n_declining": int(cp["pool_declining"].sum()),
            "overlap_with_card_pool": len(pool_set & card_pool),
            "jaccard_vs_card_pool": round(jac, 3)})

        Pw = tracts[tracts["fips_county"].isin(pool_set)]
        inv_w, dep_w = matrix_boxes(Pw, "ddi", anchors["nat_med_ddi"])
        cmp_ = compare_runs(base, inv_ref, dep_ref, inv_w, dep_w)
        cmp_rows.append({"workforce": wf, **cmp_})
        print(f"\n[{wf}] pool {len(pool_set):,} counties "
              f"(zero {pool_rows[-1]['n_zero']:,}, declining {pool_rows[-1]['n_declining']:,}); "
              f"jaccard vs cardiology {jac:.2f}")
        print(f"  INVEST {len(inv_w):,} DEPLOY {len(dep_w):,} | "
              f"baseline INVEST retained {cmp_['invest_retained_pct']}% "
              f"DEPLOY retained {cmp_['deploy_retained_pct']}% | "
              f"top10 overlap INV {cmp_['inv_top10_overlap']}/10 "
              f"DEP {cmp_['dep_top10_overlap']}/10")
        tidy(inv_w).head(TOP_N).to_csv(
            os.path.join(OUT_DIR, f"workforce_primary_care_{wf}_INVEST_top.csv"), index=False)
        tidy(dep_w).head(TOP_N).to_csv(
            os.path.join(OUT_DIR, f"workforce_primary_care_{wf}_DEPLOY_top.csv"), index=False)
        for lab, box in [(f"{wf}_INVEST", inv_w), (f"{wf}_DEPLOY", dep_w)]:
            mixes.append(state_mix(box).head(8).rename_axis("state")
                         .reset_index().assign(run=lab))

    pd.DataFrame(pool_rows).to_csv(os.path.join(OUT_DIR, "workforce_primary_care_pools.csv"), index=False)
    pd.DataFrame(cmp_rows).to_csv(os.path.join(OUT_DIR, "workforce_primary_care_comparison.csv"), index=False)
    pd.concat(mixes, ignore_index=True).to_csv(
        os.path.join(OUT_DIR, "workforce_primary_care_state_shift.csv"), index=False)
    print(f"\nwritten -> {OUT_DIR}/workforce_primary_care_*")


if __name__ == "__main__":
    main()
