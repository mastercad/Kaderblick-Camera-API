"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { netmaskToPrefix, validateConfiguration, validatePreparedConfiguration } = require("../src/config");

test("converts contiguous netmasks", () => {
  assert.equal(netmaskToPrefix("255.255.255.0"), 24);
  assert.equal(netmaskToPrefix("255.255.0.0"), 16);
  assert.equal(netmaskToPrefix("255.255.255.255"), 32);
});

test("rejects non-contiguous netmasks", () => {
  assert.throws(() => netmaskToPrefix("255.0.255.0"), /zusammenhängend/);
});

test("creates a gateway-free camera configuration", () => {
  assert.deepEqual(validateConfiguration({
    camera: 2,
    username: "kaderblick",
    password: "kaderblick",
    ip: "192.168.178.48",
    netmask: "255.255.255.0",
    gateway: ""
  }), {
    schema: 1,
    camera: 2,
    hostname: "kamera2",
    username: "kaderblick",
    password: "kaderblick",
    ip: "192.168.178.48",
    prefix: 24,
    gateway: ""
  });
});

test("validates the prepared configuration again without expecting a netmask", () => {
  const prepared = validateConfiguration({
    camera: 1,
    username: "kaderblick",
    password: "kaderblick",
    ip: "192.168.178.47",
    netmask: "255.255.255.0",
    gateway: "192.168.178.1"
  });
  assert.deepEqual(validatePreparedConfiguration(prepared), prepared);
  assert.throws(
    () => validatePreparedConfiguration({ ...prepared, prefix: 33 }),
    /Präfixlänge/
  );
  assert.throws(
    () => validatePreparedConfiguration({ ...prepared, hostname: "fremd" }),
    /Kamerakonfiguration/
  );
});

test("rejects invalid accounts and addresses", () => {
  const base = { camera: 1, username: "kaderblick", password: "x", ip: "192.168.178.47", netmask: "255.255.255.0", gateway: "" };
  assert.throws(() => validateConfiguration({ ...base, username: "Root User" }), /Benutzername/);
  assert.throws(() => validateConfiguration({ ...base, username: "root" }), /reserviert/);
  assert.throws(() => validateConfiguration({ ...base, ip: "999.1.1.1" }), /IPv4/);
  assert.throws(() => validateConfiguration({ ...base, gateway: "router" }), /Gateway/);
});

test("rejects unusable camera and gateway addresses", () => {
  assert.throws(() => validateConfiguration({
    camera: 1, username: "kaderblick", password: "kaderblick",
    ip: "192.168.178.0", netmask: "255.255.255.0", gateway: ""
  }), /Netzwerk- oder Broadcastadresse/);
  assert.throws(() => validateConfiguration({
    camera: 1, username: "kaderblick", password: "kaderblick",
    ip: "192.168.178.47", netmask: "255.255.255.0", gateway: "192.168.179.1"
  }), /selben Subnetz/);
  assert.throws(() => validateConfiguration({
    camera: 1, username: "kaderblick", password: "kaderblick",
    ip: "192.168.178.47", netmask: "255.255.255.0", gateway: "192.168.178.47"
  }), /nicht dieselbe Adresse/);
});
