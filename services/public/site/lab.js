(function () {
  "use strict";

  // /lab/ and /ru/lab/ are static pages (the Russian one is built by scripts/build-ru.py).
  // This script only fills in the live blocks, in the page language.
  const lang = document.documentElement.lang === "ru" ? "ru" : "en";
  const Core = window.LabCore;

  const EXAMS = [
    { id: "cka", name: "CKA", full: "Certified Kubernetes Administrator" },
    { id: "ckad", name: "CKAD", full: "Certified Kubernetes Application Developer" },
    { id: "cks", name: "CKS", full: "Certified Kubernetes Security Specialist" },
  ];

  const UI = {
    en: {
      error: "Data is not available right now.",
      noCommits: "No commits yet.",
      countdown: (name, days) => (days === 0 ? `${name} exam is today` : `${name} exam in ${days} ${days === 1 ? "day" : "days"}`),
      status: { running: "running", stopped: "stopped", other: "unknown" },
      roles: { cp: "control plane", worker: "worker" },
      up: "up",
      gb: "GB",
      d: "d", h: "h", m: "min",
      live: { on: "Live now", off: "Not on air", none: "Stream is not set up yet" },
    },
    ru: {
      error: "Данные сейчас недоступны.",
      noCommits: "Коммитов пока нет.",
      countdown: (name, days) => (days === 0 ? `Экзамен ${name} сегодня` : `До экзамена ${name} ${days} ${Core.ruPlural(days, "день", "дня", "дней")}`),
      status: { running: "работает", stopped: "выключена", other: "нет данных" },
      roles: { cp: "control plane", worker: "worker" },
      up: "работает",
      gb: "ГБ",
      d: "дн", h: "ч", m: "мин",
      live: { on: "Сейчас в эфире", off: "Сейчас не в эфире", none: "Трансляция ещё не настроена" },
    },
  };
  const t = UI[lang];

  function storageGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function storageSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* storage unavailable */ }
  }

  // Same language rule as the main page: a saved choice wins, then the browser language; crawlers stay put.
  const saved = storageGet("lang");
  const isBot = /bot|crawl|spider|slurp|preview/i.test(navigator.userAgent);
  const preferred = saved || ((navigator.language || "").toLowerCase().startsWith("ru") ? "ru" : "en");
  if (!isBot && preferred !== lang) {
    window.location.replace((preferred === "ru" ? "/ru/lab/" : "/lab/") + window.location.search + window.location.hash);
    return;
  }

  const toggle = document.getElementById("lang-toggle");
  toggle.addEventListener("click", (ev) => {
    ev.preventDefault();
    storageSet("lang", toggle.dataset.target);
    window.location.assign(toggle.getAttribute("href") + window.location.hash);
  });

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function getText(url) {
    return fetch(url).then((res) => (res.ok ? res.text() : Promise.reject(res.status)));
  }

  function getJSON(url, init) {
    return fetch(url, init).then((res) => (res.ok ? res.json() : Promise.reject(res.status)));
  }

  function formatDuration(sec) {
    if (sec >= 86400) return `${Math.floor(sec / 86400)} ${t.d}`;
    if (sec >= 3600) return `${Math.floor(sec / 3600)} ${t.h}`;
    return `${Math.max(1, Math.floor(sec / 60))} ${t.m}`;
  }

  // ---- Progress: one card per exam, domains inside ----

  function certCard(exam, result) {
    const card = el("details", "lab-cert");
    const summary = el("summary", "lab-cert__head");
    summary.append(el("span", "lab-cert__name", exam.name), el("span", "lab-cert__pct", `${result.percent}%`));
    const bar = el("div", "lab-bar");
    const fill = el("div", "lab-bar__fill");
    fill.style.width = `${result.percent}%`;
    bar.append(fill);
    const list = el("ul", "lab-domains");
    result.domains.forEach((d) => {
      const li = el("li", "lab-domain");
      const weight = d.weight === null ? "" : `${d.weight}% · `;
      li.append(el("span", "lab-domain__name", d.name), el("span", "lab-domain__count", `${weight}${d.done}/${d.total}`));
      list.append(li);
    });
    card.append(summary, el("p", "lab-cert__full", exam.full), bar, list);
    return card;
  }

  function loadCerts() {
    const box = document.getElementById("lab-certs");
    Promise.all(EXAMS.map((exam) => getText(`/api/github/certs/${exam.id}.md`).then(Core.parseChecklist).catch(() => null)))
      .then((results) => {
        box.replaceChildren();
        if (results.every((r) => !r)) {
          box.append(el("p", "lab-empty", t.error));
          return;
        }
        EXAMS.forEach((exam, i) => { if (results[i]) box.append(certCard(exam, results[i])); });
      });
  }

  function loadCountdown() {
    getJSON("/api/github/certs/exams.json")
      .then((exams) => {
        const next = Core.nextExam(exams, new Date());
        if (!next) return;
        const exam = EXAMS.find((e) => e.id === next.id);
        const node = document.getElementById("lab-countdown");
        node.textContent = t.countdown(exam ? exam.name : next.id.toUpperCase(), next.days);
        node.hidden = false;
      })
      .catch(() => { /* no dates, no countdown */ });
  }

  // ---- Activity: streak, heatmap, latest commits of k8s-certs ----

  function renderCommits(list) {
    const box = document.getElementById("lab-commits");
    box.replaceChildren();
    if (!list) { box.append(el("li", "commits__empty", t.error)); return; }
    if (!list.length) { box.append(el("li", "commits__empty", t.noCommits)); return; }
    list.slice(0, 5).forEach((c) => {
      const li = el("li", "commit");
      const sha = el("a", "commit__sha", c.sha.slice(0, 7));
      sha.href = c.html_url;
      sha.target = "_blank";
      sha.rel = "noopener";
      li.append(sha, el("span", "commit__msg", c.commit.message.split("\n")[0]), el("span", "commit__time", c.commit.author.date.slice(0, 10)));
      box.append(li);
    });
  }

  function loadActivity() {
    getJSON("/api/github/certs-commits")
      .then((data) => {
        const list = Array.isArray(data) ? data : [];
        const days = Core.activeDays(list);
        const now = new Date();
        document.getElementById("lab-streak").textContent = String(Core.streak(days, now));
        document.getElementById("lab-heatmap").replaceChildren(...Core.heatmap(days, now, 12).map((cell) => {
          const node = el("span", `lab-heat lab-heat--${Math.min(cell.count, 3)}`);
          node.title = `${cell.day}: ${cell.count}`;
          return node;
        }));
        renderCommits(list);
      })
      .catch(() => renderCommits(null));
  }

  // ---- Lab machines and live stream state, from /data/stats.json ----

  function statusChip(state) {
    const chip = el("span", "chip lab-vm__state");
    chip.append(el("span", `dot ${state === "running" ? "dot--ok" : "dot--pending"}`), el("span", "", t.status[state]));
    return chip;
  }

  function renderVms(stats) {
    const box = document.getElementById("lab-vms");
    const vms = stats && Array.isArray(stats.lab) ? stats.lab : null;
    if (!vms || !vms.length) {
      box.replaceChildren(el("p", "lab-empty", t.error));
      return;
    }
    box.replaceChildren(...vms.map((vm) => {
      const state = vm.status === "running" || vm.status === "stopped" ? vm.status : "other";
      const card = el("div", "lab-vm");
      const head = el("div", "lab-vm__head");
      head.append(el("span", "lab-vm__name", vm.id), statusChip(state));
      let res = `${vm.cpus} vCPU · ${vm.mem_gb} ${t.gb}`;
      if (state === "running" && vm.uptime_seconds > 0) res += ` · ${t.up} ${formatDuration(vm.uptime_seconds)}`;
      card.append(head, el("p", "lab-vm__role", vm.id === "cp" ? t.roles.cp : t.roles.worker), el("p", "lab-vm__res", res));
      return card;
    }));
  }

  let playerStarted = false;
  const watchBtn = document.getElementById("lab-live-watch");

  function renderLive(stats) {
    const live = stats && stats.live;
    const stream = live && /^[A-Za-z0-9_-]+$/.test(live.stream || "") ? live.stream : "";
    const on = Boolean(stream && live.on);
    const state = document.getElementById("lab-live-state");
    state.classList.toggle("is-live", on);
    state.replaceChildren(el("span", `dot ${on ? "dot--down" : "dot--pending"}`), el("span", "", stream ? (on ? t.live.on : t.live.off) : t.live.none));
    watchBtn.hidden = !on || playerStarted;
    watchBtn.dataset.stream = stream;
    const link = document.getElementById("lab-live-link");
    link.hidden = !stream;
    if (stream) link.href = `https://asciinema.org/s/${stream}`;
  }

  // The player connects only after a click, so visitors who just scroll by do not hold a websocket open.
  watchBtn.addEventListener("click", () => {
    const stream = watchBtn.dataset.stream;
    if (!stream || !window.AsciinemaPlayer) return;
    const screen = document.getElementById("lab-live-screen");
    screen.replaceChildren();
    window.AsciinemaPlayer.create({ driver: "websocket", url: `wss://asciinema.org/ws/s/${stream}` }, screen, { fit: "width" });
    screen.classList.add("is-live");
    playerStarted = true;
    watchBtn.hidden = true;
  });

  function loadStats() {
    getJSON("/data/stats.json", { cache: "no-cache" })
      .then((stats) => { renderVms(stats); renderLive(stats); })
      .catch(() => { renderVms(null); renderLive(null); });
  }

  loadCerts();
  loadCountdown();
  loadActivity();
  loadStats();
  setInterval(loadStats, 60000);
})();
