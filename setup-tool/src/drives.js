"use strict";

const { scanner } = require("etcher-sdk");

let deviceScanner;

async function startScanner(onChange) {
  if (deviceScanner) return deviceScanner;
  const adapter = new scanner.adapters.BlockDeviceAdapter({
    includeSystemDrives: () => false,
    includeVirtualDrives: () => false,
    unmountOnSuccess: true,
    write: true,
    direct: true
  });
  deviceScanner = new scanner.Scanner([adapter]);
  deviceScanner.on("attach", onChange);
  deviceScanner.on("detach", onChange);
  deviceScanner.on("error", (error) => onChange(error));
  await deviceScanner.start();
  return deviceScanner;
}

function listDrives() {
  if (!deviceScanner) return [];
  return Array.from(deviceScanner.drives)
    .filter((drive) => !drive.isSystem && drive.size)
    .map((drive) => ({
      id: drive.raw,
      device: drive.device,
      description: drive.description || "Wechseldatenträger",
      busType: drive.busType || "unbekannt",
      size: drive.size,
      mountpoints: drive.mountpoints.map((entry) => entry.path)
    }))
    .sort((a, b) => a.device.localeCompare(b.device));
}

function getDrive(id) {
  if (!deviceScanner) return undefined;
  return Array.from(deviceScanner.drives).find((drive) => drive.raw === id);
}

function stopScanner() {
  deviceScanner?.stop();
  deviceScanner = undefined;
}

module.exports = { getDrive, listDrives, startScanner, stopScanner };
