"""
sens_burden_kypa_crosswalk.py
=============================
Tract-level check of the Kentucky and Pennsylvania burden gap.

Builds on sens_burden_kypa: the PLACES 2023 release carries all ten measures
for KY and PA but sits on 2010-vintage tracts. This script crosswalks the
full-measure burden composite onto 2020 tracts with the Census 2010-2020
tract relationship file (population-weighted, uniform-density assumption),
asks how many priority tracts in the two states stay above the national
mean, looks at the Delaware County deployment cluster tract by tract, and
re-runs the ranking with the rebuilt burden swapped in.

Needs internet on first run: downloads the Census relationship file (~50 MB).
Reuses the cached PLACES 2023 pull from sens_burden_kypa.

Outputs (outputs/master/)
  places2023_burden_2020tracts.csv   rebuilt burden on 2020 tracts, all states
                                     (read again by validate_cross_source.py)
  burden_kypa_crosswalk_delaware.csv the Delaware County tracts, one row each
  burden_kypa_crosswalk.md           the numbers reported in the text
"""
import io
import os

import numpy as np
import pandas as pd
import requests

PD_ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(PD_, "outputs", "master")
CACHE = os.path.join(OUT, "places2023_cv_wide.csv")
POP_CACHE = os.path.join(OUT, "places2023_population.csv")
REL_CACHE = os.path.join(OUT, "tract_rel_2010_2020.txt")
XW_CACHE = os.path.join(OUT, "places2023_burden_2020tracts.csv")
MASTER = os.path.join(OUT, "tract_master.csv")
ANCHORS = os.path.join(OUT, "anchors.csv")
LOG = os.path.join(OUT, "burden_kypa_crosswalk.md")

MEASURES = ["BINGE", "BPHIGH", "CHD", "CSMOKING", "DIABETES",
            "HIGHCHOL", "LPA", "OBESITY", "SLEEP", "STROKE"]
PLACES_URL = "https://data.cdc.gov/resource/hky2-3tpn.csv"
REL_URL = ("https://www2.census.gov/geo/docs/maps-data/data/rel2020/tract/"
           "tab20_tract20_tract10_natl.txt")
PAGE = 60000


def fetch_population():
    if os.path.exists(POP_CACHE):
        return pd.read_csv(POP_CACHE, dtype={"tractfips": str})
    frames, offset = [], 0
    while True:
        r = requests.get(PLACES_URL,
                         params={"$select": "tractfips,totalpopulation",
                                 "$order": "tractfips",
                                 "$limit": PAGE, "$offset": offset},
                         timeout=180)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text), dtype={"tractfips": str})
        if df.empty:
            break
        frames.append(df)
        if len(df) < PAGE:
            break
        offset += PAGE
    pop = pd.concat(frames, ignore_index=True)
    pop.to_csv(POP_CACHE, index=False)
    return pop


def fetch_relationship():
    if not os.path.exists(REL_CACHE):
        print("downloading Census 2010-2020 tract relationship file (~50 MB) ...")
        r = requests.get(REL_URL, timeout=600)
        r.raise_for_status()
        with open(REL_CACHE, "wb") as f:
            f.write(r.content)
    rel = pd.read_csv(REL_CACHE, sep="|", dtype=str, encoding="latin-1")
    low = {c.lower(): c for c in rel.columns}
    need = {}
    for logical, frag in [("t20", "geoid_tract_20"), ("t10", "geoid_tract_10"),
                          ("part", "arealand_part"), ("land10", "arealand_tract_10")]:
        col = next((low[c] for c in low if frag in c), None)
        if col is None:
            raise SystemExit(f"missing column ~{frag}; columns = {sorted(low)}")
        need[logical] = col
    rel = rel[[need["t20"], need["t10"], need["part"], need["land10"]]]
    rel.columns = ["t20", "t10", "part", "land10"]
    rel["t20"] = rel["t20"].str.zfill(11)
    rel["t10"] = rel["t10"].str.zfill(11)
    rel["part"] = pd.to_numeric(rel["part"], errors="coerce").fillna(0.0)
    rel["land10"] = pd.to_numeric(rel["land10"], errors="coerce")
    return rel


