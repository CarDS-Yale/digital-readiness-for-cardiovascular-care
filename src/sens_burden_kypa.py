"""
sens_burden_kypa.py
========================================
Sensitivity check for the Kentucky / Pennsylvania burden gap.

Our primary burden composite draws on the 2025 PLACES release, in which KY
and PA carry only 1 of the 10 CV measures (short sleep). This
script pulls the PLACES 2023 release, where KY and PA have full measures,
rebuilds a composite z-score burden on that release, and asks whether the
KY/PA target geographies (led by Delaware County PA) stay high burden.

The 2023 release uses 2010-vintage census tracts (72,337 tracts), which
do not match our 2020-vintage tract IDs. The script detects this: if
tract IDs overlap, it runs the tract-level hybrid re-ranking with the
canonical matrix_boxes ranking; otherwise it falls back to a county-level
comparison (county FIPS are stable across vintages for KY and PA).

Run ON THE MAC (needs internet):
    cd path/to/digital-readiness
    .venv/bin/python sens_burden_kypa.py
"""
import io
import os

import numpy as np
import pandas as pd
import requests

PD_ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(PD_, "outputs", "master")
CACHE = os.path.join(OUT, "places2023_cv_wide.csv")
MASTER = os.path.join(OUT, "tract_master.csv")
ANCHORS = os.path.join(OUT, "anchors.csv")
LOG = os.path.join(OUT, "burden_kypa.md")

MEASURES = ["BINGE", "BPHIGH", "CHD", "CSMOKING", "DIABETES",
            "HIGHCHOL", "LPA", "OBESITY", "SLEEP", "STROKE"]
URL = "https://data.cdc.gov/resource/hky2-3tpn.csv"
PAGE = 60000

FOCUS = {
    "42045": "Delaware, PA (deployment flagship)",
    "42021": "Cambria, PA (investment)",
    "42089": "Monroe, PA (deployment)",
    "21111": "Jefferson, KY (both lists)",
    "21047": "Christian, KY (deployment)",
    "21093": "Hardin, KY (deployment)",
}


def discover_columns():
    r = requests.get(URL, params={"$limit": 1}, timeout=180)
    r.raise_for_status()
    header = list(pd.read_csv(io.StringIO(r.text), nrows=0).columns)
    low = {c.lower(): c for c in header}
    print(f"  dataset columns ({len(header)}): {sorted(low)}")
    tract = next((low[c] for c in low if "tractfips" in c), None)
    if tract is None:
        raise SystemExit("no tract FIPS column; see column list above")
    found, kind_used = {}, None
    for kind in ("adjprev", "crudeprev", "adj_prev", "crude_prev", "data_value"):
        found = {}
        for m in MEASURES:
            key = next((low[c] for c in low
                        if m.lower() in c and kind in c and "ci" not in c), None)
            if key:
                found[m] = key
        if found:
            kind_used = kind
            break
    if not found:
        raise SystemExit("no measure columns matched; see column list above")
    missing = [m for m in MEASURES if m not in found]
    print(f"  using '{kind_used}' columns; matched {len(found)}/10"
          + (f"; missing {missing}" if missing else ""))
    return tract, found


def fetch():
    tract, found = discover_columns()
    cols = [tract] + list(found.values())
    frames, offset = [], 0
    while True:
        r = requests.get(URL, params={"$select": ",".join(cols),
                                      "$order": tract,
                                      "$limit": PAGE, "$offset": offset},
                         timeout=180)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text), dtype={tract: str})
        if df.empty:
            break
        frames.append(df)
        print(f"  fetched {offset + len(df):,} rows")
        if len(df) < PAGE:
            break
        offset += PAGE
    full = pd.concat(frames, ignore_index=True)
    ren = {v: k for k, v in found.items()}
    ren[tract] = "tractfips"
    full = full.rename(columns=ren)
    full.to_csv(CACHE, index=False)
    return full


