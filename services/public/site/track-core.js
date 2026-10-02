// Pure helpers for visit attribution: where a visitor came from and which contact they clicked.
// Loaded in the browser as window.TrackCore and in Node tests through require().
(function (root) {
  "use strict";

  function cleanTag(value) {
    return String(value == null ? "" : value).toLowerCase().replace(/[^a-z0-9_.-]/g, "").slice(0, 40);
  }

  // UTM tags win; otherwise the referrer host. Direct visits and moves inside the site give null.
  function campaign(search, referrer, host) {
    const params = new URLSearchParams(search || "");
    const src = cleanTag(params.get("utm_source"));
    if (src) {
      return { src, campaign: cleanTag(params.get("utm_campaign")), content: cleanTag(params.get("utm_content")) };
    }
    let ref;
    try { ref = new URL(referrer).hostname.replace(/^www\./, ""); } catch (e) { return null; }
    ref = cleanTag(ref);
    if (!ref || ref === host) return null;
    return { src: ref, campaign: "", content: "" };
  }

  function eventFor(href) {
    const h = String(href || "");
    if (h.startsWith("mailto:")) return "email";
    if (/^https:\/\/cal\.com\//.test(h)) return "call";
    if (/^https:\/\/t\.me\//.test(h)) return "telegram";
    if (/^https:\/\/(www\.)?linkedin\.com\//.test(h)) return "linkedin";
    if (/^https:\/\/github\.com\//.test(h)) return "github";
    if (/\.pdf$/.test(h)) return "cv_pdf";
    return null;
  }

  // utm_medium on the booking links names the button, so it stays as written in the page.
  function calUrl(href, c) {
    if (!c) return href;
    const url = new URL(href);
    url.searchParams.set("utm_source", c.src);
    if (c.campaign) url.searchParams.set("utm_campaign", c.campaign);
    if (c.content) url.searchParams.set("utm_content", c.content);
    return url.toString();
  }

  function eventPath(event, c, lang) {
    const q = new URLSearchParams({ src: c ? c.src : "direct" });
    if (c && c.content) q.set("c", c.content);
    q.set("lang", lang);
    return `/e/${event}?${q}`;
  }

  const api = { cleanTag, campaign, eventFor, calUrl, eventPath };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TrackCore = api;
})(typeof window !== "undefined" ? window : globalThis);
