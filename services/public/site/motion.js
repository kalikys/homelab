// Scroll motion for the mission-poster page: reveals, the flight progress bar, interludes that open
// in the middle of the view, the hero clip, and one "chapter reached" beacon per chapter (retention).
// Pure math lives in motion-core.js. Without JS the page is complete and static.
(function () {
  "use strict";

  const root = document.documentElement;
  const M = window.MotionCore;
  const T = window.TrackCore;
  if (!M) return;
  window.__motionReady = true;

  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const lang = ["ru", "sk"].includes(root.lang) ? root.lang : "en";
  const chapters = ["launch", "payload", "flightlog", "origin", "ground", "contact"]
    .map((id) => document.getElementById(id)).filter(Boolean);
  const navLinks = Array.from(document.querySelectorAll(".nav a[data-chapter]"));

  // ---- Retention: count each chapter once per page view (works with reduced motion too) ----
  function source() {
    try { return JSON.parse(window.sessionStorage.getItem("src")) || null; } catch (e) { return null; }
  }
  const reached = new Set();
  function reach(id) {
    if (reached.has(id) || !T || !navigator.sendBeacon) return;
    reached.add(id);
    const event = T.reachEvent(id);
    if (event) navigator.sendBeacon(T.eventPath(event, source(), lang));
  }
  // A chapter counts only after it stays in view for 0.8 s, so jumping through the page
  // with a nav link (smooth scroll) does not count the chapters it flies past.
  if ("IntersectionObserver" in window) {
    const timers = new Map();
    const seen = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        const id = e.target.id;
        if (e.isIntersecting) {
          timers.set(id, setTimeout(() => { reach(id); seen.unobserve(e.target); }, 800));
        } else {
          clearTimeout(timers.get(id));
        }
      });
    }, { rootMargin: "0px 0px -40% 0px" });
    chapters.slice(1).forEach((c) => seen.observe(c));
  }

  // ---- Reveals: elements fade up once; siblings get a short stagger ----
  // js-on.js set .js before first paint; if it already gave up (slow load), keep everything shown.
  const reveals = Array.from(document.querySelectorAll(".reveal"));
  const revealsOn = root.classList.contains("js");
  const groups = new Map();
  reveals.forEach((el) => {
    const parent = el.parentElement;
    const n = groups.get(parent) || 0;
    groups.set(parent, n + 1);
    el.style.setProperty("--d", Math.min(n, 6) * 60 + "ms");
  });
  if (!revealsOn || reduce || !("IntersectionObserver" in window)) {
    reveals.forEach((el) => el.classList.add("is-in"));
  } else {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); } });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    reveals.forEach((el) => io.observe(el));
    // Anything already on screen at load shows at once, without waiting for a scroll.
    requestAnimationFrame(() => reveals.forEach((el) => {
      if (el.getBoundingClientRect().top < window.innerHeight) el.classList.add("is-in");
    }));
  }

  // ---- Hero clip: loads after the page is idle, plays while the poster is on screen ----
  const video = document.getElementById("poster-video");
  if (video && !reduce && "IntersectionObserver" in window && !(navigator.connection && navigator.connection.saveData)) {
    let loaded = false, onScreen = false;
    function load() {
      if (loaded) return;
      loaded = true;
      [["webm", video.dataset.srcWebm], ["mp4", video.dataset.src]].forEach(([type, src]) => {
        const s = document.createElement("source");
        s.src = src; s.type = "video/" + type;
        video.append(s);
      });
      video.load();
      video.addEventListener("playing", () => video.classList.add("is-playing"), { once: true });
    }
    function start() {
      new IntersectionObserver((entries) => {
        onScreen = entries[0].isIntersecting;
        if (onScreen) { load(); video.play().catch(() => {}); } else if (loaded) video.pause();
      }, { threshold: 0.2 }).observe(video.parentElement);
    }
    const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 1200));
    if (document.readyState === "complete") idle(start);
    else window.addEventListener("load", () => idle(start), { once: true });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) video.pause();
      else if (loaded && onScreen) video.play().catch(() => {});
    });
  }

  // ---- Hero orbit (SVG animateMotion): paused off screen, in a hidden tab and under reduced motion ----
  const orbit = document.getElementById("poster-orbit");
  if (orbit && orbit.pauseAnimations) {
    if (reduce) {
      orbit.pauseAnimations();
      orbit.setCurrentTime(6);
    } else if ("IntersectionObserver" in window) {
      let onScreen = true;
      new IntersectionObserver((entries) => {
        onScreen = entries[0].isIntersecting;
        if (onScreen && !document.hidden) orbit.unpauseAnimations(); else orbit.pauseAnimations();
      }).observe(orbit);
      document.addEventListener("visibilitychange", () => {
        if (document.hidden) orbit.pauseAnimations(); else if (onScreen) orbit.unpauseAnimations();
      });
    }
  }

  // ---- Scroll loop: progress bar, current chapter in the nav, interlude openness ----
  const fill = document.getElementById("flightbar-fill");
  const interludes = Array.from(document.querySelectorAll(".interlude"));
  let tops = [];
  function measure() {
    tops = chapters.map((c) => c.getBoundingClientRect().top + window.scrollY);
  }
  let ticking = false;
  let current = -2;
  function update() {
    ticking = false;
    const y = window.scrollY, vh = window.innerHeight;
    if (fill) fill.style.transform = `scaleX(${M.progress(y, root.scrollHeight, vh).toFixed(4)})`;
    const i = M.activeChapter(tops, y + vh * 0.35);
    if (i !== current) {
      current = i;
      const id = chapters[i] ? chapters[i].id : "";
      navLinks.forEach((a) => a.setAttribute("aria-current", a.dataset.chapter === id ? "true" : "false"));
    }
    if (!reduce) {
      interludes.forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.bottom < -vh || r.top > vh * 2) return;
        el.style.setProperty("--open", M.openness(r.top, r.height, vh).toFixed(3));
      });
    }
  }
  function onScroll() { if (!ticking) { ticking = true; requestAnimationFrame(update); } }
  measure();
  update();
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", () => { measure(); onScroll(); });
  // Live blocks (projects, commits, architecture) grow the page after load.
  window.addEventListener("load", () => { measure(); onScroll(); });
  if ("ResizeObserver" in window) new ResizeObserver(() => { measure(); onScroll(); }).observe(document.body);
})();
