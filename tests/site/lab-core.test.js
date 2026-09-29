const test = require("node:test");
const assert = require("node:assert/strict");
const Core = require("../../services/public/site/lab-core.js");

const CKA = `# CKA

## Storage (10%)
- [x] Storage classes
- [ ] Volume types

## Troubleshooting (30%)
- [X] Nodes
- [x] Components
- [ ] Networking
- [ ] Logs

## Notes
- [x] not weighted
`;

test("parseChecklist counts items per domain and weights the percentage", () => {
  const r = Core.parseChecklist(CKA);
  assert.deepEqual(r.domains, [
    { name: "Storage", weight: 10, done: 1, total: 2 },
    { name: "Troubleshooting", weight: 30, done: 2, total: 4 },
    { name: "Notes", weight: null, done: 1, total: 1 },
  ]);
  // (10 * 1/2 + 30 * 2/4) / 40 = 50%
  assert.equal(r.percent, 50);
});

test("a weighted domain without items counts as 0% and stays in the denominator", () => {
  const r = Core.parseChecklist("## A (50%)\n- [x] one\n\n## B (50%)\n");
  assert.equal(r.percent, 50);
});

test("no weighted domains gives 0%", () => {
  assert.equal(Core.parseChecklist("## Only notes\n- [x] a\n").percent, 0);
  assert.equal(Core.parseChecklist("").percent, 0);
});

test("items before the first domain and ### headings are ignored", () => {
  const r = Core.parseChecklist("- [x] stray\n### Sub (20%)\n## Real (100%)\n- [ ] a\n");
  assert.deepEqual(r.domains, [{ name: "Real", weight: 100, done: 0, total: 1 }]);
});

test("dayKey uses Tbilisi time (UTC+4)", () => {
  assert.equal(Core.dayKey(new Date("2026-09-29T19:59:00Z")), "2026-09-29");
  assert.equal(Core.dayKey(new Date("2026-09-29T20:30:00Z")), "2026-09-30");
});

const commit = (iso) => ({ commit: { author: { date: iso } } });

test("activeDays counts commits per Tbilisi day and skips broken entries", () => {
  const days = Core.activeDays([
    commit("2026-09-29T10:00:00Z"),
    commit("2026-09-29T11:00:00Z"),
    commit("2026-09-29T23:30:00Z"),
    { commit: {} },
    null,
  ]);
  assert.equal(days.get("2026-09-29"), 2);
  assert.equal(days.get("2026-09-30"), 1);
  assert.equal(days.size, 2);
});

test("streak counts back from today, or from yesterday if today is empty", () => {
  const days = new Map([["2026-09-27", 1], ["2026-09-28", 3], ["2026-09-29", 1]]);
  assert.equal(Core.streak(days, new Date("2026-09-29T08:00:00Z")), 3);
  assert.equal(Core.streak(days, new Date("2026-09-30T08:00:00Z")), 3);
  assert.equal(Core.streak(days, new Date("2026-10-01T08:00:00Z")), 0);
  assert.equal(Core.streak(new Map(), new Date()), 0);
});

test("heatmap has weeks*7 cells ending today", () => {
  const days = new Map([["2026-09-29", 2]]);
  const cells = Core.heatmap(days, new Date("2026-09-29T08:00:00Z"), 12);
  assert.equal(cells.length, 84);
  assert.deepEqual(cells[83], { day: "2026-09-29", count: 2 });
  assert.deepEqual(cells[82], { day: "2026-09-28", count: 0 });
  assert.equal(cells[0].day, "2026-07-08");
});

test("nextExam picks the nearest date today or later and ignores junk", () => {
  const now = new Date("2026-09-29T08:00:00Z");
  assert.deepEqual(Core.nextExam({ cka: "2026-11-15", ckad: "2026-10-01", cks: null }, now), { id: "ckad", date: "2026-10-01", days: 2 });
  assert.deepEqual(Core.nextExam({ cka: "2026-09-29" }, now), { id: "cka", date: "2026-09-29", days: 0 });
  assert.equal(Core.nextExam({ cka: "2026-09-01", ckad: "soon", cks: 5 }, now), null);
  assert.equal(Core.nextExam(null, now), null);
});

test("ruPlural", () => {
  const f = (n) => Core.ruPlural(n, "день", "дня", "дней");
  assert.equal(f(1), "день");
  assert.equal(f(3), "дня");
  assert.equal(f(5), "дней");
  assert.equal(f(11), "дней");
  assert.equal(f(21), "день");
  assert.equal(f(22), "дня");
  assert.equal(f(112), "дней");
});
