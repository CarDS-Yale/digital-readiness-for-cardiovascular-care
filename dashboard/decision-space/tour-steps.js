/* tour-steps.js — the guided walkthrough for the decision-space scatter.
   Uses ../tour.js (MiniTour) and the window.__ds hooks in index.html. */
(function () {
  "use strict";
  const { Tour, offer, sleep } = window.MiniTour;
  const sw = c => `<span class="mt-sw" style="background:${c}"></span>`;

  async function ready(ms = 12000) {
    const t0 = Date.now();
    while (!window.__ds && Date.now() - t0 < ms) await sleep(200);
    return window.__ds;
  }

  // a mid-chart investment tract for the hover and click demos
  function demoTract() {
    return window.__ds.find(t => t.bucket === 2 && t.rank === 40)
        || window.__ds.find(t => t.bucket === 2 && t.rank != null)
        || window.__ds.find(t => t.bucket === 1);
  }

  function resetAll() {
    const ds = window.__ds;
    if (!ds) return;
    ds.deselect();
    ds.openThresholds(false);
    ds.openList(false);
    ds.clearScope(false);
    ds.resetThresholds();
  }

  const steps = [
    {
      place: "center",
      title: "Welcome to the decision space",
      html: `Every dot is one census tract from the workforce-constrained county pool,
        placed by digital readiness and disease burden. This tour takes about
        three minutes; the chart drives itself and you click <b>Next</b>.
        Press <b>Esc</b> anytime to exit.`,
    },
    {
      target: "#chart",
      title: "How to read the chart",
      before: async () => { await ready(); },
      html: `Left to right runs the <b>Digital Divide Index</b>: further right,
        worse readiness. Bottom to top runs <b>cardiometabolic burden</b>.
        The dashed lines mark the two national cuts. Above the burden line,
        ${sw("#1f5fa6")}blue dots left of the median are <b>deployment-priority
        tracts</b> (higher readiness) and ${sw("#c1272d")}red dots to the right
        are <b>investment-priority tracts</b> (lower readiness).
        ${sw("#b7bcc3")}Grey dots are pool tracts outside both groups.
        Kentucky and Pennsylvania are not plotted; their burden score rests
        on short sleep alone.`,
    },
    {
      target: "#kpis",
      title: "The headline numbers",
      html: `The study totals: <b>49,948</b> workforce-constrained tracts, split into
        ${sw("#1f5fa6")}<b>4,765</b> deployment-priority tracts and
        ${sw("#c1272d")}<b>21,752</b> investment-priority tracts across
        <b>2,526</b> counties. These cards follow whatever thresholds and
        view you set.`,
    },
    {
      target: "#legend",
      title: "Show or hide each group",
      html: `These chips count the plotted dots. Click one to hide that group
        and declutter the view; click again to bring it back.`,
    },
    {
      target: "#chart",
      title: "Hover any dot",
      before: async () => {
        await ready();
        window.__ds.hover(demoTract());
        await sleep(400);
      },
      html: `Point at any dot and it grows, with a mini profile: the tract,
        its county, its DDI and burden values, and its rank. We are
        hovering a high-ranked investment-priority tract right now.`,
    },
    {
      target: "#panel",
      title: "Click for the full profile",
      before: async () => {
        await ready();
        window.__ds.select(demoTract());
        await sleep(400);
      },
      html: `A click opens this panel: a plain-language read of the tract, its
        priority group and rank, disease burden detail, Digital Divide
        sub-scores, and the parent county's cardiology workforce. Close it
        with the ✕, the <b>Esc</b> key, or a click on empty space.`,
    },
    {
      target: "#thr-panel",
      title: "Set the thresholds",
      before: async () => {
        await ready();
        window.__ds.deselect();
        window.__ds.openThresholds(true);
        await sleep(250);
        window.__ds.setPreset("p75", "quart");
        await sleep(450);
      },
      html: `The study anchors the cuts at the national mean burden and the
        national median DDI. Here you can move them. We just chose the
        <b>top 25%</b> of burden and a <b>quartile split</b> of readiness:
        the dashed lines moved, the counts changed, and the grey band in the
        middle now belongs to neither group. The presets match the
        manuscript's threshold analysis; the sliders take any value.`,
    },
    {
      target: ".search-wrap",
      title: "Restrict the view",
      before: async () => {
        await ready();
        window.__ds.openThresholds(false);
        window.__ds.resetThresholds();
        window.__ds.setScope("state", "IL");
        await sleep(450);
      },
      html: `Type a state, county or metropolitan area here and pick it from
        the list. We chose <b>Illinois</b>: its tracts stay in color, the rest
        of the country fades, and the counts switch to the state. A metro
        area such as "Chicago" or a county such as "Cook" works the same way.`,
    },
    {
      target: "#list-panel",
      title: "List the leading tracts",
      before: async () => {
        await ready();
        window.__ds.openList(true);
        window.__ds.setListN(10);
        await sleep(450);
      },
      html: `This list ranks the tracts under your current thresholds and
        view: here the ten leading deployment-priority tracts in Illinois,
        spotlighted on the chart. Switch to investment priority, widen the
        list to 25, 50 or 100, click a row for the full profile, or download
        the list as a CSV with the settings recorded in its header.`,
    },
    {
      target: "#settings-line",
      title: "Back to the study view",
      before: async () => {
        await ready();
        resetAll();
        await sleep(350);
      },
      html: `This line always states the thresholds and view in force, and
        <b>Reset to study view</b> returns to the published settings.
        Explore freely: nothing you do here changes the data.`,
    },
    {
      target: "#tour-btn",
      title: "That is the tour",
      html: `Restart it anytime from this <b>Tour</b> button. The <b>About</b>
        button next to it holds the methods, data sources, and limitations.
        Happy exploring.`,
    },
  ];

  const tour = new Tour({
    key: "decision-space",
    steps,
    onEnd: () => {
      try { resetAll(); } catch (e) {}
    },
  });

  document.getElementById("tour-btn").addEventListener("click", () => tour.start());

  offer({
    key: "decision-space",
    title: "Take a quick tour?",
    body: `New here? A three-minute walkthrough explains the axes and colors,
      demos hover and click, and shows how to set thresholds, restrict the
      view and list the leading tracts. The chart drives itself; you just
      click Next.`,
    onStart: () => tour.start(),
  });
})();
