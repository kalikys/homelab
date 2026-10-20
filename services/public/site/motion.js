// Scroll motion for the mission-poster page: reveals, the flight progress bar, interludes that open
// in the middle of the view, the hero clip, and one "chapter reached" beacon per chapter (retention).
// Pure math lives in motion-core.js. Without JS the page is complete and static.
(function () {
  "use strict";

  const root = document.documentElement;
  const M = window.MotionCore;
  const T = window.TrackCore;
  if (!M) return;

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
  if ("IntersectionObserver" in window) {
    const seen = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) { reach(e.target.id); seen.unobserve(e.target); } });
    }, { rootMargin: "0px 0px -40% 0px" });
    chapters.slice(1).forEach((c) => seen.observe(c));
  }

  // ---- Reveals: elements fade up once; siblings get a short stagger ----
  root.classList.add("js");
  const reveals = Array.from(document.querySelectorAll(".reveal"));
  const groups = new Map();
  reveals.forEach((el) => {
    const parent = el.parentElement;
    const n = groups.get(parent) || 0;
    groups.set(parent, n + 1);
    el.style.setProperty("--d", Math.min(n, 6) * 60 + "ms");
  });
  if (reduce || !("IntersectionObserver" in window)) {
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
  if (video && !reduce && "IntersectionObserver" in window) {
    const saveData = navigator.connection && navigator.connection.saveData;
    let loaded = false;
    function load() {
      if (loaded || saveData) return;
      loaded = true;
      const webm = document.createElement("source");
      webm.src = video.dataset.srcWebm; webm.type = "video/webm";
      const mp4 = document.createElement("source");
      mp4.src = video.dataset.src; mp4.type = "video/mp4";
      video.append(webm, mp4);
      video.load();
      video.addEventListener("playing", () => video.classList.add("is-playing"), { once: true });
    }
    new IntersectionObserver((entries) => {
      const on = entries[0].isIntersecting;
      if (on) { load(); video.play().catch(() => {}); } else if (loaded) video.pause();
    }, { threshold: 0.2 }).observe(video.parentElement);
    document.addEventListener("visibilitychange", () => { if (document.hidden) video.pause(); });
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
