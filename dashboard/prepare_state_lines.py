"""prepare_state_lines.py — dissolve counties.geojson into state outlines.

Writes data/states.geojson: one feature per state, the union of its county
polygons. The map draws these as a subtly darker line layer so users can
orient themselves by state borders. Deriving the outlines from the same
county file guarantees the lines sit exactly on the county borders.

Run after the county data prep (any time counties.geojson changes shape).
Requires shapely (pip install shapely).
"""
import json
import os
from collections import defaultdict

from shapely.geometry import shape, mapping
from shapely.ops import unary_union

DASH = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DASH, "data")


def main():
    geo = json.load(open(os.path.join(DATA, "counties.geojson")))
    by_state = defaultdict(list)
    for ft in geo["features"]:
        fips = str(ft["properties"].get("fips_st_cnty", "")).zfill(5)
        try:
            by_state[fips[:2]].append(shape(ft["geometry"]).buffer(0))
        except Exception:
            pass

    feats = []
    for st, geoms in sorted(by_state.items()):
        u = unary_union(geoms)
        feats.append({
            "type": "Feature",
            "id": st,
            "properties": {"state_fips": st},
            "geometry": mapping(u),
        })
        print(f"  state {st}: {len(geoms)} counties dissolved")

    out = {"type": "FeatureCollection", "features": feats}
    path = os.path.join(DATA, "states.geojson")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    print(f"wrote {path} ({os.path.getsize(path)/1e6:.1f} MB, {len(feats)} states)")


if __name__ == "__main__":
    main()
