"use strict";

const net = require("node:net");

const CAMERA_DEFAULTS = Object.freeze({
  1: "192.168.178.47",
  2: "192.168.178.48"
});
const RESERVED_USERNAMES = new Set([
  "root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail",
  "news", "uucp", "proxy", "www-data", "backup", "list", "irc", "_apt",
  "nobody", "systemd-network", "systemd-timesync", "messagebus", "sshd"
]);

function netmaskToPrefix(mask) {
  const octets = String(mask).trim().split(".");
  if (octets.length !== 4 || octets.some((value) => !/^\d+$/.test(value))) {
    throw new Error("Die Netzmaske ist ungültig.");
  }
  const binary = octets.map(Number).map((value) => {
    if (value < 0 || value > 255) throw new Error("Die Netzmaske ist ungültig.");
    return value.toString(2).padStart(8, "0");
  }).join("");
  if (!/^1*0*$/.test(binary)) throw new Error("Die Netzmaske muss zusammenhängend sein.");
  return binary.indexOf("0") === -1 ? 32 : binary.indexOf("0");
}

function validateUsername(username) {
  if (!/^[a-z_][a-z0-9_-]{0,31}$/.test(username)) {
    throw new Error("Der Benutzername darf nur Kleinbuchstaben, Ziffern, _ und - enthalten.");
  }
  if (RESERVED_USERNAMES.has(username)) {
    throw new Error("Dieser Benutzername ist für das Betriebssystem reserviert.");
  }
}

function ipv4ToInteger(address) {
  return address.split(".").reduce((result, octet) => ((result << 8) | Number(octet)) >>> 0, 0);
}

function validateNetwork(ip, gateway, prefix) {
  const address = ipv4ToInteger(ip);
  const mask = prefix === 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0;
  const hostMask = (~mask) >>> 0;
  const host = address & hostMask;
  if (prefix <= 30 && (host === 0 || host === hostMask)) {
    throw new Error("Die Kamera-IP darf keine Netzwerk- oder Broadcastadresse sein.");
  }
  if (!gateway) return;
  const gatewayAddress = ipv4ToInteger(gateway);
  if ((gatewayAddress & mask) !== (address & mask)) {
    throw new Error("Der Gateway muss im selben Subnetz wie die Kamera liegen.");
  }
  if (gatewayAddress === address) {
    throw new Error("Kamera und Gateway dürfen nicht dieselbe Adresse verwenden.");
  }
  const gatewayHost = gatewayAddress & hostMask;
  if (prefix <= 30 && (gatewayHost === 0 || gatewayHost === hostMask)) {
    throw new Error("Der Gateway darf keine Netzwerk- oder Broadcastadresse sein.");
  }
}

function validateConfiguration(input) {
  const camera = Number(input.camera);
  if (![1, 2].includes(camera)) throw new Error("Bitte Kamera 1 oder Kamera 2 wählen.");

  const username = String(input.username || "").trim();
  const password = String(input.password || "");
  const ip = String(input.ip || "").trim();
  const netmask = String(input.netmask || "").trim();
  const gateway = String(input.gateway || "").trim();

  validateUsername(username);
  if (password.length < 1 || password.includes("\n") || password.includes("\r")) {
    throw new Error("Das Passwort darf nicht leer sein und keine Zeilenumbrüche enthalten.");
  }
  if (net.isIP(ip) !== 4) throw new Error("Die IPv4-Adresse ist ungültig.");
  if (gateway && net.isIP(gateway) !== 4) throw new Error("Der Gateway ist ungültig.");
  const prefix = netmaskToPrefix(netmask);
  validateNetwork(ip, gateway, prefix);

  return {
    schema: 1,
    camera,
    hostname: `kamera${camera}`,
    username,
    password,
    ip,
    prefix,
    gateway
  };
}

function validatePreparedConfiguration(input) {
  const camera = Number(input.camera);
  const username = String(input.username || "").trim();
  const password = String(input.password || "");
  const ip = String(input.ip || "").trim();
  const gateway = String(input.gateway || "").trim();
  const prefix = Number(input.prefix);
  const hostname = `kamera${camera}`;

  if (input.schema !== 1 || ![1, 2].includes(camera) || input.hostname !== hostname) {
    throw new Error("Die vorbereitete Kamerakonfiguration ist ungültig.");
  }
  validateUsername(username);
  if (password.length < 1 || password.includes("\n") || password.includes("\r")) {
    throw new Error("Das Passwort darf nicht leer sein und keine Zeilenumbrüche enthalten.");
  }
  if (net.isIP(ip) !== 4) throw new Error("Die IPv4-Adresse ist ungültig.");
  if (gateway && net.isIP(gateway) !== 4) throw new Error("Der Gateway ist ungültig.");
  if (!Number.isInteger(prefix) || prefix < 0 || prefix > 32) {
    throw new Error("Die Präfixlänge ist ungültig.");
  }
  validateNetwork(ip, gateway, prefix);

  return { schema: 1, camera, hostname, username, password, ip, prefix, gateway };
}

module.exports = { CAMERA_DEFAULTS, netmaskToPrefix, validateConfiguration, validatePreparedConfiguration };
