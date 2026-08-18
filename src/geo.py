"""
Shared map geometry and palette for the figure scripts.

Albers conic projection with separate parameters for the contiguous states,
Alaska and Hawaii, so the insets keep sensible shapes. County outlines ship
with the repository; tract boundaries are pulled per state from a mirror of
the Census 2020 cartographic 500k files and cached under tract_geo/.
"""
import json
import os
import urllib.request

import numpy as np

PD_ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO_DIR = os.path.join(PD_, "tract_geo")
os.makedirs(GEO_DIR, exist_ok=True)

TRACT_URL = ("https://raw.githubusercontent.com/loganpowell/census-geojson/"
             "master/GeoJSON/500k/2020/{st}/tract.json")

# investment red, deployment blue: used by every figure
INV, DEP = "#c1272d", "#1f5fa6"
DPI = 300

TERRITORIES = {"60", "66", "69", "72", "78"}

PROJ = {"conus": (29.5, 45.5, 23.0, -96.0),
        "ak":    (55.0, 65.0, 50.0, -154.0),
        "hi":    (8.0, 18.0, 13.0, -157.0)}


def albers(lon, lat, lat1, lat2, lat0, lon0):
    lon, lat = np.radians(lon), np.radians(lat)
    lat1, lat2, lat0, lon0 = map(np.radians, (lat1, lat2, lat0, lon0))
    n = 0.5 * (np.sin(lat1) + np.sin(lat2))
    C = np.cos(lat1) ** 2 + 2 * n * np.sin(lat1)
    rho = np.sqrt(C - 2 * n * np.sin(lat)) / n
    rho0 = np.sqrt(C - 2 * n * np.sin(lat0)) / n
    th = n * (lon - lon0)
    return rho * np.sin(th), rho0 - rho * np.cos(th)


def county_polys():
    """fips -> list of rings [[x,y],...] in lon/lat, dateline-wrapped."""
    gj = json.load(open(os.path.join(PD_, "geojson-counties-fips.json")))
    out = {}
    for ft in gj["features"]:
        fips = str(ft.get("id", "")).zfill(5)
        g = ft["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        rings = []
        for poly in polys:
            r = np.asarray(poly[0], dtype=float)
            r[:, 0] = np.where(r[:, 0] > 0, r[:, 0] - 360, r[:, 0])  # Aleutians
            rings.append(r)
        out[fips] = rings
    return out


def region_of(fips):
    if fips[:2] in TERRITORIES:
        return None
    return "ak" if fips.startswith("02") else "hi" if fips.startswith("15") else "conus"


def fetch_tracts(states):
    import urllib.request
    feats = []
    for st in states:
        path = os.path.join(GEO_DIR, f"tract_{st}.json")
        if not os.path.exists(path):
            print(f"  downloading tract boundaries for state {st} ...")
            urllib.request.urlretrieve(TRACT_URL.format(st=st), path)
        feats += json.load(open(path))["features"]
    return feats
