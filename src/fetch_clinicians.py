"""
fetch_clinicians.py
===============
Download the CMS Doctors and Clinicians National Downloadable File (DAC,
formerly Physician Compare) and the Census ZCTA-to-county relationship file.

RUN THIS ON THE MAC (needs open internet). The cloud workspace cannot reach
data.cms.gov or census.gov.

Why: AHRF has no cardiology-specific NP/PA counts, and neither NPPES taxonomy
(NPs carry population-focus codes only; PAs only Medical/Surgical) nor PECOS
enrollment (generic specialty codes 50/97) identifies cardiology APPs. The
public workaround is group-practice affiliation: the DAC file lists every
Medicare-enrolled clinician with primary specialty, Group PAC ID, and practice
address, so NPs/PAs can inherit the cardiology label from their group's
physicians. process_clinicians.py implements that.

Downloads (to DAC_CMS/, skipped when present)
  DAC_NationalDownloadableFile.csv   ~2.5M rows, ~800 MB
  tab20_zcta520_county20_natl.txt    Census 2020 ZCTA-county relationships

The DAC csv URL changes each release, so this script asks the CMS metastore
for the current URL at run time.

Usage
  python3 fetch_clinicians.py          # peek: resolve URL, print metadata, no big download
  python3 fetch_clinicians.py --all    # full download
"""
import os
import sys

import requests

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT_DIR, "DAC_CMS")
os.makedirs(OUT_DIR, exist_ok=True)

DATASET_ID = "mj5m-pzi6"   # Doctors and Clinicians National Downloadable File
METASTORE = ("https://data.cms.gov/provider-data/api/1/metastore/schemas/"
             f"dataset/items/{DATASET_ID}?show-reference-ids")
ZCTA_URL = ("https://www2.census.gov/geo/docs/maps-data/data/rel2020/"
            "zcta520/tab20_zcta520_county20_natl.txt")

DAC_OUT = os.path.join(OUT_DIR, "DAC_NationalDownloadableFile.csv")
ZCTA_OUT = os.path.join(OUT_DIR, "tab20_zcta520_county20_natl.txt")


def resolve_dac_url():
    r = requests.get(METASTORE, timeout=60)
    r.raise_for_status()
    meta = r.json()
    dists = meta.get("distribution", [])
    for d in dists:
        data = d.get("data", d)
        url = data.get("downloadURL", "")
        if url.endswith(".csv"):
            return url, meta.get("modified", "?")
    raise SystemExit("No CSV distribution found in DAC metastore response.")


def download(url, dest, label):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"  [skip] {label} already present "
              f"({os.path.getsize(dest)/1e6:.0f} MB)")
        return
    print(f"  downloading {label} ...")
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                if done % (200 << 20) < (1 << 20):
                    print(f"    ... {done/1e6:,.0f} MB")
    print(f"  [done] {label}: {os.path.getsize(dest)/1e6:,.0f} MB -> {dest}")


def main():
    full = "--all" in sys.argv
    url, modified = resolve_dac_url()
    print(f"DAC csv (modified {modified}):\n  {url}")
    if not full:
        print("\nPeek mode. Rerun with --all to download "
              "(~800 MB DAC + ~10 MB ZCTA file).")
        return
    download(url, DAC_OUT, "DAC national file")
    download(ZCTA_URL, ZCTA_OUT, "ZCTA-county relationship file")
    print("\nNext: python3 process_clinicians.py")


if __name__ == "__main__":
    main()
