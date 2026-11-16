const test = require("node:test");
const assert = require("node:assert/strict");
const Oss = require("../../services/public/site/oss-core.js");

const pr = (n, repo, title, state, merged, created) => ({
  html_url: `https://github.com/${repo}/pull/${n}`,
  repository_url: `https://api.github.com/repos/${repo}`,
  title,
  state,
  created_at: created,
  pull_request: { merged_at: merged },
});

test("split puts merged and open PRs in separate lists and drops closed-unmerged ones", () => {
  const out = Oss.split([
    pr(1, "a/x", "open one", "open", null, "2026-11-10T00:00:00Z"),
    pr(2, "b/y", "merged one", "closed", "2026-11-09T00:00:00Z", "2026-11-01T00:00:00Z"),
    pr(3, "c/z", "rejected", "closed", null, "2026-11-08T00:00:00Z"),
  ]);
  assert.deepEqual(out.review.map((r) => r.title), ["open one"]);
  assert.deepEqual(out.merged.map((r) => r.title), ["merged one"]);
  assert.equal(out.merged[0].repo, "b/y");
  assert.equal(out.merged[0].date, "2026-11-09T00:00:00Z");
});

test("backports fold into the original PR with a count and the newest date", () => {
  const out = Oss.split([
    pr(2980, "canonical/k8s-snap", "ci: fix YAML [Backport release-1.37]", "closed", "2026-11-16T12:09:37Z", "2026-11-16T10:00:00Z"),
    pr(2979, "canonical/k8s-snap", "ci: fix YAML [Backport release-1.36]", "closed", "2026-11-16T12:08:00Z", "2026-11-16T10:00:00Z"),
    pr(2939, "canonical/k8s-snap", "ci: fix YAML", "closed", "2026-10-22T11:13:17Z", "2026-10-20T00:00:00Z"),
  ]);
  assert.equal(out.merged.length, 1);
  const row = out.merged[0];
  assert.equal(row.title, "ci: fix YAML");
  assert.equal(row.url, "https://github.com/canonical/k8s-snap/pull/2939");
  assert.equal(row.backports, 2);
  assert.equal(row.date, "2026-11-16T12:09:37Z");
});

test("same title in different repos stays separate; empty input is safe", () => {
  const out = Oss.split([
    pr(1, "a/x", "fix", "open", null, "2026-11-10T00:00:00Z"),
    pr(2, "b/y", "fix", "open", null, "2026-11-09T00:00:00Z"),
  ]);
  assert.equal(out.review.length, 2);
  assert.deepEqual(Oss.split(null), { merged: [], review: [] });
});
