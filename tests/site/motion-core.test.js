const test = require("node:test");
const assert = require("node:assert/strict");
const M = require("../../services/public/site/motion-core.js");

test("progress is the scrolled share of the page, clamped to 0..1", () => {
  assert.equal(M.progress(0, 2000, 1000), 0);
  assert.equal(M.progress(500, 2000, 1000), 0.5);
  assert.equal(M.progress(1000, 2000, 1000), 1);
  assert.equal(M.progress(1500, 2000, 1000), 1);
  assert.equal(M.progress(-80, 2000, 1000), 0);
  assert.equal(M.progress(50, 800, 1000), 0);
});

test("activeChapter is the last chapter whose top is above the reading line", () => {
  assert.equal(M.activeChapter([0, 900, 1800], 0), 0);
  assert.equal(M.activeChapter([0, 900, 1800], 1799), 1);
  assert.equal(M.activeChapter([0, 900, 1800], 1800), 2);
  assert.equal(M.activeChapter([0, 900, 1800], 5000), 2);
  assert.equal(M.activeChapter([100], 0), -1);
  assert.equal(M.activeChapter([], 0), -1);
});

test("openness grows as an interlude reaches the middle of the view", () => {
  assert.equal(M.openness(1000, 400, 1000), 0);
  assert.equal(M.openness(300, 400, 1000), 1);
  assert.equal(M.openness(-400, 400, 1000), 0);
  let last = -1;
  for (let top = 1000; top >= 300; top -= 50) {
    const v = M.openness(top, 400, 1000);
    assert.ok(v >= last && v >= 0 && v <= 1, `top ${top}: ${v}`);
    last = v;
  }
});
