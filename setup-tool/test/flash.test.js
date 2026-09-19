"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { prepareCmdline, prepareConfig } = require("../src/flash");

test("adds the one-time installer to the official boot command line", () => {
  const result = prepareCmdline("console=serial0,115200 root=PARTUUID=1234 init=/usr/lib/raspberrypi-sys-mods/firstboot\n");
  assert.match(result, /init=\/usr\/lib\/raspberrypi-sys-mods\/firstboot/);
  assert.match(result, /systemd\.run=\/boot\/firmware\/kaderblick-install\.sh/);
  assert.match(result, /systemd\.run_success_action=reboot/);
  assert.match(result, /systemd\.run_failure_action=none/);
});

test("applies radio and USB settings exactly once", () => {
  const once = prepareConfig("arm_64bit=1\n");
  const twice = prepareConfig(once);
  assert.equal(twice, once);
  assert.match(once, /dtoverlay=disable-wifi/);
  assert.match(once, /dtoverlay=disable-bt/);
  assert.match(once, /usb_max_current_enable=1/);
});

test("removes every one-time boot parameter only after successful configuration", () => {
  const installer = fs.readFileSync(path.join(
    __dirname,
    "..", "..", "image-builder", "stage-kaderblick", "00-runtime", "files", "install-runtime.sh"
  ), "utf8");
  const configuredAt = installer.indexOf("/usr/local/sbin/kaderblick-firstboot");
  const cleanupAt = installer.indexOf('blocked = ("systemd.run=",');

  assert.ok(configuredAt >= 0);
  assert.ok(cleanupAt > configuredAt);
  assert.match(installer, /"systemd\.run_failure_action="/);
  assert.match(installer, /rm -rf "\$\{WORK\}" "\$\{PAYLOAD_ARCHIVE\}" "\$\{BOOT\}\/kaderblick-install\.sh"/);
});

test("waits for an Ethernet route and working DNS before package installation", () => {
  const installer = fs.readFileSync(path.join(
    __dirname,
    "..", "..", "image-builder", "stage-kaderblick", "00-runtime", "files", "install-runtime.sh"
  ), "utf8");
  const networkAt = installer.indexOf("systemctl start NetworkManager.service");
  const interfaceAt = installer.indexOf("for interface_path in /sys/class/net/eth* /sys/class/net/en*");
  const deviceAt = installer.indexOf("networkmanager_device=false");
  const routeAt = installer.indexOf('ip -4 route show default dev "${ethernet_interface}"');
  const dnsAt = installer.indexOf("getent ahostsv4 deb.debian.org");
  const clockAt = installer.indexOf("synchronize_clock");
  const extractAt = installer.indexOf('tar -xJf "${PAYLOAD_ARCHIVE}"');
  const aptAt = installer.indexOf("apt-get -o Acquire::Retries=3 update");

  assert.ok(networkAt >= 0);
  assert.ok(interfaceAt > networkAt);
  assert.ok(deviceAt > interfaceAt);
  assert.ok(routeAt > deviceAt);
  assert.ok(dnsAt > routeAt);
  assert.ok(clockAt > dnsAt);
  assert.ok(extractAt > clockAt);
  assert.ok(aptAt > extractAt);
  assert.match(installer, /nmcli --get-values IP4\.DNS device show/);
  assert.match(installer, /NTPSynchronized/);
  assert.match(installer, /HTTPConnection\("deb\.debian\.org", 80/);
  assert.match(installer, /nameserver 1\.1\.1\.1/);
  assert.match(installer, /nameserver 8\.8\.8\.8/);
  assert.match(installer, /nmcli connection add type ethernet/);
});

test("uses the proven Netplan and NetworkManager final configuration", () => {
  const firstboot = fs.readFileSync(path.join(
    __dirname,
    "..", "..", "image-builder", "stage-kaderblick", "00-runtime", "files", "kaderblick-firstboot.py"
  ), "utf8");

  assert.match(firstboot, /renderer: NetworkManager/);
  assert.match(firstboot, /01-static-ip\.yaml/);
  assert.match(firstboot, /dhcp4: false/);
  assert.match(firstboot, /netplan", "generate/);
  assert.match(firstboot, /connection", "delete", "kaderblick-setup/);
});

test("runs time synchronization only before camera services and disables maintenance timers", () => {
  const files = path.join(
    __dirname,
    "..", "..", "image-builder", "stage-kaderblick", "00-runtime", "files"
  );
  const cameraService = fs.readFileSync(path.join(files, "camera_service.service"), "utf8");
  const apiService = fs.readFileSync(path.join(files, "kaderblick_app.service"), "utf8");
  const preflightService = fs.readFileSync(path.join(files, "kaderblick-boot-preflight.service"), "utf8");
  const preflight = fs.readFileSync(path.join(files, "kaderblick-boot-preflight"), "utf8");
  const installer = fs.readFileSync(path.join(files, "install-runtime.sh"), "utf8");

  assert.match(cameraService, /After=.*kaderblick-boot-preflight\.service/);
  assert.match(cameraService, /Wants=kaderblick-boot-preflight\.service/);
  assert.match(preflightService, /Before=camera_service\.service kaderblick_app\.service/);
  assert.match(preflightService, /Type=oneshot/);
  assert.match(preflightService, /TimeoutStartSec=15/);
  assert.match(preflightService, /RemainAfterExit=yes/);
  assert.doesNotMatch(preflightService, /OnCalendar|\.timer/);
  assert.match(preflight, /HTTPConnection\("deb\.debian\.org", 80/);
  assert.match(preflight, /fstrim --quiet-unsupported \/ /);
  assert.match(installer, /systemctl mask apt-daily\.service/);
  assert.match(installer, /cron\.service/);
  assert.match(installer, /fstrim\.timer/);
  assert.match(installer, /e2scrub_reap\.service/);
  assert.match(installer, /systemd-timesyncd\.service/);
  assert.match(apiService, /--no-access-log/);
});

test("grants the camera account access to Raspberry Pi GPIO devices", () => {
  const files = path.join(
    __dirname,
    "..", "..", "image-builder", "stage-kaderblick", "00-runtime", "files"
  );
  const installer = fs.readFileSync(path.join(files, "install-runtime.sh"), "utf8");
  const gpioRule = fs.readFileSync(path.join(files, "99-kaderblick-gpio.rules"), "utf8");

  assert.match(installer, /99-kaderblick-gpio\.rules/);
  assert.match(gpioRule, /SUBSYSTEM=="gpio"/);
  assert.match(gpioRule, /KERNEL=="gpiochip\*"/);
  assert.match(gpioRule, /MODE="0660"/);
  assert.match(gpioRule, /GROUP="gpio"/);
});
