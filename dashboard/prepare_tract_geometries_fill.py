"""prepare_tract_geometries_fill.py — fill in missing per-county tract files.

The original prepare_tract_geometries.py was run with scope=pool, so only
the 2,421 high-need counties have data/tracts/{fips}.geojson. This script
builds the files for every county still missing one, so the map can show
tract polygons everywhere (e.g. Platte, MO).

Boundaries come from the Census 2020 cartographic 500k tract GeoJSON,
fetched per state from the loganpowell/census-geojson mirror (the same
source figures_common.py uses for Figure 4). The 2020 vintage also fills
the 7 pool counties the 2023 file could not (the 5 old Connecticut
counties, Valdez-Cordova AK, Bedford City VA). Geometries are simplified
to ~50 m, matching the original script.

Usage:  python3 prepare_tract_geometries_fill.py         (from dashboard/)
"""
import json
import os
import urllib.request

from shapely.geometry import shape, mapping

DASH = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DASH, "data")
OUT = os.path.join(DATA, "tracts")
CACHE = os.path.join(DASH, "_tract_geo_cache")
URL = ("https://raw.githubusercontent.com/loganpowell/census-geojson/"
       "master/GeoJSON/500k/2020/{st}/tract.json")
TOL = 0.0005
os.makedirs(OUT, exist_ok=True)
os.makedirs(CACHE, exist_ok=True)


def main():
    geo = json.load(open(os.path.join(DATA, "counties.geojson")))
    all_fips = {ft["properties"]["fips_st_cnty"] for ft in geo["features"]}
    have = {f[:5] for f in os.listdir(OUT) if f.endswith(".geojson")}
    missing = sorted(all_fips - have)
    states = sorted({f[:2] for f in missing})
    print(f"counties total {len(all_fips):,} | have {len(have):,} | "
          f"missing {len(missing):,} across {len(states)} states")

    n_written = n_tracts = 0
    for st in states:
        need = [f for f in missing if f[:2] == st]
        path = os.path.join(CACHE, f"tract_{st}.json")
        if not os.path.exists(path):
            try:
                urllib.request.urlretrieve(URL.format(st=st), path)
            except Exception as e:
                print(f"  [skip] state {st}: {e}")
                continue
        try:
            feats = json.load(open(path))["features"]
        except Exception as e:
            print(f"  [skip] state {st}: bad file ({e})")
            os.remove(path)
            continue
        by_cnty = {}
        for ft in feats:
            g5 = str(ft["properties"]["GEOID"])[:5]
            if g5 in need:
                by_cnty.setdefault(g5, []).append(ft)
        for fips, fts in by_cnty.items():
            out = []
            for ft in fts:
                tfips = str(ft["properties"]["GEOID"]).zfill(11)
                geom = shape(ft["geometry"]).simplify(TOL, preserve_topology=True)
                out.append({
                    "type": "Feature",
                    "id": tfips,
                    "properties": {"fips_tract": tfips, "fips_st_cnty": fips},
                    "geometry": mapping(geom),
                })
            fc = {"type": "FeatureCollection", "features": out}
            json.dump(fc, open(os.path.join(OUT, f"{fips}.geojson"), "w"),
                      separators=(",", ":"))
            n_written += 1
            n_tracts += len(out)
        print(f"  state {st}: wrote {len(by_cnty)}/{len(need)} missing counties")

    mb = sum(os.path.getsize(os.path.join(OUT, f))
             for f in os.listdir(OUT)) / 1e6
    print(f"\nwrote {n_written:,} new county files ({n_tracts:,} tracts); "
          f"tracts/ now {mb:.0f} MB")
    still = sorted(all_fips - {f[:5] for f in os.listdir(OUT)})
    if still:
        print(f"still missing ({len(still)}): {still[:20]}{'...' if len(still) > 20 else ''}")


if __name__ == "__main__":
    main()
