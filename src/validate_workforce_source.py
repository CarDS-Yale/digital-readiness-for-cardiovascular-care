"""
validate_workforce_source.py
============================
Do two independent rosters place cardiologists in the same counties?

The primary workforce measure is the AHRF count of non-federal cardiovascular
disease physicians, which derives from the AMA Physician Masterfile. The CMS
Doctors and Clinicians national file lists Medicare-enrolled clinicians with
a practice address instead. This script compares the two at the county level
and then rebuilds the workforce-constrained pool with the CMS count in the
zero-cardiologist arm (the declining arm stays with AHRF, since the CMS file
has no history).

County assignment of CMS clinicians follows sens_workforce_endocrinology.py,
whose cached extract this script reuses: one county per NPI, by practice ZIP
through the ZCTA-county relationship file. An any-site variant counts a
clinician in every county where they list an address.

Checks
  1. national totals and the CMS to AHRF ratio
  2. county agreement: Pearson, Spearman, log, population-weighted
     correlations and Lin's concordance on log counts
  3. presence or absence of any cardiologist: 2x2 counts, percent agreement
     and Cohen's kappa, overall and by county class
  4. calibration by AHRF size band
  5. the pool swap, reported with box agreement, retention and top-10 overlap

Outputs (outputs/master/)
  workforce_source_correlation.csv, workforce_source_presence.csv,
  workforce_source_calibration.csv, workforce_source_pool_swap.csv,
  workforce_source_county.csv, workforce_source_summary.md
"""
import os

import numpy as np
import pandas as pd

from build_master import (load_master, matrix_boxes, compare_runs, rank_eligible,
                          corr_with_ci, spearman, nchs_classes, markdown_table, OUT_DIR)
from sens_workforce_endocrinology import clinician_counts


def wpearson(x, y, w):
    w = w / w.sum()
    mx, my = (w * x).sum(), (w * y).sum()
    return ((w * (x - mx) * (y - my)).sum()
            / np.sqrt((w * (x - mx) ** 2).sum() * (w * (y - my) ** 2).sum()))


def lin_ccc(x, y):
    mx, my = x.mean(), y.mean()
    return 2 * ((x - mx) * (y - my)).mean() / (x.var(ddof=0) + y.var(ddof=0) + (mx - my) ** 2)


def kappa(a, b):
    po = (a == b).mean()
    pe = a.mean() * b.mean() + (1 - a.mean()) * (1 - b.mean())
    return (po - pe) / (1 - pe)


