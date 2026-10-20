// Runs before first paint (blocking, tiny): marks the page as scripted so reveal styles apply
// without a flash. If motion.js never runs, everything is shown after 2.5 s.
document.documentElement.classList.add("js");
setTimeout(function () {
  if (!window.MotionCore) document.documentElement.classList.remove("js");
}, 2500);
