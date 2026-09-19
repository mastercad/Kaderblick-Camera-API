"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { IMAGE_PATTERN, sha256 } = require("../src/download");

test("matches only release image assets", () => {
  assert.equal(IMAGE_PATTERN.test("kaderblick-camera-os-0.1.0.img.xz"), true);
  assert.equal(IMAGE_PATTERN.test("Kaderblick-Kamera-Setup.exe"), false);
  assert.equal(IMAGE_PATTERN.test("kaderblick-camera-os.img"), false);
});

test("calculates sha256", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "kaderblick-test-"));
  const filename = path.join(directory, "sample");
  await fs.writeFile(filename, "kaderblick");
  assert.equal(await sha256(filename), "904041ec3c406c09cb75dd5503ca0928052d51e2b0852ff4b44a20394e50fdf6");
});
