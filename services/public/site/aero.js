(function () {
  "use strict";

  // The aerospace section: a spaceplane flies a minimum-energy ballistic arc from Tbilisi (TBS)
  // to Košice (KSC). The trajectory is integrated here in the browser: point-mass gravity,
  // spherical non-rotating Earth, no atmosphere. Drawn to scale, altitude included.
  const svg = document.getElementById("flight-svg");
  if (!svg) return;

  const lang = ["ru", "sk"].includes(document.documentElement.lang) ? document.documentElement.lang : "en";
  const PHASE = {
    en: { ascent: "ascent", apogee: "apogee", descent: "descent", entry: "entry", landed: "landed" },
    ru: { ascent: "подъём", apogee: "апогей", descent: "спуск", entry: "вход в атм.", landed: "посадка" },
    sk: { ascent: "stúpanie", apogee: "apogeum", descent: "klesanie", entry: "vstup do atm.", landed: "pristátie" },
  }[lang];

  const MU = 3.986004418e14;   // m^3/s^2
  const R = 6371e3;            // m
  const RANGE = 2005e3;        // TBS to KSC great circle, m
  const GAMMA = (40.5 * Math.PI) / 180; // minimum-energy flight path angle for this range

  function fly(v, dt) {
    let x = 0, y = R, vx = v * Math.cos(GAMMA), vy = v * Math.sin(GAMMA), t = 0;
    const pts = [];
    for (;;) {
      const r = Math.hypot(x, y);
      pts.push({ t, s: Math.atan2(x, y) * R, h: r - R, v: Math.hypot(vx, vy), up: x * vx + y * vy > 0 });
      if (t > 0 && r < R) break;
      const a = -MU / (r * r * r);
      vx += a * x * dt; vy += a * y * dt;
      x += vx * dt; y += vy * dt; t += dt;
    }
    return pts;
  }

  // Burnout speed that lands the arc on Košice.
  let lo = 3000, hi = 6000;
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2;
    const p = fly(mid, 2);
    if (p[p.length - 1].s < RANGE) lo = mid; else hi = mid;
  }
  const track = fly((lo + hi) / 2, 0.5);
  const last = track[track.length - 1];
  last.h = 0; last.s = RANGE;
  const apogee = track.reduce((m, p) => (p.h > m.h ? p : m), track[0]);

  // Geometry: true scale, Earth as a circle whose top sits near the bottom of the view.
  const W = 800, PAD = 70, BASE = 250;
  const k = (W - 2 * PAD) / (RANGE / 1000);     // px per km along the ground
  const Rpx = (R / 1000) * k;
  const cx = W / 2, cy = BASE + Rpx;
  const mid = RANGE / 2;
  function pos(s, h) {
    const phi = (s - mid) / R;
    const rr = ((R + h) / 1000) * k;
    return [cx + rr * Math.sin(phi), cy - rr * Math.cos(phi)];
  }
  function arc(h, s0, s1) {
    const n = 48, out = [];
    for (let i = 0; i <= n; i++) {
      const p = pos(s0 + ((s1 - s0) * i) / n, h);
      out.push((i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1));
    }
    return out.join("");
  }
  const NS = "http://www.w3.org/2000/svg";
  function node(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const a in attrs) n.setAttribute(a, attrs[a]);
    if (parent) parent.appendChild(n);
    return n;
  }

  const span = RANGE * 0.62;
  const earth = arc(0, -span, RANGE + span);
  document.getElementById("flight-earth").setAttribute("d", earth + "L" + W + " 340L0 340Z");
  document.getElementById("flight-atmo").setAttribute("d", arc(100e3, -span, RANGE + span) + "L" + W + " 340L0 340Z");
  document.getElementById("flight-karman").setAttribute("d", arc(100e3, -span, RANGE + span));
  const kl = pos(RANGE * 0.6, 100e3);
  const klabel = document.getElementById("flight-karman-label");
  klabel.setAttribute("x", (kl[0] + 6).toFixed(0));
  klabel.setAttribute("y", (kl[1] - 6).toFixed(0));

  const path = track.map((p, i) => {
    const q = pos(p.s, p.h);
    return (i ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1);
  }).join("");
  document.getElementById("flight-ghost").setAttribute("d", path);

  // Stars, placed once with a fixed seed so the sky does not jump between visits.
  const stars = document.getElementById("flight-stars");
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let i = 0; i < 46; i++) {
    const c = node("circle", { cx: (rnd() * W).toFixed(0), cy: (rnd() * 200).toFixed(0), r: (0.4 + rnd() * 0.9).toFixed(2) }, stars);
    c.style.animationDelay = (rnd() * 4).toFixed(2) + "s";
    c.style.opacity = (0.3 + rnd() * 0.6).toFixed(2);
  }

  const sites = document.getElementById("flight-sites");
  [[0, "TBS", "Tbilisi", "start"], [RANGE, "KSC", "Košice", "end"]].forEach(([s, code, city, anchor]) => {
    const [x, y] = pos(s, 0);
    const g = node("g", { class: "flight__site" }, sites);
    node("circle", { cx: x.toFixed(1), cy: y.toFixed(1), r: 4 }, g);
    const dx = anchor === "start" ? -8 : 8;
    const ta = anchor === "start" ? "start" : "end";
    node("text", { x: (x + dx).toFixed(0), y: (y + 22).toFixed(0), "text-anchor": ta }, g).textContent = code;
    node("text", { x: (x + dx).toFixed(0), y: (y + 36).toFixed(0), "text-anchor": ta, class: "flight__label" }, g).textContent = city;
  });

  const craft = document.getElementById("flight-craft");
  const plume = document.getElementById("flight-plume");
  const trail = document.getElementById("flight-trail-path");
  const tm = {
    t: document.getElementById("tm-t"), alt: document.getElementById("tm-alt"),
    vel: document.getElementById("tm-vel"), range: document.getElementById("tm-range"),
    phase: document.getElementById("tm-phase"),
  };
  const nf = new Intl.NumberFormat(lang === "en" ? "en-US" : lang, { maximumFractionDigits: 0 });
  const nf2 = new Intl.NumberFormat(lang === "en" ? "en-US" : lang, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function sample(t) {
    const i = Math.min(track.length - 2, Math.floor(t / 0.5));
    const a = track[i], b = track[i + 1], f = Math.min(1, Math.max(0, (t - a.t) / 0.5));
    return { t, s: a.s + (b.s - a.s) * f, h: a.h + (b.h - a.h) * f, v: a.v + (b.v - a.v) * f, up: a.up, i };
  }

  function draw(t) {
    const p = sample(Math.min(t, last.t));
    const [x, y] = pos(p.s, p.h);
    const ahead = sample(Math.min(t + 2, last.t));
    const [x2, y2] = pos(ahead.s, ahead.h);
    const ang = t >= last.t ? 0 : (Math.atan2(y2 - y, x2 - x) * 180) / Math.PI;
    craft.setAttribute("transform", `translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${ang.toFixed(1)})`);
    plume.classList.toggle("is-on", t < 18);

    const pts = [];
    for (let j = 0; j <= p.i; j += 2) {
      const q = pos(track[j].s, track[j].h);
      pts.push((j ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1));
    }
    pts.push("L" + x.toFixed(1) + " " + y.toFixed(1));
    trail.setAttribute("d", pts.join(""));

    const sec = Math.round(p.t);
    tm.t.textContent = String(Math.floor(sec / 60)).padStart(2, "0") + ":" + String(sec % 60).padStart(2, "0");
    tm.alt.textContent = nf.format(p.h / 1000) + " km";
    tm.vel.textContent = nf2.format(t >= last.t ? 0 : p.v / 1000) + " km/s";
    tm.range.textContent = nf.format(p.s / 1000) + " km";
    let ph;
    if (t >= last.t) ph = "landed";
    else if (Math.abs(p.t - apogee.t) < 25) ph = "apogee";
    else if (p.up) ph = "ascent";
    else ph = p.h < 100e3 ? "entry" : "descent";
    tm.phase.textContent = PHASE[ph];
  }

  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) { draw(apogee.t); return; }

  // 703 s of flight in about 9 s, then a pause on the ground and another flight.
  const SPEED = last.t / 9;
  const PAUSE = 2600;
  let start = null, raf = 0, visible = false;
  function frame(now) {
    if (start === null) start = now;
    const t = ((now - start) / 1000) * SPEED;
    draw(t);
    if (t >= last.t + (PAUSE / 1000) * SPEED) start = now;
    raf = window.requestAnimationFrame(frame);
  }
  function run() {
    if (raf || !visible || document.hidden) return;
    start = null;
    raf = window.requestAnimationFrame(frame);
  }
  function stop() { window.cancelAnimationFrame(raf); raf = 0; }

  draw(0);
  if ("IntersectionObserver" in window) {
    new IntersectionObserver((entries) => {
      visible = entries[0].isIntersecting;
      if (visible) run(); else stop();
    }, { threshold: 0.25 }).observe(svg);
  } else {
    visible = true; run();
  }
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); else run(); });
})();
