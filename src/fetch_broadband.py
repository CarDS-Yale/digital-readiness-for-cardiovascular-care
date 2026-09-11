#!/usr/bin/env python3
"""
fetch_broadband.py — download FCC BDC fixed-broadband "Served-Unserved" files
(one per state) for the DDI infrastructure side of the sensitivity analysis.

Each Served-Unserved file lists every Broadband Serviceable Location with its
served status at the 100/20 benchmark and a geography id. That gives BOTH the
availability numerator and the true total-location denominator per tract, so no
Location Fabric license and no household proxy are needed for availability.
Satellite is excluded elsewhere; this served-unserved file is terrestrial-based.

AUTH — set your FCC National Broadband Map API token first:
    export FCC_USERNAME="you@example.com"
    export FCC_HASH="your_api_token"

USAGE:
    python fetch_broadband.py            # PEEK: pull only the smallest state, print columns
    python fetch_broadband.py --all      # download all 50 states + DC to FCC/<vintage>/
    FCC_VINTAGE=2025-12-31 python fetch_broadband.py --all   # pick a different as-of date

Files land in ./FCC/<vintage>/ . Re-runs skip files already downloaded.
"""
import os, sys, ssl, json, time, zipfile, io, shutil
import urllib.request, urllib.error

VINTAGE = os.environ.get("FCC_VINTAGE", "2024-12-31")
BASE = "https://broadbandmap.fcc.gov"
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(PROJECT_DIR, "FCC", VINTAGE.replace("-", ""))
os.makedirs(OUT, exist_ok=True)

USER = os.environ.get("FCC_USERNAME", "").strip()
HASH = os.environ.get("FCC_HASH", "").strip()
if not USER or not HASH:
    sys.exit("Set FCC_USERNAME and FCC_HASH environment variables first "
             "(FCC National Broadband Map API token).")

try:
    import certifi; CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    CTX = ssl.create_default_context()
H = {"User-Agent": "cards-digital-readiness/1.0", "Accept": "application/json",
     "username": USER, "hash_value": HASH}

# 50 states + DC (drops the unassigned codes and all territories)
FIPS_50_DC = {f"{i:02d}" for i in range(1, 57)} - {"03", "07", "14", "43", "52"}

def api_json(path):
    req = urllib.request.Request(BASE + path, headers=H)
    with urllib.request.urlopen(req, timeout=180, context=CTX) as r:
        return json.loads(r.read())

def list_served_unserved():
    rows = api_json(f"/api/public/map/downloads/listAvailabilityData/{VINTAGE}")["data"]
    return [r for r in rows
            if r.get("technology_type") == "Fixed Broadband"
            and r.get("category") == "State"
            and r.get("subcategory") == "Served-Unserved"
            and r.get("state_fips") in FIPS_50_DC]

def download(file_id, dest):
    url = f"{BASE}/api/public/map/downloads/downloadFile/availability/{file_id}"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=H)
            tmp = dest + ".part"
            with urllib.request.urlopen(req, timeout=900, context=CTX) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, length=1 << 20)
            os.replace(tmp, dest)
            return os.path.getsize(dest)
        except Exception as e:
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))

def peek(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
        print("  files in zip:", z.namelist())
        with z.open(csvs[0]) as f:
            t = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
            print("  COLUMNS:", t.readline().strip())
            for i in range(2):
                print(f"  ROW{i+1}:", t.readline().strip()[:320])

def main():
    allmode = "--all" in sys.argv
    files = sorted(list_served_unserved(), key=lambda r: int(r.get("record_count") or 0))
    print(f"vintage {VINTAGE}: {len(files)} served-unserved state files (target 51)")
    if not files:
        sys.exit("No matching files. Check the vintage date and your token.")
    targets = files if allmode else files[:1]
    if not allmode:
        print("PEEK mode: smallest state only. Re-run with --all for the full set (~1-2 GB).")
    for i, r in enumerate(targets, 1):
        dest = os.path.join(OUT, r["file_name"] + ".zip")
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            print(f"[{i}/{len(targets)}] {r['state_fips']} {r['file_name']} present, skip")
        else:
            print(f"[{i}/{len(targets)}] {r['state_fips']} {r['file_name']} "
                  f"({int(r.get('record_count') or 0):,} locs) downloading...", flush=True)
            n = download(r["file_id"], dest)
            print(f"      wrote {n/1e6:.1f} MB", flush=True)
        if i == 1:
            print("  --- schema of first file ---")
            peek(dest)
    print("done ->", OUT)

if __name__ == "__main__":
    main()