def main():
    tracts, anchors = load_master()
    counts, qc = clinician_counts()
    c = (tracts.drop_duplicates("fips_county")
         [["fips_county", "county_state", "card_last", "card_per_100k_last",
           "county_pop_last", "pool_nocard", "pool_declining", "in_pool"]].copy())
    c = c[c["card_last"].notna() & c["county_pop_last"].notna()].copy()
    c["cms"] = c["fips_county"].map(counts["card"]).fillna(0)
    c["cms_any"] = c["fips_county"].map(counts["card_anysite"]).fillna(0)
    c["ahrf"] = c["card_last"]
    c["cms_pc"] = c["cms"] / c["county_pop_last"] * 1e5
    c["ahrf_pc"] = c["ahrf"] / c["county_pop_last"] * 1e5
    c = c.merge(nchs_classes(), left_on="fips_county", right_on="fips_st_cnty",
                how="left").drop(columns="fips_st_cnty")
    c["class_group"] = np.select([c["nchs_code"] <= 2, c["nchs_code"] <= 4],
                                 ["Large metro", "Small or medium metro"], "Nonmetro")
    c.loc[c["nchs_code"].isna(), "class_group"] = "Unclassified"

    L = ["# AHRF versus CMS cardiologist counts", "",
         "Script: validate_workforce_source.py", ""]

    # 1. totals
    tot = {"counties": len(c), "ahrf_total_2023": int(c["ahrf"].sum()),
           "cms_total_assigned": int(c["cms"].sum()),
           "cms_npi_national": qc["card_npi"],
           "ratio_cms_to_ahrf": round(c["cms"].sum() / c["ahrf"].sum(), 3)}
    print("1. totals", tot)
    L += ["## 1. National totals", ""] + [f"- {k}: {v:,}" if isinstance(v, int)
                                         else f"- {k}: {v}" for k, v in tot.items()] + [""]

    # 2. correlations
    rows = []
    for lab, x, y in [("counts", c["cms"], c["ahrf"]),
                      ("per 100,000", c["cms_pc"], c["ahrf_pc"]),
                      ("counts, CMS any site", c["cms_any"], c["ahrf"])]:
        cc = corr_with_ci(x, y)
        rows.append({"measure": lab, "n": cc["n"], "pearson": cc["r"],
                     "pearson_ci_low": cc["ci_low"], "pearson_ci_high": cc["ci_high"],
                     "spearman": round(spearman(x, y), 3),
                     "pearson_log1p": round(np.log1p(x).corr(np.log1p(y)), 3),
                     "pop_weighted_pearson": round(wpearson(x, y, c["county_pop_last"]), 3),
                     "lin_ccc_log1p": round(lin_ccc(np.log1p(x), np.log1p(y)), 3)})
    for g, s in c.groupby("class_group"):
        rows.append({"measure": f"per 100,000, {g}", "n": len(s),
                     "pearson": round(s["cms_pc"].corr(s["ahrf_pc"]), 3),
                     "spearman": round(spearman(s["cms_pc"], s["ahrf_pc"]), 3),
                     "pearson_log1p": round(np.log1p(s["cms_pc"]).corr(np.log1p(s["ahrf_pc"])), 3),
                     "pop_weighted_pearson": round(wpearson(s["cms_pc"], s["ahrf_pc"],
                                                            s["county_pop_last"]), 3),
                     "lin_ccc_log1p": round(lin_ccc(np.log1p(s["cms"]), np.log1p(s["ahrf"])), 3)})
    corr = pd.DataFrame(rows)
    corr.to_csv(os.path.join(OUT_DIR, "workforce_source_correlation.csv"), index=False)
    print(corr.to_string(index=False))
    L += ["## 2. County agreement", "", markdown_table(corr.set_index("measure"), ".3f"), ""]

    # 3. presence or absence
    pa = []
    for g, s in [("All", c)] + list(c.groupby("class_group")):
        for lab, col in [("primary", "cms"), ("any site", "cms_any")]:
            a0, d0 = s["ahrf"] == 0, s[col] == 0
            pa.append({"group": g, "cms_rule": lab, "n": len(s),
                       "both_zero": int((a0 & d0).sum()),
                       "ahrf_zero_cms_some": int((a0 & ~d0).sum()),
                       "ahrf_some_cms_zero": int((~a0 & d0).sum()),
                       "both_some": int((~a0 & ~d0).sum()),
                       "pct_agree": round((a0 == d0).mean() * 100, 1),
                       "kappa": round(kappa(a0.astype(float), d0.astype(float)), 3)})
    pa = pd.DataFrame(pa)
    pa.to_csv(os.path.join(OUT_DIR, "workforce_source_presence.csv"), index=False)
    print(pa.to_string(index=False))
    L += ["## 3. Presence or absence of any cardiologist", "",
          markdown_table(pa.set_index("group"), ".3f"), ""]
    d1 = c[(c["ahrf"] == 0) & (c["cms"] > 0)]
    d2 = c[(c["ahrf"] > 0) & (c["cms"] == 0)]
    disc = {"n_ahrf_zero_cms_some": len(d1),
            "median_cms_in_those": float(d1["cms"].median()),
            "pct_with_1_or_2_cms": round((d1["cms"] <= 2).mean() * 100, 1),
            "n_ahrf_some_cms_zero": len(d2),
            "median_ahrf_in_those": float(d2["ahrf"].median()),
            "pct_with_1_or_2_ahrf": round((d2["ahrf"] <= 2).mean() * 100, 1)}
    print(disc)
    L += ["Discordant counties:", ""] + [f"- {k}: {v}" for k, v in disc.items()] + [""]

    # 4. calibration by size band
    bands = pd.cut(c["ahrf"], [-0.1, 0, 2, 9, 49, 1e9],
                   labels=["0", "1-2", "3-9", "10-49", "50+"])
    cal = []
    for band, s in c.assign(band=bands).groupby("band", observed=True):
        ratio = (s["cms"] / s["ahrf"]).replace(np.inf, np.nan)
        cal.append({"ahrf_band": str(band), "counties": len(s),
                    "ahrf_sum": int(s["ahrf"].sum()), "cms_sum": int(s["cms"].sum()),
                    "ratio_of_sums": round(s["cms"].sum() / max(s["ahrf"].sum(), 1), 2),
                    "median_county_ratio": round(ratio.median(), 2)
                                           if (s["ahrf"] > 0).all() else np.nan})
    cal = pd.DataFrame(cal)
    cal.to_csv(os.path.join(OUT_DIR, "workforce_source_calibration.csv"), index=False)
    print(cal.to_string(index=False))
    L += ["## 4. Calibration by AHRF size band", "",
          markdown_table(cal.set_index("ahrf_band"), ".2f"), ""]

    # 5. pool swap
    base = tracts.dropna(subset=["burden_z", "ddi"]).copy()
    cut = anchors["nat_med_ddi"]
    inv_r, dep_r = matrix_boxes(tracts[tracts["in_pool"]], "ddi", cut)
    ref_pool = set(c.loc[c["in_pool"].astype(bool), "fips_county"])
    dec = set(c.loc[c["pool_declining"].astype(bool), "fips_county"])
    out = []
    for lab, col in [("CMS zero arm", "cms"), ("CMS zero arm, any site", "cms_any")]:
        ps = set(c.loc[c[col] == 0, "fips_county"]) | dec
        inv_w, dep_w = matrix_boxes(tracts[tracts["fips_county"].isin(ps)], "ddi", cut)
        cmp_ = compare_runs(base, inv_r, dep_r, inv_w, dep_w)
        ie, de, ire, dre = map(rank_eligible, (inv_w, dep_w, inv_r, dep_r))
        cmp_["inv_top10_overlap"] = len(set(ire.fips_tract.head(10)) & set(ie.fips_tract.head(10)))
        cmp_["dep_top10_overlap"] = len(set(dre.fips_tract.head(10)) & set(de.fips_tract.head(10)))
        out.append({"pool": lab, "n_counties": len(ps),
                    "jaccard_vs_primary": round(len(ps & ref_pool) / len(ps | ref_pool), 3),
                    **cmp_})
    sw = pd.DataFrame(out)
    sw.to_csv(os.path.join(OUT_DIR, "workforce_source_pool_swap.csv"), index=False)
    show = ["pool", "n_counties", "jaccard_vs_primary", "n_invest_new", "n_deploy_new",
            "box_agree_pct", "invest_retained_pct", "deploy_retained_pct",
            "inv_top10_overlap", "dep_top10_overlap"]
    print(sw[show].to_string(index=False))
    L += ["## 5. Pool with the CMS count in the zero arm (declining arm from AHRF)", "",
          markdown_table(sw[show].set_index("pool")), ""]

    c.to_csv(os.path.join(OUT_DIR, "workforce_source_county.csv"), index=False)
    with open(os.path.join(OUT_DIR, "workforce_source_summary.md"), "w") as fh:
        fh.write("\n".join(L))
    print(f"\nwritten -> {OUT_DIR}/workforce_source_*")


if __name__ == "__main__":
    main()
