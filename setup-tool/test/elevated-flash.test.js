"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { quote } = require("../src/elevated-flash");

test("shell quoting preserves spaces", () => {
  const result = quote("/tmp/Kaderblick Setup/helper.js");
  assert.match(result, /Kaderblick Setup/);
  assert.ok(result.startsWith(process.platform === "win32" ? '"' : "'"));
});
