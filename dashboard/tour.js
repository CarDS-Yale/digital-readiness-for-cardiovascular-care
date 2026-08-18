/* tour.js — shared walkthrough engine for the CarDS dashboards.
   Dependency-free. Each app defines its steps and calls:
     const tour = new MiniTour.Tour({ key, steps, onEnd });
     MiniTour.offer({ key, title, body, onStart: () => tour.start() });
   A step: { target: cssSelector | () => Element | null,
             title, html, before: async () => {}, place: "auto"|"center" }
   target null (or place "center") shows a centered card with a full dim. */
(function () {
  "use strict";

  const Z = 10500;
  const CSS = `
  .mt-dim { position: fixed; background: rgba(15,18,24,.45); z-index: ${Z};
            transition: all .28s cubic-bezier(.4,0,.2,1); }
  .mt-ring { position: fixed; z-index: ${Z + 1}; pointer-events: none;
             border: 2px solid #1f5fa6; border-radius: 10px;
             box-shadow: 0 0 0 4px rgba(31,95,166,.25), 0 4px 24px rgba(0,0,0,.25);
             transition: all .28s cubic-bezier(.4,0,.2,1); }
  .mt-card { position: fixed; z-index: ${Z + 2}; width: 340px; max-width: calc(100vw - 32px);
             background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
             box-shadow: 0 1px 2px rgba(0,0,0,.05), 0 12px 40px rgba(0,0,0,.22);
             font-family: Arial, "Helvetica Neue", sans-serif; color: #000;
             padding: 16px 18px 14px; transition: opacity .2s ease; }
  .mt-eyebrow { font-size: 11.5px; font-weight: 700;
                color: #71767f; margin-bottom: 4px; }
  .mt-title { font-size: 15.5px; font-weight: 700; margin: 0 0 7px; letter-spacing: -0.01em; }
  .mt-body { font-size: 13px; line-height: 1.55; color: #1f2937; }
  .mt-body b { color: #000; }
  .mt-sw { display: inline-block; width: 10px; height: 10px; border-radius: 50%;
           margin: 0 3px -1px 1px; }
  .mt-foot { display: flex; align-items: center; justify-content: space-between;
             margin-top: 14px; }
  .mt-dots { display: flex; gap: 5px; }
  .mt-dot { width: 7px; height: 7px; border-radius: 50%; background: #d8dce1; }
  .mt-dot.on { background: #1f5fa6; }
  .mt-btns { display: flex; gap: 8px; }
  .mt-btn { border: 1px solid #e5e7eb; background: #fff; color: #000;
            font: 700 12.5px Arial, sans-serif; border-radius: 999px;
            padding: 6px 14px; cursor: pointer; }
  .mt-btn:hover { box-shadow: 0 1px 6px rgba(0,0,0,.12); }
  .mt-btn.primary { background: #1f5fa6; border-color: #1f5fa6; color: #fff; }
  .mt-skip { position: absolute; top: 10px; right: 12px; border: none; background: none;
             color: #71767f; font: 400 12px Arial, sans-serif; cursor: pointer;
             padding: 4px 6px; border-radius: 6px; }
  .mt-skip:hover { background: #f2f3f5; color: #000; }
  .mt-loading { position: fixed; z-index: ${Z + 3}; top: 18px; left: 50%;
                transform: translateX(-50%); background: #fff; border: 1px solid #e5e7eb;
                border-radius: 999px; padding: 7px 16px; font: 700 12px Arial, sans-serif;
                color: #4b5563; box-shadow: 0 2px 12px rgba(0,0,0,.15); display: none; }
  .mt-offer { position: fixed; inset: 0; z-index: ${Z + 4};
              background: rgba(15,18,24,.45); display: flex;
              align-items: center; justify-content: center; }
  .mt-offer-card { background: #fff; border-radius: 14px; width: 400px;
                   max-width: calc(100vw - 40px); padding: 24px 26px 20px;
                   font-family: Arial, sans-serif; color: #000;
                   box-shadow: 0 20px 60px rgba(0,0,0,.3); text-align: left; }
  .mt-offer-card h2 { font-size: 18px; margin: 0 0 8px; letter-spacing: -0.01em; }
  .mt-offer-card p { font-size: 13.5px; line-height: 1.55; color: #1f2937; margin: 0 0 18px; }
  .mt-offer-btns { display: flex; gap: 10px; justify-content: flex-end; }
  .mt-btn:focus-visible, .mt-skip:focus-visible {
    outline: 2px solid #1f5fa6; outline-offset: 2px;
  }
  @media (prefers-reduced-motion: reduce) {
    .mt-dim, .mt-ring, .mt-card { transition: none !important; }
  }
  `;

  function injectCss() {
    if (document.getElementById("mt-style")) return;
    const s = document.createElement("style");
    s.id = "mt-style";
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function mk(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  class Tour {
    constructor({ key, steps, onEnd }) {
      this.key = key;
      this.steps = steps;
      this.onEnd = onEnd || (() => {});
      this.i = -1;
      this.active = false;
      this._onResize = () => { if (this.active) this._position(); };
      this._onKey = e => {
        if (!this.active) return;
        if (e.key === "Escape") { e.stopPropagation(); this.end(); }
        else if (e.key === "ArrowRight") this.next();
        else if (e.key === "ArrowLeft") this.back();
      };
    }

    start() {
      injectCss();
      if (this.active) this._teardown();
      this.active = true;
      this.dims = [mk("div", "mt-dim"), mk("div", "mt-dim"),
                   mk("div", "mt-dim"), mk("div", "mt-dim")];
      this.ring = mk("div", "mt-ring");
      this.card = mk("div", "mt-card");
      this.card.setAttribute("role", "dialog");
      this.card.setAttribute("aria-modal", "true");
      this.card.setAttribute("aria-label", "Guided walkthrough");
      this.loading = mk("div", "mt-loading", "One moment…");
      this.dims.forEach(d => document.body.appendChild(d));
      document.body.appendChild(this.ring);
      document.body.appendChild(this.card);
      document.body.appendChild(this.loading);
      window.addEventListener("resize", this._onResize);
      window.addEventListener("keydown", this._onKey, true);
      this._show(0);
    }

    async _show(i) {
      this.i = i;
      const s = this.steps[i];
      this.card.style.opacity = "0";
      if (s.before) {
        this.loading.style.display = "block";
        try { await s.before(); } catch (e) { console.warn("tour step", i, e); }
        this.loading.style.display = "none";
      }
      if (!this.active) return;
      this._render(s);
      this._position();
      this.card.style.opacity = "1";
    }

    _target(s) {
      if (!s.target || s.place === "center") return null;
      const t = typeof s.target === "function" ? s.target()
                : document.querySelector(s.target);
      if (!t) return null;
      const r = t.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return null;
      return r;
    }

    _render(s) {
      const n = this.steps.length;
      const dots = this.steps.map((_, k) =>
        `<span class="mt-dot${k === this.i ? " on" : ""}"></span>`).join("");
      this.card.innerHTML = `
        <button class="mt-skip" aria-label="Skip the tour">Skip tour ✕</button>
        <div class="mt-eyebrow">Step ${this.i + 1} of ${n}</div>
        <div class="mt-title">${s.title}</div>
        <div class="mt-body">${s.html}</div>
        <div class="mt-foot">
          <div class="mt-dots">${dots}</div>
          <div class="mt-btns">
            ${this.i > 0 ? `<button class="mt-btn" data-a="back">Back</button>` : ""}
            <button class="mt-btn primary" data-a="next">${this.i === n - 1 ? "Done" : "Next"}</button>
          </div>
        </div>`;
      this.card.querySelector(".mt-skip").onclick = () => this.end();
      this.card.querySelectorAll(".mt-btn").forEach(b => {
        b.onclick = () => (b.dataset.a === "back" ? this.back() : this.next());
      });
      // keep keyboard focus inside the dialog while the tour runs
      const primary = this.card.querySelector(".mt-btn.primary");
      if (primary) primary.focus({ preventScroll: true });
      this.card.onkeydown = e => {
        if (e.key !== "Tab") return;
        const items = [...this.card.querySelectorAll("button")];
        const first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      };
    }

    _position() {
      const s = this.steps[this.i];
      const r = this._target(s);
      const vw = window.innerWidth, vh = window.innerHeight, PAD = 8;
      if (!r) {                                   // centered step: full dim
        this._dimRects([{ x: 0, y: 0, w: vw, h: vh }, ...Array(3).fill({ x: 0, y: 0, w: 0, h: 0 })]);
        this.ring.style.display = "none";
        this.card.style.left = Math.max(16, (vw - this.card.offsetWidth) / 2) + "px";
        this.card.style.top = Math.max(16, (vh - this.card.offsetHeight) / 2.3) + "px";
        return;
      }
      const x0 = Math.max(0, r.left - PAD), y0 = Math.max(0, r.top - PAD);
      const x1 = Math.min(vw, r.right + PAD), y1 = Math.min(vh, r.bottom + PAD);
      this._dimRects([
        { x: 0, y: 0, w: vw, h: y0 },             // top
        { x: 0, y: y1, w: vw, h: vh - y1 },       // bottom
        { x: 0, y: y0, w: x0, h: y1 - y0 },       // left
        { x: x1, y: y0, w: vw - x1, h: y1 - y0 }, // right
      ]);
      this.ring.style.display = "block";
      Object.assign(this.ring.style, {
        left: x0 + "px", top: y0 + "px",
        width: (x1 - x0) + "px", height: (y1 - y0) + "px",
      });
      // card placement: below, above, right, left; clamp to viewport
      const cw = this.card.offsetWidth, ch = this.card.offsetHeight, G = 14;
      let cx, cy;
      if (y1 + G + ch < vh) { cy = y1 + G; cx = Math.min(Math.max(16, x0), vw - cw - 16); }
      else if (y0 - G - ch > 0) { cy = y0 - G - ch; cx = Math.min(Math.max(16, x0), vw - cw - 16); }
      else if (x1 + G + cw < vw) { cx = x1 + G; cy = Math.min(Math.max(16, y0), vh - ch - 16); }
      else { cx = Math.max(16, x0 - G - cw); cy = Math.min(Math.max(16, y0), vh - ch - 16); }
      this.card.style.left = cx + "px";
      this.card.style.top = cy + "px";
    }

    _dimRects(rects) {
      this.dims.forEach((d, k) => {
        const r = rects[k];
        Object.assign(d.style, {
          left: r.x + "px", top: r.y + "px",
          width: r.w + "px", height: r.h + "px",
        });
      });
    }

    next() { this.i >= this.steps.length - 1 ? this.end(true) : this._show(this.i + 1); }
    back() { if (this.i > 0) this._show(this.i - 1); }

    end(completed) {
      if (!this.active) return;
      this.active = false;
      this._teardown();
      try { sessionStorage.setItem("mt-dismissed-" + this.key, "1"); } catch (e) {}
      this.onEnd(!!completed);
    }

    _teardown() {
      [...(this.dims || []), this.ring, this.card, this.loading]
        .forEach(e => e && e.remove());
      window.removeEventListener("resize", this._onResize);
      window.removeEventListener("keydown", this._onKey, true);
    }
  }

  function offer({ key, title, body, onStart }) {
    injectCss();
    let seen = false;
    try { seen = !!sessionStorage.getItem("mt-dismissed-" + key); } catch (e) {}
    if (seen) return;
    const wrap = mk("div", "mt-offer");
    wrap.innerHTML = `
      <div class="mt-offer-card" role="dialog" aria-label="Walkthrough offer">
        <h2>${title}</h2>
        <p>${body}</p>
        <div class="mt-offer-btns">
          <button class="mt-btn" data-a="no">Not now</button>
          <button class="mt-btn primary" data-a="yes">Start the tour</button>
        </div>
      </div>`;
    const done = start => {
      try { sessionStorage.setItem("mt-dismissed-" + key, "1"); } catch (e) {}
      wrap.remove();
      if (start) onStart();
    };
    wrap.querySelector('[data-a="no"]').onclick = () => done(false);
    wrap.querySelector('[data-a="yes"]').onclick = () => done(true);
    wrap.addEventListener("keydown", e => { if (e.key === "Escape") done(false); });
    setTimeout(() => { const b = wrap.querySelector('[data-a="yes"]'); if (b) b.focus(); }, 50);
    wrap.addEventListener("click", e => { if (e.target === wrap) done(false); });
    document.body.appendChild(wrap);
  }

  window.MiniTour = { Tour, offer, sleep };
})();
