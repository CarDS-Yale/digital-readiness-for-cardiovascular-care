"""
sens_workforce_endocrinology.py
===============================
Sensitivity: count endocrinologists alongside cardiologists.

The burden measure spans cardiometabolic conditions, so a workforce screen
built on cardiologists alone might miss counties where endocrinologists
carry that care. The Area Health Resources Files have no endocrinology
field (it sits inside the internal-medicine subspecialty total), so
endocrinologists come from the CMS Doctors and Clinicians national file,
primary specialty ENDOCRINOLOGY. That file is a single snapshot of
Medicare-enrolled clinicians, which means endocrinology can only enter the
zero-workforce arm; the declining arm keeps the AHRF cardiology trend.

Clinician to county: ZIP5 treated as a ZCTA, ZCTA mapped to the county with
the largest land overlap, one county per NPI (first listed practice row).
This is the same rule process_clinicians.py applies to NPs and PAs. The raw
file (~840 MB) is pre-filtered with grep to rows mentioning ENDOCRIN or
CARDI, which takes seconds, and the extract is cached.

Parts
  (a) county endocrinologists per 100,000 against cardiologists per 100,000
  (b) joint absence: how often a county lacks both specialties
  (c) pool variants, classified at the national-median DDI anchor:
        joint_absence   no cardiologist AND no endocrinologist, or declining
                        cardiology per capita  (the reported variant)
        union           cardiology pool OR no endocrinologist
        intersection    cardiology pool AND no endocrinologist
        endocrinology   no endocrinologist alone, for reference
      Each reports pool size, Jaccard overlap with the cardiology pool, box
      agreement, retention and top-N overlap on the rank-eligible lists.

Outputs (outputs/master/)
  workforce_endocrinology_county.csv      county counts, rates, flags
  workforce_endocrinology_correlation.csv
  workforce_endocrinology_joint_absence.csv
  workforce_endocrinology_comparison.csv  one row per pool variant
  workforce_endocrinology_<variant>_INVEST_top.csv / _DEPLOY_top.csv
  workforce_endocrinology_summary.md
"""
import os
import subprocess

import numpy as np
import pandas as pd

from build_master import (load_master, matrix_boxes, compare_runs, rank_eligible,
                          spearman, tidy, markdown_table, OUT_DIR, PROJECT_DIR)

DAC_FILE = os.path.join(PROJECT_DIR, "DAC_CMS", "DAC_NationalDownloadableFile.csv")
ZCTA_FILE = os.path.join(PROJECT_DIR, "DAC_CMS", "tab20_zcta520_county20_natl.txt")
EXTRACT = os.path.join(OUT_DIR, "dac_endocrinology_cardiology_extract.csv.gz")
KEEP = ["NPI", "pri_spec", "sec_spec_all", "ZIP Code", "State", "adrs_id",
        "org_pac_id"]
TOP_N = 10


def build_extract():
    """Keep only rows that mention either specialty, then parse those."""
    for f in (DAC_FILE, ZCTA_FILE):
        if not os.path.exists(f):
            raise SystemExit(f"{f} missing. Run fetch_clinicians.py first.")
    tmp = EXTRACT.replace(".csv.gz", "_raw.csv")
    with open(tmp, "w") as fh:
        subprocess.run(["head", "-1", DAC_FILE], stdout=fh, check=True)
    with open(tmp, "a") as fh:
        subprocess.run(["grep", "-E", "ENDOCRIN|CARDI", DAC_FILE], stdout=fh,
                       check=True, env={**os.environ, "LC_ALL": "C"})
    d = pd.read_csv(tmp, dtype=str, usecols=KEEP)
    d.to_csv(EXTRACT, index=False, compression="gzip")
    os.remove(tmp)


def zip_to_county():
    z = pd.read_csv(ZCTA_FILE, sep="|", dtype=str).dropna(subset=["GEOID_ZCTA5_20"])
    z["_a"] = pd.to_numeric(z["AREALAND_PART"], errors="coerce").fillna(0)
    z = z.sort_values("_a", ascending=False).drop_duplicates("GEOID_ZCTA5_20")
    return dict(zip(z["GEOID_ZCTA5_20"].str.zfill(5), z["GEOID_COUNTY_20"].str.zfill(5)))


