// Pure scroll math for motion.js. Loaded in the browser as window.MotionCore and in Node tests through require().
(function (root) {
  "use strict";

  const clamp = (v) => Math.min(1, Math.max(0, v));

  // Share of the page scrolled so far: 0 at the top, 1 at the bottom.
  function progress(scrollY, docHeight, viewHeight) {
    const range = docHeight - viewHeight;
    return range > 0 ? clamp(scrollY / range) : 0;
  }

  // Index of the chapter being read: the last one whose top has passed the reading line y.
  function activeChapter(tops, y) {
    let found = -1;
    for (let i = 0; i < tops.length; i++) if (tops[i] <= y) found = i;
    return found;
  }

  // How open an interlude strip is: 0 off screen, 1 while its centre is in the middle 40 % of the view.
  function openness(rectTop, rectHeight, viewHeight) {
    const centre = rectTop + rectHeight / 2;
    const bandTop = viewHeight * 0.3, bandBottom = viewHeight * 0.7;
    if (centre >= bandTop && centre <= bandBottom) return 1;
    if (centre > bandBottom) return clamp((viewHeight + rectHeight / 2 - centre) / (viewHeight + rectHeight / 2 - bandBottom));
    return clamp((centre + rectHeight / 2) / (bandTop + rectHeight / 2));
  }

  const api = { progress, activeChapter, openness };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MotionCore = api;
})(typeof window !== "undefined" ? window : globalThis);
