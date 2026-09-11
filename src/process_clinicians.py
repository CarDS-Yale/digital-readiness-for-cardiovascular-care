"""
County counts of cardiology nurse practitioners and physician assistants.

Built from the CMS Doctors and Clinicians file (downloaded by
fetch_clinicians.py) using practice affiliation. Group-level rules do not work
here: only a few hundred of ~58,000 groups are cardiology-majority, so a strict
group rule finds almost no clinicians, while "any group containing a
cardiologist" sweeps in everyone employed by a large health system.

Classification therefore happens at the practice SITE, defined as one
(Group PAC ID, ZIP5) pair. A health system's cardiology clinic is mostly
cardiologists at its own address even when the parent system employs thousands
of other clinicians.

Rules computed per clinician (each NPI counted once, at its best qualifying site)
  grp_strict   group cardiology share >= 0.5, retained for comparison
  site_strict  site cardiology share >= 0.5 and >= 1 cardiologist at the site
  site_any     >= 1 cardiologist at the clinician's own site (co-location)
  site_wtd     site_any weighted by the site's cardiology share
"""
import os
import re

import numpy as np
import pandas as pd

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAC_FILE = os.path.join(PROJECT_DIR, "DAC_CMS", "DAC_NationalDownloadableFile.csv")
ZCTA_FILE = os.path.join(PROJECT_DIR, "DAC_CMS", "tab20_zcta520_county20_natl.txt")
OUT_DIR = os.path.join(PROJECT_DIR, "outputs", "master")
os.makedirs(OUT_DIR, exist_ok=True)

# cardiology = any CARDI* specialty except surgery. DAC strings observed:
#   CARDIOVASCULAR DISEASE (CARDIOLOGY), INTERVENTIONAL CARDIOLOGY,
#   CARDIAC ELECTROPHYSIOLOGY, ADVANCED HEART FAILURE AND TRANSPLANT
#   CARDIOLOGY; CARDIAC SURGERY is excluded (mirrors the AHRF proxy).
def card_mask(spec):
    return (spec.str.contains("CARDI", na=False)
            & ~spec.str.contains("SURGERY", na=False))
APP_SPECS = {"NURSE PRACTITIONER", "PHYSICIAN ASSISTANT"}
NON_PHYSICIAN = APP_SPECS | {
    "CERTIFIED REGISTERED NURSE ANESTHETIST", "CRNA",
    "CERTIFIED REGISTERED NURSE ANESTHETIST (CRNA)",
    "CLINICAL NURSE SPECIALIST", "CERTIFIED NURSE MIDWIFE",
    "ANESTHESIOLOGY ASSISTANT", "CLINICAL PSYCHOLOGIST",
    "CLINICAL SOCIAL WORKER", "MARRIAGE AND FAMILY THERAPIST",
    "MENTAL HEALTH COUNSELOR", "PHYSICAL THERAPY", "OCCUPATIONAL THERAPY",
    "QUALIFIED AUDIOLOGIST", "AUDIOLOGIST",
    "QUALIFIED SPEECH LANGUAGE PATHOLOGIST", "SPEECH LANGUAGE PATHOLOGIST",
    "REGISTERED DIETITIAN OR NUTRITION PROFESSIONAL", "OPTOMETRY",
    "CHIROPRACTIC", "PODIATRY", "CERTIFIED CLINICAL NURSE SPECIALIST",
}
MAJORITY_CUT = 0.5

COLMAP = {
    "npi":       r"^npi$",
    "pri_spec":  r"^(pri_spec|primary specialty)$",
    "org_pac":   r"^(org_pac_id|group pac id)$",
    "zip":       r"^(zip|zip[_ ]?code)$",
    "state":     r"^(st|state)$",
}
# optional: exact practice-location identifiers (preferred site key)
COLMAP_OPT = {
    "adrs_id":   r"^(adrs_id|address id)$",
    "ln1":       r"^(adr_ln_1|address line 1|line 1 street address)$",
    "city":      r"^(cty|city|city/town)$",
}