def main():
    lines = []
    def say(s):
        print(s)
        lines.append(s)

    # full-measure burden on 2010 tracts (from the sens_burden_kypa cache)
    if not os.path.exists(CACHE):
        raise SystemExit("run sens_burden_kypa.py first "
                         "(builds the PLACES 2023 cache)")
    w = pd.read_csv(CACHE, dtype={"tractfips": str})
    w["tractfips"] = w["tractfips"].str.zfill(11)
    w = w.drop_duplicates("tractfips").set_index("tractfips")
    have = [m for m in MEASURES if m in w.columns]
    vals = w[have].astype(float)
    n_meas = vals.notna().sum(axis=1)
    z = (vals - vals.mean()) / vals.std()
    burden10 = z.mean(axis=1).where(n_meas >= max(len(have) - 2, 1))
    say("## tract-level crosswalk check (PLACES 2023 full-measure burden)\n")
    say(f"- 2010-vintage tracts with full-measure burden: {burden10.notna().sum():,}")

    pop = fetch_population()
    pop["tractfips"] = pop["tractfips"].str.zfill(11)
    pop10 = pop.drop_duplicates("tractfips").set_index("tractfips")[
        "totalpopulation"].astype(float)

    rel = fetch_relationship()
    rel["b10"] = rel["t10"].map(burden10)
    rel["pop10"] = rel["t10"].map(pop10)
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = np.where(rel["land10"] > 0, rel["part"] / rel["land10"], 0.0)
    rel["wt"] = (rel["pop10"].fillna(0) * frac).clip(lower=0)
    # fall back to area weight where population is unavailable
    rel.loc[rel["wt"] <= 0, "wt"] = rel.loc[rel["wt"] <= 0, "part"]

    rel_ok = rel.dropna(subset=["b10"])
    num = (rel_ok["b10"] * rel_ok["wt"]).groupby(rel_ok["t20"]).sum()
    den_ok = rel_ok.groupby("t20")["wt"].sum()
    den_all = rel.groupby("t20")["wt"].sum()
    cov = (den_ok / den_all).fillna(0)
    burden20 = (num / den_ok).where(cov >= 0.5)
    say(f"- 2020-vintage tracts with crosswalked burden: {burden20.notna().sum():,}")
    (burden20.rename("b23").rename_axis("t20").reset_index()
     .to_csv(XW_CACHE, index=False))

    # primary data and the primary classification
    from build_master import matrix_boxes, corr_with_ci, spearman
    t = pd.read_csv(MASTER, dtype={"fips_tract": str, "fips_county": str})
    t = t.drop_duplicates("fips_tract")
    anchors = pd.read_csv(ANCHORS).iloc[0]
    nat = float(anchors["nat_med_ddi"])
    P = t[t["in_pool"]].dropna(subset=["burden_z", "ddi"]).copy()
    P["st"] = P["fips_tract"].str.zfill(11).str[:2]
    P["b23"] = P["fips_tract"].map(burden20)

    # validity anchor at TRACT level, outside KY/PA/FL
    va = P[~P["st"].isin(["21", "42", "12"])].dropna(subset=["b23"])
    say(f"- Tract-level validity anchor (pool tracts outside KY/PA/FL, "
        f"n = {len(va):,}): primary vs crosswalked full-measure burden "
        f"r = {va['burden_z'].corr(va['b23']):.3f}, "
        f"rho = {spearman(va['burden_z'], va['b23']):.3f}")

    kp_all = P[P["st"].isin(["21", "42"])]
    kp = kp_all.dropna(subset=["b23"]).copy()
    kp["hb"] = kp["burden_z"] > 0
    kp["ready"] = kp["ddi"] <= nat
    kp["label"] = np.where(kp["hb"] & kp["ready"], "DEP",
                  np.where(kp["hb"] & ~kp["ready"], "INV", "other"))
    say(f"- KY/PA pool tracts: {len(kp_all):,}; with crosswalked burden: "
        f"{len(kp):,} ({len(kp_all) - len(kp)} had no 2010-tract match)")
    cc = corr_with_ci(kp["burden_z"], kp["b23"])
    say(f"- KY/PA sleep-only vs full-measure burden: "
        f"r = {cc['r']:.3f} (95% CI {cc['ci_low']:.3f} to {cc['ci_high']:.3f}, "
        f"n = {cc['n']:,}), "
        f"rho = {spearman(kp['burden_z'], kp['b23']):.3f}")
    for lab in ["DEP", "INV"]:
        sub = kp[kp["label"] == lab]
        say(f"- KY/PA {lab} tracts staying high burden (full-measure z > 0): "
            f"{(sub['b23'] > 0).sum():,} of {len(sub):,} "
            f"({(sub['b23'] > 0).mean() * 100:.1f}%)")

    # the Delaware County, PA deployment cluster, tract by tract
    inv_b, dep_b = matrix_boxes(P, "ddi", nat)
    top25 = dep_b.head(25)
    dela = top25[top25["fips_tract"].str[:5] == "42045"]
    say(f"\n- Delaware County tracts in the unrestricted deployment top 25: {len(dela)}")
    say("| rank | tract | sleep-only burden z | full-measure burden z | stays high burden |")
    say("|---|---|---|---|---|")
    n_keep, rows = 0, []
    for rank, (_, r) in enumerate(top25.iterrows(), start=1):
        if r["fips_tract"][:5] != "42045":
            continue
        b23 = burden20.get(r["fips_tract"], np.nan)
        keep = "yes" if (pd.notna(b23) and b23 > 0) else ("no data" if pd.isna(b23) else "NO")
        n_keep += 1 if keep == "yes" else 0
        say(f"| {rank} | {r['fips_tract']} | {r['burden_z']:.2f} | "
            f"{b23:.2f} | {keep} |")
        rows.append({"Rank": rank, "Tract FIPS": r["fips_tract"],
                     "DDI": round(r["ddi"], 1),
                     "Single-measure burden z": round(r["burden_z"], 2),
                     "Full-measure burden z (2023 release)": round(b23, 2),
                     "Above national mean": keep})
    say(f"- Delaware County tracts staying high burden: {n_keep} of {len(dela)}")
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "burden_kypa_crosswalk_delaware.csv"),
                              index=False)

    # hybrid re-ranking: full-measure burden for KY/PA, primary burden elsewhere
    H = P.copy()
    swap = H["st"].isin(["21", "42"]) & H["b23"].notna()
    H["burden_z"] = np.where(swap, H["b23"], H["burden_z"])
    H = H.drop(columns=["hb"], errors="ignore")
    inv_h, dep_h = matrix_boxes(H.dropna(subset=["burden_z", "ddi"]), "ddi", nat)
    say(f"\n- Hybrid boxes (full-measure burden for KY/PA): "
        f"INV {len(inv_b):,} -> {len(inv_h):,}; DEP {len(dep_b):,} -> {len(dep_h):,}")
    for lab, b, h in [("DEP", dep_b, dep_h), ("INV", inv_b, inv_h)]:
        b25 = set(b.head(25)["fips_tract"]); h25 = set(h.head(25)["fips_tract"])
        b10 = set(b.head(10)["fips_tract"]); h10 = set(h.head(10)["fips_tract"])
        say(f"- Hybrid {lab}: top-25 overlap {len(b25 & h25)}/25; "
            f"top-10 overlap {len(b10 & h10)}/10")
    n_dela_h = (dep_h.head(25)["fips_tract"].str[:5] == "42045").sum()
    say(f"- Hybrid deployment top 25: Delaware County PA holds {n_dela_h} of 25")

    with open(LOG, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nlog -> {LOG}")


if __name__ == "__main__":
    main()
