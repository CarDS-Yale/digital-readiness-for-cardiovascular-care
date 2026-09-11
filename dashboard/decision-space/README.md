# Implementation Decision Space (interactive)

An interactive version of Figure 2 from the manuscript. Every tract in the
workforce-constrained county pool is one point, plotted by Digital Divide Index (x)
and cardiometabolic burden z score (y). Blue points are deployment-priority tracts,
red points are investment-priority tracts, and grey points are pool tracts outside
both groups. Hover a point to inspect it. Click it to open a full tract profile in
a sidebar. Click the legend chips to show or hide each group.

The page uses the priority matrix framing from `build_master.py`: anchored
cuts at burden z > 0 and the national median DDI (18.77, reported as 18.8 in the
manuscript), on the workforce-constrained pool (2,582 counties; 49,948 tracts;
4,765 deployment priority; 21,752 investment priority).

## Files

```
decision-space/
├── index.html                       # The whole app (Arial, no build step)
├── d3.v7.min.js                     # D3 vendored locally, no CDN needed
├── README.md
├── prepare_decision_space_data.py   # Regenerates the data file
└── data/
    └── decision_space.json          # ~5 MB, one record per pool tract
```

## Run locally

Browsers block `fetch` over `file://`, so serve the folder:

```bash
cd dashboard/decision-space
python3 -m http.server 8000
# open http://localhost:8000
```

## Deploy

Upload the folder to any static host, next to the main dashboard. Turn on
gzip for `.json` (the data file drops from 5 MB to about 1.3 MB on the wire).

## Refresh the data

Run from this folder after the upstream pipeline changes:

```bash
python3 prepare_decision_space_data.py
```

The script reads `outputs/burden_workforce/`, `outputs/ahrf_workforce_trend_summary.csv`,
`DDI/2022-2024 US DDI.xlsx`, `outputs/master/`, and
`dashboard/data/{tract_data,county_data}.json` from the repo root. It rebuilds
the workforce-constrained pool, checks the boxes against the ranked priority CSVs
written by `export_priority_lists.py`, and writes `data/decision_space.json`.
