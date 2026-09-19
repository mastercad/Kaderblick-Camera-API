"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { prepareCmdline, prepareConfig } = require("../src/flash");

test("adds the one-time installer to the official boot command line", () => {
  const result = prepareCmdline("console=serial0,115200 root=PARTUUID=1234 init=/usr/lib/raspberrypi-sys-mods/firstboot\n");
  assert.match(result, /init=\/usr\/lib\/raspberrypi-sys-mods\/firstboot/);
  assert.match(result, /systemd\.run=\/boot\/firmware\/kaderblick-install\.sh/);
  assert.match(result, /systemd\.run_success_action=reboot/);
});

test("applies radio and USB settings exactly once", () => {
  const once = prepareConfig("arm_64bit=1\n");
  const twice = prepareConfig(once);
  assert.equal(twice, once);
  assert.match(once, /dtoverlay=disable-wifi/);
  assert.match(once, /dtoverlay=disable-bt/);
  assert.match(once, /usb_max_current_enable=1/);
});