def clinician_counts():
    """County counts of endocrinologists and (for comparison) cardiologists in the CMS file.

    Returns a dict of Series keyed by county FIPS: endo, card, and the
    any-site variants that count a clinician in every county where they list
    a practice address.
    """
    if not os.path.exists(EXTRACT):
        build_extract()
    d = pd.read_csv(EXTRACT, dtype=str)
    d["pri_spec"] = d["pri_spec"].str.strip().str.upper()
    d["zip5"] = d["ZIP Code"].str.extract(r"(\d{5})")[0]
    d["fips"] = d["zip5"].map(zip_to_county())
    is_endo = d["pri_spec"].eq("ENDOCRINOLOGY")
    # cardiology = CARDI* minus surgery, as in process_clinicians.py
    is_card = (d["pri_spec"].str.contains("CARDI", na=False)
               & ~d["pri_spec"].str.contains("SURG", na=False))
    qc = {"endo_npi": int(d.loc[is_endo, "NPI"].nunique()),
          "card_npi": int(d.loc[is_card, "NPI"].nunique()),
          "endo_zip_unmapped_pct": round(d.loc[is_endo, "fips"].isna().mean() * 100, 1)}
    out = {}
    for lab, m in [("endo", is_endo), ("card", is_card)]:
        x = d[m].dropna(subset=["fips"])
        out[lab] = x.drop_duplicates("NPI")["fips"].value_counts()
        out[lab + "_anysite"] = x.drop_duplicates(["NPI", "fips"])["fips"].value_counts()
    qc["endo_npi_assigned"] = int(out["endo"].sum())
    qc["card_npi_assigned"] = int(out["card"].sum())
    return out, qc


def wpearson(x, y, w):
    w = w / w.sum()
    mx, my = (w * x).sum(), (w * y).sum()
    cov = (w * (x - mx) * (y - my)).sum()
    return cov / np.sqrt((w * (x - mx) ** 2).sum() * (w * (y - my) ** 2).sum())


def corr_row(label, c, xcol, ycol):
    s = c.dropna(subset=[xcol, ycol, "county_pop_last"])
    return {"pair": label, "n_counties": len(s),
            "pearson_r": round(s[xcol].corr(s[ycol]), 3),
            "spearman_rho": round(spearman(s[xcol], s[ycol]), 3),
            "pearson_log1p": round(np.log1p(s[xcol]).corr(np.log1p(s[ycol])), 3),
            "pop_weighted_pearson": round(wpearson(s[xcol], s[ycol], s["county_pop_last"]), 3)}


