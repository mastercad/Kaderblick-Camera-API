"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { linuxHelperInvocation, quote } = require("../src/elevated-flash");

test("shell quoting preserves spaces", () => {
  const result = quote("/tmp/Kaderblick Setup/helper.js");
  assert.match(result, /Kaderblick Setup/);
  assert.ok(result.startsWith(process.platform === "win32" ? '"' : "'"));
});

test("restarts the AppImage itself for Linux administrator access", () => {
  const invocation = linuxHelperInvocation(
    "/tmp/.mount-private/resources/app.asar/src/helper.js",
    "/tmp/kaderblick/helper-bootstrap.js",
    "/tmp/kaderblick/job.json",
    "/home/user/Kaderblick Kamera Setup.AppImage"
  );
  assert.equal(invocation.executable, "pkexec");
  assert.deepEqual(invocation.args.slice(-3), [
    "/home/user/Kaderblick Kamera Setup.AppImage",
    "/tmp/kaderblick/helper-bootstrap.js",
    "/tmp/kaderblick/job.json"
  ]);
});