def resolve_columns(path):
    header = pd.read_csv(path, nrows=0)
    cols = {}
    for canon, pat in COLMAP.items():
        hit = [c for c in header.columns
               if re.fullmatch(pat, c.strip().lower())]
        if not hit:
            raise SystemExit(f"Cannot find a column matching {pat!r}. "
                             f"Header: {list(header.columns)[:40]}")
        cols[canon] = hit[0]
    for canon, pat in COLMAP_OPT.items():
        hit = [c for c in header.columns
               if re.fullmatch(pat, c.strip().lower())]
        if hit:
            cols[canon] = hit[0]
    return cols


def zip_to_county():
    z = pd.read_csv(ZCTA_FILE, sep="|", dtype=str)
    zc = next(c for c in z.columns if re.fullmatch(r"GEOID_ZCTA5.*", c))
    cc = next(c for c in z.columns if re.fullmatch(r"GEOID_COUNTY.*", c))
    area = next((c for c in z.columns if c.startswith("AREALAND_PART")), None)
    z = z.dropna(subset=[zc])
    z["_area"] = pd.to_numeric(z[area], errors="coerce").fillna(0)
    z = (z.sort_values("_area", ascending=False).drop_duplicates(zc))
    return dict(zip(z[zc].str.zfill(5), z[cc].str.zfill(5)))


