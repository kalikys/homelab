// Pure helpers for the open-source block: splits my pull requests (GitHub search items) into
// merged and still-in-review, folding backports of one change into a single row.
// Loaded in the browser as window.OssCore and in Node tests through require().
(function (root) {
  "use strict";

  const BACKPORT = /\s*\[backport[^\]]*\]\s*$/i;

  function repoOf(item) {
    return String(item.repository_url || "").replace("https://api.github.com/repos/", "");
  }

  function stateOf(item) {
    if (item.pull_request && item.pull_request.merged_at) return "merged";
    return item.state === "open" ? "open" : "closed";
  }

  // Returns { merged: [...], review: [...] }; each row is
  // { title, url, repo, state, date, backports }. Closed-unmerged PRs are left out.
  // A PR and its "[Backport …]" copies in the same repo become one row: the original's link,
  // the newest date, and the number of backports. Rows keep the input order (newest first).
  function split(items) {
    const rows = [];
    const byKey = new Map();
    (items || []).forEach((item) => {
      const state = stateOf(item);
      if (state === "closed") return;
      const repo = repoOf(item);
      const raw = String(item.title || "");
      const isBackport = BACKPORT.test(raw);
      const title = raw.replace(BACKPORT, "");
      const key = `${state}\u0000${repo}\u0000${title}`;
      const date = (item.pull_request && item.pull_request.merged_at) || item.created_at;
      let row = byKey.get(key);
      if (!row) {
        row = { title, url: item.html_url, repo, state, date, backports: 0 };
        byKey.set(key, row);
        rows.push(row);
      } else if (!isBackport) {
        row.url = item.html_url;
      }
      if (isBackport) row.backports += 1;
      if (date && (!row.date || date > row.date)) row.date = date;
    });
    return {
      merged: rows.filter((r) => r.state === "merged"),
      review: rows.filter((r) => r.state === "open"),
    };
  }

  const api = { split };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.OssCore = api;
})(typeof self !== "undefined" ? self : this);
