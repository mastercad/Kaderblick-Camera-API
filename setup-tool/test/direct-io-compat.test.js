"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

require("../src/direct-io-compat");
const directIo = require("@ronomon/direct-io");

test("uses ordinary buffers when direct I/O is disabled", () => {
  const buffer = directIo.getAlignedBuffer(4096, 4096);

  assert.ok(Buffer.isBuffer(buffer));
  assert.equal(buffer.length, 4096);
  assert.equal(buffer.buffer instanceof ArrayBuffer, true);
});
