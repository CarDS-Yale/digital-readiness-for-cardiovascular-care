#!/usr/bin/env python3
"""
aggregate_broadband.py — roll the FCC Served-Unserved location files up to census
tracts to produce the broadband-availability indicator for the DDI sensitivity
analysis.

INPUT : FCC/<vintage>/*served_unserved*.zip   (from: python fetch_broadband.py --all)
OUTPUT: FCC/fcc_<vintage>_tract_availability.csv
        GEOID (11-digit str), n_locations, n_terr_100_20, n_wired_100_20,
        n_any_100_20, terr_avail_pct, terr_unserved_pct

Availability uses TERRESTRIAL service at 100/20 Mbps, which excludes satellite
(satellite blankets everywhere and would erase the divide signal). The
DDI-aligned indicator is terr_unserved_pct, where higher = worse readiness.
n_locations is the true count of Broadband Serviceable Locations per tract, so
this is the exact denominator, not the household proxy.
"""
import os, sys, glob
import pandas as pd

VINTAGE = os.environ.get("FCC_VINTAGE", "2024-12-31")
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_DIR = os.path.join(PROJECT_DIR, "FCC", VINTAGE.replace("-", ""))
OUT = os.path.join(PROJECT_DIR, "FCC", f"fcc_{VINTAGE.replace('-','')}_tract_availability.csv")

zips = sorted(glob.glob(os.path.join(IN_DIR, "*served_unserved*.zip")))
if not zips:
    sys.exit(f"No served-unserved zips in {IN_DIR}. Run: python fetch_broadband.py --all")

COLS = ["block_geoid", "terrestrial_dl100_ul20", "wired_dl100_ul20", "any_dl100_ul20"]
FLAGS = ["terrestrial_dl100_ul20", "wired_dl100_ul20", "any_dl100_ul20"]

parts = []
for i, z in enumerate(zips, 1):
    df = pd.read_csv(z, usecols=COLS, dtype={"block_geoid": str})
    df = df[df["block_geoid"].notna()]
    df["GEOID"] = df["block_geoid"].str.zfill(15).str[:11]
    for c in FLAGS:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    g = df.groupby("GEOID").agg(
        n_locations=("terrestrial_dl100_ul20", "size"),
        n_terr_100_20=("terrestrial_dl100_ul20", "sum"),
        n_wired_100_20=("wired_dl100_ul20", "sum"),
        n_any_100_20=("any_dl100_ul20", "sum"),
    )
    parts.append(g)
    print(f"[{i}/{len(zips)}] {os.path.basename(z)}: {len(df):,} locs -> {len(g):,} tracts", flush=True)

out = pd.concat(parts).groupby("GEOID").sum()  # safe even if a tract spans files
out["terr_avail_pct"] = out["n_terr_100_20"] / out["n_locations"]
out["terr_unserved_pct"] = 1 - out["terr_avail_pct"]
out = out.reset_index().sort_values("GEOID")
out.to_csv(OUT, index=False)

nat = out["n_terr_100_20"].sum() / out["n_locations"].sum()
print(f"\nWrote {len(out):,} tracts x {out.shape[1]} cols -> {OUT}")
print(f"national terrestrial 100/20 availability = {nat:.3f}  (unserved {1-nat:.3f})")
print("GEOID is an 11-digit string; read with dtype={'GEOID': str}.")
