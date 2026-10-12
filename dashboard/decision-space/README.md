# Implementation Decision Space (interactive)

An interactive version of Figure 2 from the manuscript. Every tract in the
workforce-constrained county pool is one point, plotted by Digital Divide Index (x)
and cardiometabolic burden z score (y). Blue points are deployment-priority tracts,
red points are investment-priority tracts, and grey points are pool tracts outside
both groups. Hover a point to inspect it. Click it to open a full tract profile in
a sidebar. Click the legend chips to show or hide each group.

The page opens on the study settings from `build_master.py`: anchored cuts at
burden z > 0 and the national median DDI (18.77, reported as 18.8 in the
manuscript), on the workforce-constrained pool (2,582 counties; 49,948 tracts;
4,765 deployment priority; 21,752 investment priority).

## Controls

**Thresholds** (top right). The burden cut and the two readiness cuts can be
moved with sliders or set to presets. The presets are the national percentiles
used in the manuscript's threshold analysis (`sens_thresholds.py`): burden
above the mean, in the top quartile or in the top decile; readiness split at
the median, at the quartiles or at the deciles. With a quartile or decile
split, tracts between the two readiness cuts belong to neither group.

At the study defaults the page uses the published group membership and ranks
as they are. Under any other setting it reclassifies every tract in the
browser and ranks each group by the priority score (burden minus DDI for
deployment, burden plus DDI for investment, both standardized within the
pool). The scores are fixed, so a stricter cut keeps the study ordering and
drops the tracts that miss it, as in the manuscript. The data file stores
DDI to two decimals and burden to four, so counts under a preset can differ
from Table S25 by a tract or two at the cut.

**View** (search box). Type a state, county or metropolitan area and pick it.
Tracts outside the area fade, the KPI cards and legend switch to the area,
and the list below ranks the area's tracts. Metropolitan areas are the 2023
core-based statistical areas from the Area Health Resources Files (metro
areas only, not micropolitan). The settings line under the KPI cards always
states the thresholds and view in force, with a reset link.

**Leading tracts** (top right). A docked list of the 10, 25, 50 or 100
highest-ranked tracts in either group under the current thresholds and view.
Rows open the tract profile; hovering a row rings its dot; a switch
spotlights the listed tracts on the chart; Download CSV writes the list with
the settings in its header. The rows are keyboard-focusable, so the list is
also the accessible alternative to the canvas.

Kentucky and Pennsylvania tracts count toward the totals under every setting
but are never plotted or ranked, because their burden rests on a single
PLACES measure.

## Files

```
decision-space/
├── index.html                       # The whole app (Arial, no build step)
├── tour-steps.js                    # Guided walkthrough (engine in ../tour.js)
├── d3.v7.min.js                     # D3 vendored locally, no CDN needed
├── README.md
├── prepare_decision_space_data.py   # Regenerates the data file
└── data/
    └── decision_space.json          # ~6 MB, one record per pool tract (not tracked)
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
gzip for `.json` (the data file drops from 6 MB to about 1.6 MB on the wire).

## Refresh the data

Run from this folder after the upstream pipeline changes:

```bash
python3 prepare_decision_space_data.py
```

The script reads `outputs/burden_workforce/`, `outputs/ahrf_workforce_trend_summary.csv`,
`DDI/2022-2024 US DDI.xlsx`, `outputs/master/`, and
`dashboard/data/{tract_data,county_data}.json` from the repo root. It rebuilds
the workforce-constrained pool, checks the boxes against the ranked priority CSVs
written by `export_priority_lists.py`, records the pool standardization and the
national cut points the presets use, and writes `data/decision_space.json`.