def main():
    tracts, anchors = load_master()
    cut = anchors["nat_med_ddi"]
    base = tracts.dropna(subset=["burden_z", "ddi"]).copy()
    inv_ref, dep_ref = matrix_boxes(tracts[tracts["in_pool"]], "ddi", cut)
    inv_ref_e, dep_ref_e = rank_eligible(inv_ref), rank_eligible(dep_ref)

    counts, qc = clinician_counts()
    c = (tracts.drop_duplicates("fips_county")
         [["fips_county", "county_state", "state_abbr", "card_last",
           "card_per_100k_last", "county_pop_last", "pool_nocard",
           "pool_declining", "in_pool"]].copy())
    for k, s in counts.items():
        c["n_" + k] = c["fips_county"].map(s).fillna(0).astype(int)
    pop = c["county_pop_last"]
    c["endo_per_100k"] = c["n_endo"] / pop * 1e5
    c["card_cms_per_100k"] = c["n_card"] / pop * 1e5
    has_wf = c["card_last"].notna()     # Connecticut planning regions drop out here

    print("=" * 78)
    print("endocrinology alongside cardiology (CMS Doctors and Clinicians)")
    print("=" * 78)
    print(f"endocrinologists: {qc['endo_npi']:,} NPIs, {qc['endo_npi_assigned']:,} "
          f"assigned to a county ({qc['endo_zip_unmapped_pct']}% of rows had an "
          f"unmapped ZIP)")

    # (a) correlation
    cc = c[has_wf & pop.notna()]
    corr = pd.DataFrame([
        corr_row("endocrinologists per 100k (CMS) vs cardiologists per 100k (AHRF 2023)",
                 cc, "endo_per_100k", "card_per_100k_last"),
        corr_row("endocrinologists per 100k (CMS) vs cardiologists per 100k (CMS)",
                 cc, "endo_per_100k", "card_cms_per_100k"),
        corr_row("endocrinologist count (CMS) vs cardiologist count (AHRF 2023)",
                 cc, "n_endo", "card_last"),
        corr_row("cardiologist count, CMS vs AHRF 2023",
                 cc, "n_card", "card_last"),
    ])
    corr.to_csv(os.path.join(OUT_DIR, "workforce_endocrinology_correlation.csv"), index=False)
    print("\n(a) correlation\n" + corr.to_string(index=False))

    # (b) joint absence
    w = c[has_wf]
    nocard, noendo = w["card_last"] == 0, w["n_endo"] == 0
    joint = {
        "n_counties": len(w),
        "n_no_cardiologist": int(nocard.sum()),
        "n_no_endocrinologist": int(noendo.sum()),
        "n_both_absent": int((nocard & noendo).sum()),
        "n_both_present": int((~nocard & ~noendo).sum()),
        "pct_both_or_neither": round(((nocard == noendo).mean()) * 100, 1),
        "pct_no_cardiologist_also_no_endocrinologist": round(noendo[nocard].mean() * 100, 1),
        "pct_has_cardiologist_but_no_endocrinologist": round(noendo[~nocard].mean() * 100, 1),
        "n_no_cardiologist_with_endocrinologist": int((nocard & ~noendo).sum()),
        "pct_population_in_no_endocrinologist_counties":
            round(w.loc[noendo, "county_pop_last"].sum() / w["county_pop_last"].sum() * 100, 1),
    }
    pd.DataFrame([joint]).to_csv(
        os.path.join(OUT_DIR, "workforce_endocrinology_joint_absence.csv"), index=False)
    print("\n(b) joint absence")
    for k, v in joint.items():
        print(f"  {k}: {v}")

    # (c) pool variants
    pool = w["in_pool"].astype(bool)
    declining = w["pool_declining"].astype(bool)
    card_pool = set(w.loc[pool, "fips_county"])
    scarce = set(w.loc[noendo, "fips_county"])
    variants = {
        "joint_absence": set(w.loc[nocard & noendo, "fips_county"])
                         | set(w.loc[declining, "fips_county"]),
        "union": card_pool | scarce,
        "intersection": card_pool & scarce,
        "endocrinology": scarce,
    }
    rows = [{"variant": "cardiology (primary)", "n_counties_pool": len(card_pool),
             "n_added": 0, "n_dropped": 0, "jaccard_vs_primary_pool": 1.0,
             "n_pool_tracts": int(tracts["fips_county"].isin(card_pool).sum()),
             **compare_runs(base, inv_ref, dep_ref, inv_ref, dep_ref)}]
    for name, ps in variants.items():
        Pw = tracts[tracts["fips_county"].isin(ps)]
        inv_w, dep_w = matrix_boxes(Pw, "ddi", cut)
        cmp_ = compare_runs(base, inv_ref, dep_ref, inv_w, dep_w)
        inv_we, dep_we = rank_eligible(inv_w), rank_eligible(dep_w)
        for n in (10, 50, 100):      # overlap on the rank-eligible lists
            cmp_[f"inv_top{n}_overlap"] = len(set(inv_ref_e.fips_tract.head(n))
                                             & set(inv_we.fips_tract.head(n)))
            cmp_[f"dep_top{n}_overlap"] = len(set(dep_ref_e.fips_tract.head(n))
                                             & set(dep_we.fips_tract.head(n)))
        rows.append({"variant": name, "n_counties_pool": len(ps),
                     "n_added": len(ps - card_pool), "n_dropped": len(card_pool - ps),
                     "jaccard_vs_primary_pool":
                         round(len(ps & card_pool) / len(ps | card_pool), 3),
                     "n_pool_tracts": len(Pw), **cmp_})
        tidy(inv_we).head(TOP_N).to_csv(
            os.path.join(OUT_DIR, f"workforce_endocrinology_{name}_INVEST_top.csv"), index=False)
        tidy(dep_we).head(TOP_N).to_csv(
            os.path.join(OUT_DIR, f"workforce_endocrinology_{name}_DEPLOY_top.csv"), index=False)
    comp = pd.DataFrame(rows)
    comp.to_csv(os.path.join(OUT_DIR, "workforce_endocrinology_comparison.csv"), index=False)
    show = ["variant", "n_counties_pool", "n_added", "n_dropped", "jaccard_vs_primary_pool",
            "n_invest_new", "n_deploy_new", "box_agree_pct", "invest_retained_pct",
            "deploy_retained_pct", "inv_top10_overlap", "dep_top10_overlap"]
    print("\n(c) pool variants\n" + comp[show].to_string(index=False))

    c["pool_joint_absence"] = c["fips_county"].isin(variants["joint_absence"])
    c.to_csv(os.path.join(OUT_DIR, "workforce_endocrinology_county.csv"), index=False)

    nat_endo = cc["n_endo"].sum() / cc["county_pop_last"].sum() * 1e5
    nat_card = cc["card_last"].sum() / cc["county_pop_last"].sum() * 1e5
    lines = ["# Endocrinology alongside cardiology", "",
             "Script: sens_workforce_endocrinology.py. Source of truth: the CSV files "
             "beside this log.", "",
             f"- CMS endocrinologists: {qc['endo_npi']:,} NPIs, {qc['endo_npi_assigned']:,} "
             f"assigned to a county.",
             f"- National supply per 100,000: {nat_endo:.2f} endocrinologists (CMS) vs "
             f"{nat_card:.2f} cardiologists (AHRF 2023).", "",
             "## Correlation", "", markdown_table(corr.set_index("pair"), ".3f"), "",
             "## Joint absence", ""]
    lines += [f"- {k}: {v}" for k, v in joint.items()]
    lines += ["", "## Pool variants", "",
              f"Classification anchors unchanged (burden z > 0; ready = DDI <= {cut}). "
              "Top-N overlap on rank-eligible lists.", "",
              markdown_table(comp[show].set_index("variant")), ""]
    with open(os.path.join(OUT_DIR, "workforce_endocrinology_summary.md"), "w") as fh:
        fh.write("\n".join(lines))
    print(f"\nwritten -> {OUT_DIR}/workforce_endocrinology_*")


if __name__ == "__main__":
    main()
