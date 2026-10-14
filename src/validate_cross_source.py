"""
validate_cross_source.py
========================
Cross-source agreement for each of the three inputs.

For every input the question is the same: rebuild it from a different source
or vintage, report how well the two measures agree, then swap the rebuilt
measure into the classification and report how many labels survive. Two of
the three comparisons are computed by other scripts and gathered here; the
third (burden) and the readiness gradient are computed in this file.

  workforce   AHRF (AMA Masterfile) against CMS Doctors and Clinicians,
              from validate_workforce_source.py
  readiness   the Divide Index against an index rebuilt from six ACS
              indicators, from sens_readiness_components.py; plus a gradient
              check against two sources the index does not use at these
              vintages, the FCC Broadband Data Collection share of locations
              without terrestrial 100/20 Mbps service and the ACS shares of
              households without an internet subscription and without a
              computer, by quintile of the Divide Index
  burden      PLACES 2025 (BRFSS 2023) against PLACES 2023 (BRFSS 2021)
              crosswalked to 2020 tracts by sens_burden_kypa_crosswalk.py,
              restandardized across analyzed tracts, in the states where
              the 2023 release reported all ten measures

Run validate_workforce_source.py, sens_readiness_components.py and
sens_burden_kypa_crosswalk.py first.

Outputs (outputs/master/)
  cross_source_summary.csv       one row per comparison
  cross_source_readiness_gradient.csv
  cross_source_summary.md
"""
import os

import numpy as np
import pandas as pd

from build_master import (load_master, matrix_boxes, compare_runs, rank_eligible,
                          corr_with_ci, spearman, acs_components, fcc_availability,
                          markdown_table, OUT_DIR)

MIN_LOCATIONS = 20          # FCC availability is noisy below this
LOG = []


def log(s=""):
    print(s)
    LOG.append(s)


def need(name):
    f = os.path.join(OUT_DIR, name)
    if not os.path.exists(f):
        raise SystemExit(f"{name} missing; see the docstring for the scripts to run first")
    return f


