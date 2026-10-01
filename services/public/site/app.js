(function () {
  "use strict";

  const LINKEDIN_URL = "https://www.linkedin.com/in/devops-kalislav-smirnov/";

  const UI = {
    en: {
      updated: "updated",
      stars: "stars",
      noDesc: "No description yet.",
      reposError: "GitHub is not responding right now.",
      reposEmpty: "No public repositories yet.",
      internet: "Internet",
      tunnel: "Tunnel",
      tunnelLink: "tunnel, outbound connection only",
      host: "Proxmox VE host",
      zones: { lan: "Home LAN", dmz: "Isolated DMZ" },
      bothNets: "LAN + DMZ",
      mb: "MB",
      gb: "GB",
      restart: "Restart session",
      ci: { label: "infra checks", success: "passing", failure: "failing", other: "unknown" },
      archBelow: "architecture below ↓",
      commitsError: "Commits are not available right now.",
      stats: {
        uptime: "host uptime", guests: "guests running, LXC + VM", containers: "Docker containers",
        load: (n) => `load average, ${n} threads`, d: "d", h: "h",
      },
    },
    ru: {
      updated: "обновлён",
      stars: "звёзд",
      noDesc: "Описания пока нет.",
      reposError: "GitHub сейчас не отвечает.",
      reposEmpty: "Публичных репозиториев пока нет.",
      internet: "Интернет",
      tunnel: "Туннель",
      tunnelLink: "туннель, только исходящее соединение",
      host: "Хост Proxmox VE",
      zones: { lan: "Домашняя сеть", dmz: "Изолированная DMZ" },
      bothNets: "LAN + DMZ",
      mb: "МБ",
      gb: "ГБ",
      restart: "Перезапустить сессию",
      ci: { label: "проверки инфры", success: "проходят", failure: "падают", other: "нет данных" },
      archBelow: "архитектура ниже ↓",
      commitsError: "Коммиты сейчас недоступны.",
      stats: {
        uptime: "аптайм хоста", guests: "гостей запущено, LXC + ВМ", containers: "Docker-контейнеров",
        load: (n) => `load average, ${n} потоков`, d: "дн", h: "ч",
      },
      roles: {
        adguard: "DNS и блокировка рекламы для LAN и VPN",
        tailscale: "VPN: маршрутизатор подсети и exit node",
        npm: "Обратный прокси с wildcard TLS",
        apps: "Домашние сервисы в Docker",
        public: "Публичный узел: CV, страница статуса, Cloudflare Tunnel",
        sandbox: "Публичный веб-терминал, изолированная сеть, сброс каждые 30 минут",
        agent: "AI-агент для эксплуатации (Telegram), только чтение",
        farm: "Ферма стартапов: workflow n8n, Postgres, агенты Claude",
        "k8s-cp": "Лаба Kubernetes: control plane",
        "k8s-w1": "Лаба Kubernetes: worker",
        "k8s-w2": "Лаба Kubernetes: worker",
      },
      networks: {
        lan: "Домашняя сеть за двойным NAT, без входящих портов",
        dmz: "Изолированный мост без выхода наружу; до песочницы достаёт только публичный контейнер",
      },
    },
  };

  const LANG_COLORS = {
    HCL: "#844FBA", Python: "#3572A5", Shell: "#89e051", TypeScript: "#3178c6",
    JavaScript: "#f1e05a", Go: "#00ADD8", Dockerfile: "#384d54", HTML: "#e34c26", CSS: "#563d7c",
  };

  const STATUS_TEXT = {
    en: { ok: "All systems operational", partial: "Partial outage", down: "Major outage", error: "Status unavailable", checked: "checked", ago: "ago", s: "s", m: "min" },
    ru: { ok: "Все системы работают", partial: "Частичный сбой", down: "Серьёзный сбой", error: "Статус недоступен", checked: "проверено", ago: "назад", s: "с", m: "мин" },
  };

  // Each language is its own static page (/ and /ru/, built by scripts/build-ru.py).
  // JS only renders the live blocks in the page language.
  const lang = document.documentElement.lang === "ru" ? "ru" : "en";
  let lastStatus = null;
  let repos;      // undefined: loading, null: failed, array: loaded
  let inventory;  // undefined: loading, null: failed, object: loaded
  let ciRun;      // undefined: loading, null: failed, object: latest completed run
  let commits;    // undefined: loading, null: failed, array: loaded
  let stats;      // undefined: loading, null: failed, object: loaded
  let sandboxStarted = false;

  function storageGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function storageSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* storage unavailable */ }
  }

  // First visit from a Russian-language browser goes to /ru/; an explicit choice is remembered.
  // Crawlers are never redirected, so each URL is indexed in its own language.
  const saved = storageGet("lang");
  const isBot = /bot|crawl|spider|slurp|preview/i.test(navigator.userAgent);
  const preferred = saved || ((navigator.language || "").toLowerCase().startsWith("ru") ? "ru" : "en");
  if (!isBot && preferred !== lang) {
    window.location.replace((preferred === "ru" ? "/ru/" : "/") + window.location.search + window.location.hash);
    return;
  }

  const toggle = document.getElementById("lang-toggle");
  toggle.addEventListener("click", (ev) => {
    ev.preventDefault();
    storageSet("lang", toggle.dataset.target);
    window.location.assign(toggle.getAttribute("href") + window.location.hash);
  });

  if (LINKEDIN_URL) {
    const li = document.getElementById("linkedin-link");
    li.href = LINKEDIN_URL;
    li.hidden = false;
  }

  const overallEl = document.getElementById("status-overall");
  const updatedEl = document.getElementById("status-updated");
  const listEl = document.getElementById("status-list");

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderStatus(endpoints) {
    const t = STATUS_TEXT[lang];
    listEl.replaceChildren();

    if (!endpoints) {
      overallEl.replaceChildren(el("span", "dot dot--down"), el("span", "", t.error));
      updatedEl.textContent = "";
      return;
    }

    const groups = new Map();
    let up = 0;
    let newest = 0;
    endpoints.forEach((ep) => {
      const last = ep.results && ep.results[ep.results.length - 1];
      if (!last) return;
      if (last.success) up += 1;
      const ts = Date.parse(last.timestamp);
      if (ts > newest) newest = ts;
      const g = ep.group || "Other";
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push({ name: ep.name, ok: last.success, ms: Math.round((last.duration || 0) / 1e6) });
    });

    const total = Array.from(groups.values()).reduce((n, g) => n + g.length, 0);
    let state = "ok";
    if (up < total) state = up === 0 || total - up > 2 ? "down" : "partial";
    const dotClass = { ok: "dot dot--ok", partial: "dot dot--warn", down: "dot dot--down" }[state];
    overallEl.replaceChildren(el("span", dotClass), el("span", "", t[state]));

    if (newest) {
      const sec = Math.max(0, Math.round((Date.now() - newest) / 1000));
      const age = sec < 60 ? `${sec} ${t.s}` : `${Math.round(sec / 60)} ${t.m}`;
      updatedEl.textContent = `${t.checked} ${age} ${t.ago}`;
    }

    const ORDER = ["Network", "Compute", "Edge", "Apps"];
    const rank = (g) => (ORDER.indexOf(g) === -1 ? ORDER.length : ORDER.indexOf(g));
    Array.from(groups.entries()).sort((a, b) => rank(a[0]) - rank(b[0])).forEach(([name, items]) => {
      listEl.append(el("li", "status__group", name));
      items.forEach((item) => {
        const li = el("li", "status__item");
        li.append(el("span", item.ok ? "dot dot--ok" : "dot dot--down"), el("span", "status__name", item.name), el("span", "status__ms", item.ok ? `${item.ms} ms` : "down"));
        listEl.append(li);
      });
    });
  }

  async function loadStatus() {
    try {
      const res = await fetch("/api/status", { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      lastStatus = await res.json();
    } catch (e) {
      lastStatus = null;
    }
    renderStatus(lastStatus);
  }

  loadStatus();
  setInterval(loadStatus, 60000);

  // ---- Projects (GitHub, proxied and cached by nginx) ----

  function relativeTime(iso) {
    const diff = (Date.parse(iso) - Date.now()) / 1000;
    const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
    const steps = [["year", 31536000], ["month", 2592000], ["week", 604800], ["day", 86400], ["hour", 3600], ["minute", 60]];
    for (const [unit, sec] of steps) {
      if (Math.abs(diff) >= sec) return rtf.format(Math.round(diff / sec), unit);
    }
    return rtf.format(Math.round(diff), "second");
  }

  function renderProjects() {
    const box = document.getElementById("projects-list");
    if (!box || repos === undefined) return;
    const t = UI[lang];
    box.replaceChildren();
    if (repos === null) { box.append(el("p", "projects__empty", t.reposError)); return; }
    const list = repos.filter((r) => !r.fork && !r.archived);
    if (!list.length) { box.append(el("p", "projects__empty", t.reposEmpty)); return; }
    list.forEach((r) => {
      // The name link stretches over the whole card, so the card can still hold its own links.
      const card = el("div", "project");
      const name = el("a", "project__name", r.name);
      name.href = r.html_url;
      name.target = "_blank";
      name.rel = "noopener";
      card.append(name, el("p", "project__desc", r.description || t.noDesc));
      if (r.name === "homelab") card.append(homelabExtras(t));
      if (r.topics && r.topics.length) {
        const tags = el("p", "tags");
        r.topics.slice(0, 5).forEach((topic) => tags.append(el("span", "", topic)));
        card.append(tags);
      }
      const meta = el("p", "project__meta");
      if (r.language) {
        const dot = el("span", "project__lang-dot");
        dot.style.background = LANG_COLORS[r.language] || "var(--faint)";
        meta.append(dot, el("span", "", r.language));
      }
      if (r.stargazers_count) meta.append(el("span", "", `★ ${r.stargazers_count}`));
      meta.append(el("span", "", `${t.updated} ${relativeTime(r.pushed_at)}`));
      card.append(meta);
      box.append(card);
    });
  }

  function homelabExtras(t) {
    const row = el("p", "project__extras");
    if (ciRun !== undefined) {
      const state = ciRun && (ciRun.conclusion === "success" || ciRun.conclusion === "failure") ? ciRun.conclusion : "other";
      const badge = el("a", `ci-badge ci-badge--${state}`);
      badge.href = ciRun ? ciRun.html_url : "https://github.com/kalikys/homelab/actions";
      badge.target = "_blank";
      badge.rel = "noopener";
      badge.append(el("span", "ci-badge__label", t.ci.label), el("span", "ci-badge__value", t.ci[state]));
      if (ciRun && ciRun.head_sha) badge.title = ciRun.head_sha.slice(0, 7);
      row.append(badge);
    }
    const arch = el("a", "project__arch", t.archBelow);
    arch.href = "#homelab";
    row.append(arch);
    return row;
  }

  function getJSON(url) {
    return fetch(url).then((res) => (res.ok ? res.json() : Promise.reject(res.status)));
  }

  getJSON("/api/github/repos")
    .then((data) => { repos = Array.isArray(data) ? data : null; })
    .catch(() => { repos = null; })
    .then(renderProjects);

  getJSON("/api/github/actions")
    .then((data) => { ciRun = (data.workflow_runs && data.workflow_runs[0]) || null; })
    .catch(() => { ciRun = null; })
    .then(renderProjects);

  // ---- Homelab: recent commits and live stats ----

  function renderCommits() {
    const list = document.getElementById("commits-list");
    if (!list || commits === undefined) return;
    list.replaceChildren();
    if (!commits || !commits.length) { list.append(el("li", "commits__empty", UI[lang].commitsError)); return; }
    commits.forEach((c) => {
      const li = el("li", "commit");
      const sha = el("a", "commit__sha", c.sha.slice(0, 7));
      sha.href = c.html_url;
      sha.target = "_blank";
      sha.rel = "noopener";
      li.append(sha, el("span", "commit__msg", c.commit.message.split("\n")[0]), el("span", "commit__time", relativeTime(c.commit.author.date)));
      list.append(li);
    });
  }

  getJSON("/api/github/commits")
    .then((data) => { commits = Array.isArray(data) ? data : null; })
    .catch(() => { commits = null; })
    .then(renderCommits);

  function formatUptime(sec, t) {
    const days = Math.floor(sec / 86400);
    return days >= 1 ? `${days} ${t.d}` : `${Math.max(1, Math.floor(sec / 3600))} ${t.h}`;
  }

  function renderStats() {
    const box = document.getElementById("stats");
    if (!box || stats === undefined) return;
    box.hidden = !stats;
    if (!stats) return;
    const t = UI[lang].stats;
    const tiles = [
      [formatUptime(stats.uptime_seconds, t), t.uptime],
      [`${stats.guests_running}/${stats.guests_total}`, t.guests],
      [String(stats.containers_running), t.containers],
      [stats.load[0].toFixed(2), t.load(stats.cpus)],
    ];
    box.replaceChildren(...tiles.map(([value, label]) => {
      const tile = el("div", "metric metric--live");
      tile.append(el("p", "metric__value", value), el("p", "metric__label", label));
      return tile;
    }));
  }

  function loadStats() {
    fetch("/data/stats.json", { cache: "no-cache" })
      .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
      .then((data) => { stats = data; })
      .catch(() => { stats = null; })
      .then(renderStats);
  }

  loadStats();
  setInterval(loadStats, 300000);

  // ---- Learning: live progress from the k8s-certs checklists (same parser as /lab/) ----

  function loadLearning() {
    const box = document.getElementById("learn-progress");
    if (!box || !window.LabCore) return;
    Promise.all(["cka", "ckad", "cks"].map((id) => fetch(`/api/github/certs/${id}.md`)
      .then((res) => (res.ok ? res.text() : Promise.reject(res.status)))
      .then((md) => [id, window.LabCore.parseChecklist(md).percent])))
      .then((rows) => {
        box.replaceChildren(...rows.map(([id, pct]) => el("span", "learn-progress__item", `${id.toUpperCase()} ${pct}%`)));
        box.hidden = false;
      })
      .catch(() => { box.hidden = true; });
  }

  loadLearning();

  // ---- Architecture diagram (data exported from Terraform) ----

  function guestCard(g, t) {
    const card = el("div", "arch-guest");
    card.dataset.guest = g.name;
    const head = el("div", "arch-guest__head");
    head.append(el("span", "arch-guest__name", g.name), el("span", "arch-guest__kind", `${g.kind.toUpperCase()} ${g.id}`));
    const role = (t.roles && t.roles[g.name]) || g.role;
    const mem = g.memory_mb >= 1024 ? `${g.memory_mb / 1024} ${t.gb}` : `${g.memory_mb} ${t.mb}`;
    card.append(head, el("p", "arch-guest__role", role), el("p", "arch-guest__res", `${g.cores} vCPU · ${mem} · ${g.disk_gb} ${t.gb}`));
    if (g.network.length > 1) card.append(el("span", "arch-guest__badge", t.bothNets));
    return card;
  }

  function highlightRoute(route, on) {
    const body = document.getElementById("arch-body");
    if (!body || !inventory) return;
    const targets = new Set([route.guest]);
    const target = inventory.guests.find((g) => g.name === route.guest);
    if (target && !target.network.includes("lan")) {
      inventory.guests.filter((g) => g.network.includes("lan") && g.network.includes("dmz")).forEach((g) => targets.add(g.name));
    }
    body.classList.toggle("is-tracing", on);
    body.querySelectorAll(".arch-guest").forEach((c) => c.classList.toggle("is-lit", on && targets.has(c.dataset.guest)));
  }

  function renderArch() {
    const body = document.getElementById("arch-body");
    if (!body || !inventory) return;
    const t = UI[lang];
    body.replaceChildren();

    const edge = el("div", "arch__edge");
    edge.append(el("div", "arch-node", t.internet), el("span", "arch__arrow", "→"));
    const cf = el("div", "arch-node arch-node--cf");
    cf.append(el("span", "arch-node__title", `Cloudflare · ${t.tunnel}`));
    const routes = el("div", "arch-routes");
    inventory.public_routes.forEach((route) => {
      const chip = el("button", "arch-route", route.hostname);
      chip.type = "button";
      ["mouseenter", "focus"].forEach((ev) => chip.addEventListener(ev, () => highlightRoute(route, true)));
      ["mouseleave", "blur"].forEach((ev) => chip.addEventListener(ev, () => highlightRoute(route, false)));
      routes.append(chip);
    });
    cf.append(routes);
    edge.append(cf);

    const link = el("div", "arch__link", t.tunnelLink);

    const host = el("div", "arch__host");
    host.append(el("p", "arch__host-title", `${inventory.host.name} · ${t.host} · ${inventory.host.storage}`));
    const zones = el("div", "arch__zones");
    ["lan", "dmz"].forEach((zone) => {
      const box = el("div", `arch-zone arch-zone--${zone}`);
      const desc = (t.networks && t.networks[zone]) || inventory.networks[zone];
      box.append(el("p", "arch-zone__title", t.zones[zone]), el("p", "arch-zone__desc", desc));
      const grid = el("div", "arch-zone__grid");
      inventory.guests
        .filter((g) => (zone === "lan" ? g.network.includes("lan") : !g.network.includes("lan")))
        .sort((a, b) => a.id - b.id)
        .forEach((g) => grid.append(guestCard(g, t)));
      box.append(grid);
      zones.append(box);
    });
    host.append(zones);

    body.append(edge, link, host);
  }

  getJSON("/data/homelab.json")
    .then((data) => { inventory = data; renderArch(); })
    .catch(() => { const a = document.getElementById("arch"); if (a) a.hidden = true; });

  // ---- Sandbox: the terminal connects only after an explicit click ----

  function updateSandboxButton() {
    const btn = document.getElementById("sandbox-start");
    if (btn && sandboxStarted) btn.textContent = UI[lang].restart;
  }

  const sandboxBtn = document.getElementById("sandbox-start");
  const sandboxScreen = document.getElementById("sandbox-screen");

  if (sandboxBtn && sandboxScreen) {
    sandboxBtn.addEventListener("click", () => {
      const frame = document.createElement("iframe");
      frame.src = "https://shell.kalik8s.com/";
      frame.title = "Sandbox terminal";
      frame.className = "sandbox__frame";
      frame.setAttribute("sandbox", "allow-scripts allow-same-origin allow-forms");
      frame.setAttribute("referrerpolicy", "no-referrer");
      sandboxScreen.replaceChildren(frame);
      sandboxScreen.classList.add("is-live");
      sandboxStarted = true;
      updateSandboxButton();
      frame.focus();
    });
  }
})();
