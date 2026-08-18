"""prepare_fips_patches.py — re-key obsolete county FIPS in counties.geojson.

The county boundary base carries three pre-2015 FIPS codes whose analytic
data lives under a successor code, so their polygons rendered grey and
clicked to "Data unavailable":

  46113 Shannon County, SD   -> 46102 Oglala Lakota County (renamed 2015)
  02270 Wade Hampton, AK     -> 02158 Kusilvak Census Area (renamed 2015)
  51515 Bedford City, VA     -> 51019 Bedford County (merged 2013)

This script renames those features to the successor FIPS and copies the
successor's analytic record onto the feature, so coloring, clicks, search,
and tract drill-in all work. Run AFTER prepare_dashboard_data.py,
prepare_metric_extras.py, and prepare_priority_layers.py (it reads the finished
county_data.json), and BEFORE prepare_tract_geometries_fill.py (which then
sees the successor FIPS and fetches their tract boundaries).
"""
import json
import os

DASH = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DASH, "data")

ALIASES = {"46113": "46102", "02270": "02158", "51515": "51019"}


def main():
    geo = json.load(open(os.path.join(DATA, "counties.geojson")))
    cd = json.load(open(os.path.join(DATA, "county_data.json")))

    n = 0
    for ft in geo["features"]:
        props = ft.get("properties", {})
        old = props.get("fips_st_cnty")
        if old not in ALIASES:
            continue
        new = ALIASES[old]
        rec = cd.get(new)
        if not rec:
            print(f"  [skip] {old} -> {new}: no analytic record")
            continue
        ft["id"] = new
        props.update(rec)
        props["fips_st_cnty"] = new
        n += 1
        print(f"  {old} -> {new} ({rec.get('county_name')})")

    json.dump(geo, open(os.path.join(DATA, "counties.geojson"), "w"),
              separators=(",", ":"))
    print(f"re-keyed {n} features; counties.geojson written")


if __name__ == "__main__":
    main()