def main():
    tracts, anchors = load_master()
    cut = float(anchors["nat_med_ddi"])
    base = tracts.dropna(subset=["burden_z", "ddi"]).drop_duplicates("fips_tract").copy()
    inv_ref, dep_ref = matrix_boxes(base[base["in_pool"]], "ddi", cut)
    rows = []

    # workforce: gathered from validate_workforce_source
    corr = pd.read_csv(need("workforce_source_correlation.csv")).set_index("measure")
    pres = pd.read_csv(need("workforce_source_presence.csv"))
    swap = pd.read_csv(need("workforce_source_pool_swap.csv")).set_index("pool")
    pa = pres[(pres["group"] == "All") & (pres["cms_rule"] == "primary")].iloc[0]
    sw = swap.loc["CMS zero arm"]
    cw = corr.loc["counts"]
    rows.append({
        "input": "Cardiology workforce",
        "primary source": "HRSA Area Health Resources Files 2023 (AMA Masterfile)",
        "comparison source": "CMS Doctors and Clinicians national file (Medicare enrollment)",
        "unit": f"{int(cw['n']):,} counties",
        "measure agreement": (f"county counts r = {cw['pearson']:.3f} "
                              f"(95% CI {cw['pearson_ci_low']:.3f} to {cw['pearson_ci_high']:.3f}; "
                              f"population-weighted {cw['pop_weighted_pearson']:.3f}); "
                              f"presence agreement {pa['pct_agree']:.1f}%, kappa {pa['kappa']:.2f}"),
        "box agreement %": sw["box_agree_pct"],
        "investment retained %": sw["invest_retained_pct"],
        "deployment retained %": sw["deploy_retained_pct"],
        "top-10 overlap": f"{int(sw['inv_top10_overlap'])} and {int(sw['dep_top10_overlap'])} of 10",
        "computed by": "validate_workforce_source.py"})

    # readiness: gathered from sens_readiness_components
    a = pd.read_csv(need("readiness_components_comparison.csv")).set_index("variant")
    r6, r7 = a.loc["ACS_6"], a.loc["ACS_6_plus_FCC_7"]
    rows.append({
        "input": "Digital readiness",
        "primary source": "Purdue Digital Divide Index, 2022 vintage",
        "comparison source": "Index rebuilt from six ACS 2020-2024 indicators "
                             "(and with FCC availability as a seventh)",
        "unit": f"{int(r6['n_tracts']):,} pool tracts",
        "measure agreement": (f"r = {r6['pearson_r']:.3f} (95% CI {r6['pearson_ci_low']:.3f} "
                              f"to {r6['pearson_ci_high']:.3f}) with six ACS indicators; "
                              f"{r7['pearson_r']:.3f} with FCC added"),
        "box agreement %": r6["box_agree_pct"],
        "investment retained %": r6["invest_retained_pct"],
        "deployment retained %": r6["deploy_retained_pct"],
        "top-10 overlap": f"{int(r6['inv_top10_overlap'])} and {int(r6['dep_top10_overlap'])} of 10 "
                          f"({r7['box_agree_pct']:.1f}% agreement with FCC)",
        "computed by": "sens_readiness_components.py"})

    # readiness gradient against FCC availability and ACS adoption
    R = (base.merge(fcc_availability()[["GEOID", "n_locations", "terr_unserved_pct"]],
                    left_on="fips_tract", right_on="GEOID", how="left").drop(columns="GEOID")
             .merge(acs_components()[["GEOID", "no_internet_pct", "no_computer_pct"]],
                    left_on="fips_tract", right_on="GEOID", how="left").drop(columns="GEOID"))
    R = R[R["n_locations"].fillna(0) >= MIN_LOCATIONS]
    log(f"Readiness gradient: {len(R):,} analyzed tracts with at least "
        f"{MIN_LOCATIONS} broadband serviceable locations")
    rho = {}
    for y, lab in (("terr_unserved_pct", "FCC unserved share"),
                   ("no_internet_pct", "ACS no-internet share"),
                   ("no_computer_pct", "ACS no-computer share")):
        s = R.dropna(subset=[y])
        rho[lab] = tuple(round(spearman(s[c], s[y]), 3)
                         for c in ("ddi", "infa", "se"))
        log(f"  Spearman with {lab}: DDI {rho[lab][0]:.3f}, INFA {rho[lab][1]:.3f}, "
            f"SE {rho[lab][2]:.3f}")
    R["ddi_quintile"] = pd.qcut(R["ddi"], 5, labels=["Q1 (most ready)", "Q2", "Q3", "Q4",
                                                      "Q5 (least ready)"])
    grad = (R.groupby("ddi_quintile", observed=True)
              .agg(tracts=("fips_tract", "size"), ddi_median=("ddi", "median"),
                   fcc_unserved_mean_pct=("terr_unserved_pct", lambda s: 100 * s.mean()),
                   fcc_unserved_median_pct=("terr_unserved_pct", lambda s: 100 * s.median()),
                   pct_tracts_over_10pct_unserved=("terr_unserved_pct",
                                                   lambda s: 100 * (s > 0.10).mean()),
                   acs_no_internet_mean_pct=("no_internet_pct", lambda s: 100 * s.mean()),
                   acs_no_internet_median_pct=("no_internet_pct", lambda s: 100 * s.median()),
                   acs_no_computer_mean_pct=("no_computer_pct", lambda s: 100 * s.mean()),
                   acs_no_computer_median_pct=("no_computer_pct", lambda s: 100 * s.median()))
              .round(1))
    grad.to_csv(os.path.join(OUT_DIR, "cross_source_readiness_gradient.csv"))
    log("\nBy quintile of the Divide Index:")
    log(markdown_table(grad))
    q1, q5 = grad.iloc[0], grad.iloc[-1]
    rows.append({
        "input": "Digital readiness",
        "primary source": "Purdue Digital Divide Index, 2022 vintage",
        "comparison source": "FCC Broadband Data Collection, December 2024 (locations without "
                             "terrestrial 100/20 Mbps); ACS 2020-2024 households without an "
                             "internet subscription or a computer",
        "unit": f"{len(R):,} analyzed tracts",
        "measure agreement": (
            f"mean FCC unserved share {q1['fcc_unserved_mean_pct']:.1f}% in the most-ready "
            f"quintile to {q5['fcc_unserved_mean_pct']:.1f}% in the least-ready; tracts with "
            f">10% unserved {q1['pct_tracts_over_10pct_unserved']:.1f}% to "
            f"{q5['pct_tracts_over_10pct_unserved']:.1f}%; households without internet "
            f"{q1['acs_no_internet_median_pct']:.1f}% to {q5['acs_no_internet_median_pct']:.1f}% "
            f"(Spearman with DDI {rho['ACS no-internet share'][0]:.2f}); without a computer "
            f"{q1['acs_no_computer_median_pct']:.1f}% to {q5['acs_no_computer_median_pct']:.1f}%"),
        "box agreement %": np.nan, "investment retained %": np.nan,
        "deployment retained %": np.nan,
        "top-10 overlap": "not a composite; gradient only",
        "computed by": "validate_cross_source.py"})

    # burden: PLACES 2025 against the crosswalked 2023 release, full-measure states only
    b23 = pd.read_csv(need("places2023_burden_2020tracts.csv"), dtype={"t20": str})
    b23["t20"] = b23["t20"].str.zfill(11)
    B = base.merge(b23, left_on="fips_tract", right_on="t20", how="left").drop(columns="t20")
    st = B["fips_tract"].str[:2]
    B.loc[st.isin(["21", "42", "12"]), "b23"] = np.nan      # KY, PA, FL lacked full measures
    ok = B["b23"].notna()
    B["burden_alt"] = (B["b23"] - B.loc[ok, "b23"].mean()) / B.loc[ok, "b23"].std()
    pool_ok = ok & B["in_pool"]
    cc = corr_with_ci(B.loc[pool_ok, "burden_z"], B.loc[pool_ok, "burden_alt"])
    rho_b = spearman(B.loc[pool_ok, "burden_z"], B.loc[pool_ok, "burden_alt"])
    log(f"\nBurden rebuilt from the 2023 release: {int(ok.sum()):,} analyzed tracts outside "
        f"KY, PA and FL; {cc['n']:,} pool tracts; r = {cc['r']:.3f} "
        f"(95% CI {cc['ci_low']:.3f} to {cc['ci_high']:.3f}), rho = {rho_b:.3f}")
    Pb = B[pool_ok].copy()
    inv_same, dep_same = matrix_boxes(Pb, "ddi", cut)       # primary burden, same tracts
    Pb_alt = Pb.drop(columns="burden_z").rename(columns={"burden_alt": "burden_z"})
    inv_alt, dep_alt = matrix_boxes(Pb_alt, "ddi", cut)
    cmp_b = compare_runs(B[ok], inv_same, dep_same, inv_alt, dep_alt)
    ie, ia = rank_eligible(inv_same), rank_eligible(inv_alt)
    de, da = rank_eligible(dep_same), rank_eligible(dep_alt)
    t10i = len(set(ie.fips_tract.head(10)) & set(ia.fips_tract.head(10)))
    t10d = len(set(de.fips_tract.head(10)) & set(da.fips_tract.head(10)))
    log(f"  classification on the same tracts: investment {len(inv_same):,} -> {len(inv_alt):,}; "
        f"deployment {len(dep_same):,} -> {len(dep_alt):,}; agreement {cmp_b['box_agree_pct']}%; "
        f"retention {cmp_b['invest_retained_pct']}% / {cmp_b['deploy_retained_pct']}%; "
        f"top-10 overlap {t10i} / {t10d}")
    rows.append({
        "input": "Cardiometabolic burden",
        "primary source": "CDC PLACES 2025 release (BRFSS 2023)",
        "comparison source": "CDC PLACES 2023 release (BRFSS 2021), crosswalked from 2010 to "
                             "2020 tracts",
        "unit": f"{cc['n']:,} pool tracts outside KY, PA and FL",
        "measure agreement": (f"r = {cc['r']:.3f} (95% CI {cc['ci_low']:.3f} to "
                              f"{cc['ci_high']:.3f}), Spearman {rho_b:.3f}"),
        "box agreement %": cmp_b["box_agree_pct"],
        "investment retained %": cmp_b["invest_retained_pct"],
        "deployment retained %": cmp_b["deploy_retained_pct"],
        "top-10 overlap": f"{t10i} and {t10d} of 10",
        "computed by": "validate_cross_source.py"})

    S = pd.DataFrame(rows)
    S.to_csv(os.path.join(OUT_DIR, "cross_source_summary.csv"), index=False)
    log("\nSummary")
    log(markdown_table(S.set_index("input")))
    with open(os.path.join(OUT_DIR, "cross_source_summary.md"), "w") as fh:
        fh.write("# Cross-source agreement\n\n" + "\n".join(LOG) + "\n")
    print(f"\nwritten -> {OUT_DIR}/cross_source_*")


if __name__ == "__main__":
    main()
