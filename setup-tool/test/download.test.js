"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { OFFICIAL_IMAGE_URL, sha256 } = require("../src/download");

test("uses the pinned official Raspberry Pi OS Lite image", () => {
  const url = new URL(OFFICIAL_IMAGE_URL);
  assert.equal(url.hostname, "downloads.raspberrypi.com");
  assert.match(url.pathname, /raspios-bookworm-arm64-lite\.img\.xz$/);
});

test("calculates sha256", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "kaderblick-test-"));
  const filename = path.join(directory, "sample");
  await fs.writeFile(filename, "kaderblick");
  assert.equal(await sha256(filename), "904041ec3c406c09cb75dd5503ca0928052d51e2b0852ff4b44a20394e50fdf6");
});