def main():
    w = None
    if os.path.exists(CACHE):
        w = pd.read_csv(CACHE, dtype={"tractfips": str})
        if not any(m in w.columns for m in MEASURES):
            print("cache lacks measure columns; refetching")
            w = None
        else:
            print(f"using cached {CACHE} ({len(w):,} rows)")
    if w is None:
        print("downloading PLACES 2023 release (tract, GIS-friendly) ...")
        w = fetch()

    w["tractfips"] = w["tractfips"].str.zfill(11)
    w = w.drop_duplicates("tractfips").set_index("tractfips")
    have = [m for m in MEASURES if m in w.columns]
    vals = w[have].astype(float)
    st = vals.index.str[:2]
    n_meas = vals.notna().sum(axis=1)

    lines = []
    def say(s):
        print(s)
        lines.append(s)

    say("## KY/PA burden sensitivity (PLACES 2023 release)\n")
    say(f"- Release tracts: {len(vals):,}; measures matched: {len(have)}/10")
    for code, name in [("21", "KY"), ("42", "PA"), ("12", "FL"), ("06", "CA")]:
        sub = n_meas[st == code]
        say(f"- {name} tracts with all matched measures: "
            f"{(sub == len(have)).sum():,} / {len(sub):,}")

    z = (vals - vals.mean()) / vals.std()
    min_req = max(len(have) - 2, 1)
    burden23 = z.mean(axis=1).where(n_meas >= min_req)

    t = pd.read_csv(MASTER, dtype={"fips_tract": str, "fips_county": str})
    t = t.drop_duplicates("fips_tract")
    anchors = pd.read_csv(ANCHORS).iloc[0]
    nat = float(anchors["nat_med_ddi"])

    overlap = len(set(t["fips_tract"]) & set(burden23.dropna().index))
    say(f"- Tract-ID overlap with 2020-vintage master: {overlap:,} "
        f"of {t['fips_tract'].nunique():,}")

    P = t[t["in_pool"]].dropna(subset=["burden_z", "ddi"]).copy()
    P["st"] = P["fips_tract"].str.zfill(11).str[:2]
    P["hb"] = P["burden_z"] > 0
    P["ready"] = P["ddi"] <= nat
    P["label"] = np.where(P["hb"] & P["ready"], "DEP",
                 np.where(P["hb"] & ~P["ready"], "INV", "other"))

    if overlap > 0.9 * t["fips_tract"].nunique():
        # same vintage: tract-level hybrid with the canonical ranking
        from build_master import matrix_boxes
        P["burden23"] = P["fips_tract"].map(burden23)
        both = P[P["st"].isin(["21", "42"])].dropna(subset=["burden23"])
        say(f"- KY/PA pool tracts with full-measure burden: {len(both):,}")
        say(f"- Correlation sleep-only vs full-measure burden (KY/PA): "
            f"r = {both['burden_z'].corr(both['burden23']):.3f}, "
            f"rho = {both['burden_z'].corr(both['burden23'], method='spearman'):.3f}")
        for lab in ["DEP", "INV"]:
            sub = both[both["label"] == lab]
            say(f"- KY/PA {lab} staying high burden: {(sub['burden23'] > 0).sum():,} "
                f"of {len(sub):,} ({(sub['burden23'] > 0).mean() * 100:.1f}%)")
        H = P.copy()
        swap = H["st"].isin(["21", "42"]) & H["burden23"].notna()
        H.loc[swap, "burden_z"] = H.loc[swap, "burden23"]
        inv_b, dep_b = matrix_boxes(P, "ddi", nat)
        inv_h, dep_h = matrix_boxes(H, "ddi", nat)
        for lab, b, h in [("DEP", dep_b, dep_h), ("INV", inv_b, inv_h)]:
            b25 = set(b.head(25)["fips_tract"]); h25 = set(h.head(25)["fips_tract"])
            b10 = set(b.head(10)["fips_tract"]); h10 = set(h.head(10)["fips_tract"])
            say(f"- Hybrid {lab}: box {len(b):,} -> {len(h):,}; top-25 overlap "
                f"{len(b25 & h25)}/25; top-10 overlap {len(b10 & h10)}/10")
        n_dela = (dep_h.head(25)["fips_tract"].str[:5] == "42045").sum()
        say(f"- Hybrid deployment top 25: Delaware County PA holds {n_dela} of 25")
    else:
        # vintage mismatch: county-level fallback (county FIPS are stable)
        say("- Vintage mismatch: falling back to county-level comparison\n")
        cnty23 = burden23.groupby(burden23.index.str[:5]).mean()
        share_hb = (burden23 > 0).groupby(burden23.index.str[:5]).mean()
        n23 = burden23.groupby(burden23.index.str[:5]).size()
        # validity anchor: county means, full-measure vs primary, outside KY/PA/FL
        prim_cnty = (P.groupby("fips_county")["burden_z"].mean())
        joint = pd.concat([prim_cnty.rename("prim"), cnty23.rename("full")],
                          axis=1).dropna()
        joint = joint[~joint.index.str[:2].isin(["21", "42", "12"])]
        say(f"- Validity anchor (counties outside KY/PA/FL, n = {len(joint):,}): "
            f"county-mean primary vs full-measure burden r = "
            f"{joint['prim'].corr(joint['full']):.3f}")
        pct = cnty23.rank(pct=True) * 100
        say("")
        say("| county | full-measure county burden z | national percentile | "
            "share of tracts high burden | tracts |")
        say("|---|---|---|---|---|")
        for f5, name in FOCUS.items():
            if f5 in cnty23.index:
                say(f"| {name} | {cnty23[f5]:.2f} | {pct[f5]:.0f} | "
                    f"{share_hb[f5] * 100:.0f}% | {int(n23[f5])} |")
            else:
                say(f"| {name} | no data | - | - | - |")
        # KY/PA pool tracts summarized at county level
        kp = P[P["st"].isin(["21", "42"])]
        for lab in ["DEP", "INV"]:
            sub = kp[kp["label"] == lab]
            cs = sub.groupby("fips_county").size()
            covered = cs.index.isin(cnty23.index)
            hb_share = (cnty23.reindex(cs.index) > 0)
            say(f"- KY/PA {lab} tracts: {len(sub):,} across {len(cs)} counties; "
                f"{int((cs[hb_share.fillna(False).values]).sum()):,} of them "
                f"({(cs[hb_share.fillna(False).values].sum() / len(sub)) * 100:.0f}%) "
                f"sit in counties with above-average full-measure burden")

    with open(LOG, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nlog -> {LOG}")


if __name__ == "__main__":
    main()
