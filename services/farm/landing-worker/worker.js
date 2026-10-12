// Farm landing Worker: serves smoke-test landing pages from KV and counts visits, price clicks and sign-ups in D1.
// The counter is injected here, not written by the agent, so the agent cannot fake its own metrics.
const EXP_RE = /^(EXP|GAME)-\d{3}$/;
const FILE_RE = /^[a-z0-9][a-z0-9._-]{0,60}$/;
const BOT_RE = /bot|crawl|spider|slurp|preview|headless|lighthouse|facebookexternalhit|curl|wget|python|go-http/i;
const TYPES = { html: "text/html; charset=utf-8", css: "text/css", js: "application/javascript", svg: "image/svg+xml", png: "image/png", jpg: "image/jpeg", webp: "image/webp", ico: "image/x-icon", txt: "text/plain" };
const CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'";

const BEACON = `(() => {
  const s = document.currentScript, exp = s.dataset.exp;
  if (s.dataset.preview) return;
  let vid; try { vid = localStorage.getItem("fv") || crypto.randomUUID(); localStorage.setItem("fv", vid); } catch (e) { vid = crypto.randomUUID(); }
  const q = new URLSearchParams(location.search);
  const base = { exp, vid, path: location.pathname, ref: document.referrer.slice(0, 200), src: q.get("utm_source") || "", campaign: q.get("utm_campaign") || "" };
  const send = (ev, extra) => navigator.sendBeacon("/e", JSON.stringify({ ...base, ev, ...extra }));
  send("view");
  document.addEventListener("click", e => { const c = e.target.closest("[data-farm-cta]"); if (c) send("cta", { plan: c.dataset.farmCta || "" }); });
  document.querySelectorAll("form[data-farm-signup]").forEach(f => f.addEventListener("submit", async e => {
    e.preventDefault();
    const email = (f.querySelector("input[type=email]") || {}).value || "";
    const r = await fetch("/s", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...base, email, plan: f.dataset.farmSignup || "" }) });
    const t = document.querySelector("[data-farm-thanks]");
    if (r.ok) { f.hidden = true; if (t) t.hidden = false; } else { f.querySelector("button")?.setAttribute("disabled", ""); }
  }));
})();`;

const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });

async function readBody(req) {
  const text = await req.text();
  if (text.length > 4000) return null;
  try { return JSON.parse(text); } catch { return null; }
}

async function track(req, env) {
  const b = await readBody(req);
  if (!b || !EXP_RE.test(b.exp || "") || !["view", "cta"].includes(b.ev)) return json({ ok: false }, 400);
  const ua = req.headers.get("user-agent") || "";
  await env.DB.prepare("INSERT INTO events (ts, exp, vid, ev, plan, path, ref, src, campaign, country, bot) VALUES (?,?,?,?,?,?,?,?,?,?,?)")
    .bind(new Date().toISOString(), b.exp, String(b.vid || "").slice(0, 40), b.ev, String(b.plan || "").slice(0, 40), String(b.path || "").slice(0, 120),
          String(b.ref || "").slice(0, 200), String(b.src || "").slice(0, 60), String(b.campaign || "").slice(0, 60), req.cf?.country || "", BOT_RE.test(ua) ? 1 : 0).run();
  return new Response(null, { status: 204 });
}

async function signup(req, env) {
  const b = await readBody(req);
  const email = String(b?.email || "").trim().toLowerCase();
  if (!b || !EXP_RE.test(b.exp || "") || !/^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,}$/.test(email)) return json({ ok: false }, 400);
  await env.DB.prepare("INSERT OR IGNORE INTO signups (ts, exp, vid, email, plan, src, campaign, country) VALUES (?,?,?,?,?,?,?,?)")
    .bind(new Date().toISOString(), b.exp, String(b.vid || "").slice(0, 40), email, String(b.plan || "").slice(0, 40),
          String(b.src || "").slice(0, 60), String(b.campaign || "").slice(0, 60), req.cf?.country || "").run();
  return json({ ok: true });
}

