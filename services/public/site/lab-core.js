// Pure helpers for the /lab/ page: checklist progress, commit streak, exam countdown.
// Loaded in the browser as window.LabCore and in Node tests through require().
(function (root) {
  "use strict";

  const DAY = 86400000;
  // Georgia has no DST, so stepping back 24 h always lands on the previous local day.
  const dayFormat = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tbilisi", year: "numeric", month: "2-digit", day: "2-digit" });

  function dayKey(date) {
    return dayFormat.format(date);
  }

  // "## Storage (10%)" starts a domain, "- [x] item" / "- [ ] item" are its items.
  // Domains without a weight are listed but left out of the percentage.
  function parseChecklist(md) {
    const domains = [];
    let current = null;
    String(md).split(/\r?\n/).forEach((line) => {
      const head = line.match(/^##\s+(.+?)\s*(?:\((\d+(?:\.\d+)?)%\))?\s*$/);
      if (head) {
        current = { name: head[1], weight: head[2] === undefined ? null : Number(head[2]), done: 0, total: 0 };
        domains.push(current);
        return;
      }
      const item = line.match(/^\s*[-*]\s+\[([ xX])\]\s+\S/);
      if (item && current) {
        current.total += 1;
        if (item[1] !== " ") current.done += 1;
      }
    });
    const weighted = domains.filter((d) => d.weight !== null);
    const weights = weighted.reduce((sum, d) => sum + d.weight, 0);
    const score = weighted.reduce((sum, d) => sum + (d.total ? d.weight * (d.done / d.total) : 0), 0);
    return { domains, percent: weights ? Math.round((score / weights) * 100) : 0 };
  }

  function activeDays(commits) {
    const days = new Map();
    (commits || []).forEach((c) => {
      const ts = Date.parse(c && c.commit && c.commit.author && c.commit.author.date);
      if (Number.isNaN(ts)) return;
      const key = dayKey(new Date(ts));
      days.set(key, (days.get(key) || 0) + 1);
    });
    return days;
  }

  // Consecutive active days ending today, or yesterday when nothing is committed yet today.
  function streak(days, now) {
    let t = now.getTime();
    if (!days.has(dayKey(new Date(t)))) t -= DAY;
    let count = 0;
    while (days.has(dayKey(new Date(t)))) {
      count += 1;
      t -= DAY;
    }
    return count;
  }

  function heatmap(days, now, weeks) {
    const cells = [];
    for (let i = weeks * 7 - 1; i >= 0; i -= 1) {
      const day = dayKey(new Date(now.getTime() - i * DAY));
      cells.push({ day, count: days.get(day) || 0 });
    }
    return cells;
  }

  // Nearest exam today or later. Dates are "YYYY-MM-DD" in Tbilisi time.
  function nextExam(exams, now) {
    const today = dayKey(now);
    let best = null;
    Object.keys(exams || {}).forEach((id) => {
      const date = exams[id];
      if (typeof date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(date) || date < today) return;
      if (!best || date < best.date) best = { id, date };
    });
    if (!best) return null;
    best.days = Math.round((Date.parse(best.date) - Date.parse(today)) / DAY);
    return best;
  }

  function ruPlural(n, one, few, many) {
    const m10 = n % 10;
    const m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }

  const api = { parseChecklist, dayKey, activeDays, streak, heatmap, nextExam, ruPlural };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.LabCore = api;
})(typeof window !== "undefined" ? window : globalThis);
