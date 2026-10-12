import { test } from "node:test";
import assert from "node:assert/strict";
import { resume } from "./format.ts";

test("resume quotes folder and id for the shell", () => {
  assert.equal(resume({ id: "abc-1", cwd: "/Users/k/My Docs" }), "cd '/Users/k/My Docs' && claude --resume 'abc-1'");
  assert.equal(resume({ id: "x", cwd: "/tmp/a'; rm -r ~; '" }), "cd '/tmp/a'\\''; rm -r ~; '\\''' && claude --resume 'x'");
  assert.equal(resume({ id: "x", cwd: "" }), "claude --resume 'x'");
});