async function stats(req, env, url) {
  if (!env.STATS_TOKEN || req.headers.get("x-farm-token") !== env.STATS_TOKEN) return json({ ok: false }, 401);
  const exp = url.searchParams.get("exp") || "";
  if (!EXP_RE.test(exp)) return json({ ok: false }, 400);
  const days = await env.DB.prepare(`SELECT substr(ts, 1, 10) AS day,
      COUNT(DISTINCT CASE WHEN ev = 'view' THEN vid END) AS visitors,
      SUM(ev = 'view') AS views,
      COUNT(DISTINCT CASE WHEN ev = 'cta' THEN vid END) AS cta_visitors
    FROM events WHERE exp = ? AND bot = 0 GROUP BY day ORDER BY day`).bind(exp).all();
  const sign = await env.DB.prepare("SELECT substr(ts, 1, 10) AS day, COUNT(*) AS signups FROM signups WHERE exp = ? GROUP BY day").bind(exp).all();
  const total = await env.DB.prepare(`SELECT COUNT(DISTINCT CASE WHEN ev = 'view' THEN vid END) AS visitors,
      COUNT(DISTINCT CASE WHEN ev = 'cta' THEN vid END) AS cta_visitors, SUM(bot) AS bot_events FROM events WHERE exp = ?`).bind(exp).first();
  const signups = await env.DB.prepare("SELECT COUNT(*) AS n FROM signups WHERE exp = ?").bind(exp).first();
  const bySrc = await env.DB.prepare(`SELECT src, COUNT(DISTINCT vid) AS visitors FROM events WHERE exp = ? AND bot = 0 AND ev = 'view' GROUP BY src`).bind(exp).all();
  return json({ ok: true, exp, total: { ...total, signups: signups.n }, days: days.results, signups_by_day: sign.results, by_source: bySrc.results });
}

async function page(req, env, url, exp, rest) {
  const meta = await env.SITES.get(`meta:${exp}`, "json");
  if (!meta) return new Response("Not found", { status: 404 });
  const preview = url.searchParams.get("preview");
  const isPreview = !meta.live;
  if (isPreview && (!preview || preview !== meta.preview_token)) return new Response("Not found", { status: 404 });
  if (rest === "") return Response.redirect(`${url.origin}/l/${exp}/${url.search}`, 301);
  const file = rest === "/" ? "index.html" : rest.slice(1);
  if (!FILE_RE.test(file)) return new Response("Not found", { status: 404 });
  const ext = file.split(".").pop();
  const body = await env.SITES.get(`site:${exp}:${file}`, ext === "html" || ext === "css" || ext === "js" || ext === "svg" || ext === "txt" ? "text" : "arrayBuffer");
  if (body === null) return new Response("Not found", { status: 404 });
  let out = body;
  if (ext === "html") {
    const tag = `<script src="/b.js" data-exp="${exp}"${isPreview ? ' data-preview="1"' : ""} defer></script>`;
    out = body.includes("</body>") ? body.replace("</body>", `${tag}</body>`) : body + tag;
  }
  return new Response(out, { headers: { "content-type": TYPES[ext] || "application/octet-stream", "content-security-policy": CSP,
    "x-robots-tag": isPreview ? "noindex" : "all", "cache-control": "no-store", "referrer-policy": "strict-origin-when-cross-origin" } });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const p = url.pathname;
    if (p === "/b.js") return new Response(BEACON, { headers: { "content-type": "application/javascript", "cache-control": "public, max-age=300" } });
    if (p === "/e" && req.method === "POST") return track(req, env);
    if (p === "/s" && req.method === "POST") return signup(req, env);
    if (p === "/stats") return stats(req, env, url);
    const m = p.match(/^\/l\/((?:EXP|GAME)-\d{3})(\/.*)?$/);
    if (m) return page(req, env, url, m[1], m[2] || "");
    return new Response("Not found", { status: 404 });
  },
};