def main():
    for f in (DAC_FILE, ZCTA_FILE):
        if not os.path.exists(f):
            raise SystemExit(f"Missing {f}. Run fetch_clinicians.py --all first.")

    cols = resolve_columns(DAC_FILE)
    print(f"resolved columns: {cols}")
    dac = pd.read_csv(DAC_FILE, usecols=list(cols.values()), dtype=str,
                      low_memory=False)
    dac = dac.rename(columns={v: k for k, v in cols.items()})
    dac["pri_spec"] = dac["pri_spec"].str.strip().str.upper()
    dac["zip5"] = dac["zip"].str.extract(r"(\d{5})")[0]

    # site key: exact practice location, best available granularity
    if "adrs_id" in dac.columns and dac["adrs_id"].notna().mean() > 0.5:
        dac["site"] = dac["adrs_id"]
        site_kind = "address ID"
    elif "ln1" in dac.columns:
        dac["site"] = (dac["ln1"].fillna("").str.upper()
                       .str.replace(r"[^A-Z0-9]", "", regex=True)
                       + "|" + dac.get("city", pd.Series("", index=dac.index))
                                  .fillna("").str.upper()
                       + "|" + dac["zip5"].fillna(""))
        site_kind = "normalized street address"
    else:
        dac["site"] = dac["zip5"]
        site_kind = "ZIP5 (fallback)"
    print(f"rows: {len(dac):,}  unique NPIs: {dac['npi'].nunique():,}  "
          f"site key: {site_kind}")

    is_app = dac["pri_spec"].isin(APP_SPECS)
    is_phys = ~dac["pri_spec"].isin(NON_PHYSICIAN)
    is_card = card_mask(dac["pri_spec"])

    # ── group-level cardiology share, kept for comparison ────────────────────────
    phys = dac[is_phys & dac["org_pac"].notna()]
    grp = (phys.drop_duplicates(["org_pac", "npi"])
               .assign(card=lambda d: card_mask(d["pri_spec"]))
               .groupby("org_pac")["card"].agg(["size", "sum"])
               .rename(columns={"size": "n_physicians", "sum": "n_cardiologists"}))
    grp["grp_share"] = grp["n_cardiologists"] / grp["n_physicians"]
    grp_card = grp[grp["n_cardiologists"] > 0]
    print(f"groups: {len(grp):,}; with >=1 cardiologist: {len(grp_card):,}; "
          f"cardiology-majority: {(grp_card['grp_share'] >= MAJORITY_CUT).sum():,}")

    # ── site-level (org_pac x practice location) cardiology share ───────────
    site_phys = (phys.dropna(subset=["site"])
                     .drop_duplicates(["org_pac", "site", "npi"])
                     .assign(card=lambda d: card_mask(d["pri_spec"]))
                     .groupby(["org_pac", "site"])["card"].agg(["size", "sum"])
                     .rename(columns={"size": "n_phys_site",
                                      "sum": "n_card_site"}))
    site_phys["site_share"] = site_phys["n_card_site"] / site_phys["n_phys_site"]
    site_card = site_phys[site_phys["n_card_site"] > 0]
    print(f"sites (group x location): {len(site_phys):,}; with >=1 cardiologist: "
          f"{len(site_card):,}; cardiology-majority sites: "
          f"{(site_card['site_share'] >= MAJORITY_CUT).sum():,}")

    # ── attribute APPs ──────────────────────────────────────────────────────
    app = (dac[is_app & dac["org_pac"].notna() & dac["zip5"].notna()
               & dac["site"].notna()]
           .drop_duplicates(["npi", "org_pac", "site"]))
    app = app.merge(grp_card[["grp_share"]], left_on="org_pac",
                    right_index=True, how="inner")     # group has a cardiologist
    app = app.merge(site_card[["site_share"]],
                    left_on=["org_pac", "site"], right_index=True, how="left")
    app["site_share"] = app["site_share"].fillna(0.0)

    # one row per person: best site by (site_share, grp_share)
    app = (app.sort_values(["site_share", "grp_share"], ascending=False)
              .drop_duplicates("npi"))
    app["grp_strict"] = app["grp_share"] >= MAJORITY_CUT
    app["site_any"] = app["site_share"] > 0
    app["site_strict"] = app["site_share"] >= MAJORITY_CUT
    app["site_wt"] = app["site_share"]

    zmap = zip_to_county()
    app["fips_st_cnty"] = app["zip5"].map(zmap)
    print(f"APPs in cardiologist-containing groups: {len(app):,}")
    print(f"  grp_strict {int(app['grp_strict'].sum()):,} | "
          f"site_any {int(app['site_any'].sum()):,} | "
          f"site_strict {int(app['site_strict'].sum()):,} | "
          f"site_wtd {app['site_wt'].sum():,.0f}")
    print(f"  ZIP unmapped: {app['fips_st_cnty'].isna().mean()*100:.1f}%")

    # DAC cardiologist county counts (sanity vs AHRF)
    cardio = dac[is_card].copy()
    cardio["fips_st_cnty"] = cardio["zip5"].map(zmap)
    cardio = cardio.dropna(subset=["fips_st_cnty"]).drop_duplicates("npi")

    county = (app.dropna(subset=["fips_st_cnty"])
                 .groupby("fips_st_cnty")
                 .agg(n_app_grp_strict=("grp_strict", "sum"),
                      n_app_site_strict=("site_strict", "sum"),
                      n_app_site_any=("site_any", "sum"),
                      n_app_site_wtd=("site_wt", "sum"))
                 .round({"n_app_site_wtd": 2}))
    county["n_cardiologists_dac"] = cardio.groupby("fips_st_cnty")["npi"].size()
    county = county.fillna(0).reset_index()
    county.to_csv(os.path.join(OUT_DIR, "dac_cardiology_app_county.csv"), index=False)

    app[app["site_any"]][["npi", "pri_spec", "org_pac", "grp_share",
                          "site_share", "site_strict", "zip5", "state",
                          "fips_st_cnty"]].to_csv(
        os.path.join(OUT_DIR, "dac_cardiology_app_npi.csv"), index=False)
    grp_card.reset_index().to_csv(
        os.path.join(OUT_DIR, "dac_group_summary.csv"), index=False)

    # compact extract: all rows of cardiologist-containing groups
    keep = dac["org_pac"].isin(grp_card.index) & dac["zip5"].notna()
    ext = dac[keep].copy()
    ext["role"] = np.select(
        [card_mask(ext["pri_spec"]), ext["pri_spec"].isin(APP_SPECS),
         ~ext["pri_spec"].isin(NON_PHYSICIAN)],
        ["card_phys", "app", "other_phys"], default="other_nonphys")
    (ext[["npi", "role", "pri_spec", "org_pac", "site", "zip5", "state"]]
        .drop_duplicates(["npi", "org_pac", "site"])
        .to_csv(os.path.join(OUT_DIR, "dac_cardgroup_extract.csv"), index=False))

    print(f"counties with >=1 site_strict APP: "
          f"{(county['n_app_site_strict'] > 0).sum():,} | "
          f"site_any: {(county['n_app_site_any'] > 0).sum():,}")
    print(f"written -> {OUT_DIR}/dac_*")


if __name__ == "__main__":
    main()
