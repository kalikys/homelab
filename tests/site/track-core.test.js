const test = require("node:test");
const assert = require("node:assert/strict");
const Track = require("../../services/public/site/track-core.js");

test("cleanTag keeps a short lowercase token and drops everything else", () => {
  assert.equal(Track.cleanTag("LinkedIn"), "linkedin");
  assert.equal(Track.cleanTag("video_a-2.1"), "video_a-2.1");
  assert.equal(Track.cleanTag("a b<script>"), "abscript");
  assert.equal(Track.cleanTag("x".repeat(60)).length, 40);
  assert.equal(Track.cleanTag(null), "");
});

test("campaign prefers UTM tags over the referrer", () => {
  const c = Track.campaign("?utm_source=linkedin&utm_campaign=hire-devops&utm_content=video_a", "https://www.google.com/", "kalik8s.com");
  assert.deepEqual(c, { src: "linkedin", campaign: "hire-devops", content: "video_a" });
});

test("campaign falls back to the referrer host, without www", () => {
  assert.deepEqual(Track.campaign("", "https://l.instagram.com/?u=x", "kalik8s.com"), { src: "l.instagram.com", campaign: "", content: "" });
  assert.deepEqual(Track.campaign("", "https://www.facebook.com/", "kalik8s.com"), { src: "facebook.com", campaign: "", content: "" });
  assert.deepEqual(Track.campaign("", "android-app://com.linkedin.android/", "kalik8s.com"), { src: "com.linkedin.android", campaign: "", content: "" });
});

test("campaign is empty for direct visits and for navigation inside the site", () => {
  assert.equal(Track.campaign("", "", "kalik8s.com"), null);
  assert.equal(Track.campaign("?x=1", "https://kalik8s.com/ru/", "kalik8s.com"), null);
  assert.equal(Track.campaign("", "not a url", "kalik8s.com"), null);
});

test("eventFor names the contact a link leads to", () => {
  assert.equal(Track.eventFor("https://cal.com/kalikys/intro?utm_source=cv_site"), "call");
  assert.equal(Track.eventFor("mailto:kalikys@outlook.com"), "email");
  assert.equal(Track.eventFor("https://t.me/kalikys"), "telegram");
  assert.equal(Track.eventFor("https://www.linkedin.com/in/devops-kalislav-smirnov/"), "linkedin");
  assert.equal(Track.eventFor("https://github.com/kalikys"), "github");
  assert.equal(Track.eventFor("/Kalislav-Smirnov-CV.pdf"), "cv_pdf");
  assert.equal(Track.eventFor("/lab/"), null);
  assert.equal(Track.eventFor("#experience"), null);
  assert.equal(Track.eventFor(""), null);
});

test("calUrl carries the visit source into the booking link and keeps the button position", () => {
  const href = "https://cal.com/kalikys/intro?utm_source=cv_site&utm_medium=hero";
  assert.equal(
    Track.calUrl(href, { src: "linkedin", campaign: "hire-devops", content: "video_a" }),
    "https://cal.com/kalikys/intro?utm_source=linkedin&utm_medium=hero&utm_campaign=hire-devops&utm_content=video_a"
  );
  assert.equal(
    Track.calUrl(href, { src: "facebook.com", campaign: "", content: "" }),
    "https://cal.com/kalikys/intro?utm_source=facebook.com&utm_medium=hero"
  );
  assert.equal(Track.calUrl(href, null), href);
});

test("eventPath builds the same-origin beacon URL", () => {
  assert.equal(
    Track.eventPath("cv_pdf", { src: "linkedin", campaign: "hire-devops", content: "video_a" }, "en"),
    "/e/cv_pdf?src=linkedin&c=video_a&lang=en"
  );
  assert.equal(Track.eventPath("call", null, "ru"), "/e/call?src=direct&lang=ru");
  assert.equal(Track.eventPath("email", { src: "facebook.com", campaign: "", content: "" }, "en"), "/e/email?src=facebook.com&lang=en");
});
