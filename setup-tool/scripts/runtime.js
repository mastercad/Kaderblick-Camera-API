"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const setupRoot = path.join(__dirname, "..");
const repositoryRoot = path.join(setupRoot, "..");
const runtimeDirectory = path.join(setupRoot, "runtime");
const runtimeName = "kaderblick-camera-runtime-trixie-arm64.tar.xz";
const runtimePath = path.join(runtimeDirectory, runtimeName);
const checksumPath = `${runtimePath}.sha256`;

function sha256(filename) {
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(filename));
  return hash.digest("hex");
}

function verifyRuntime() {
  if (!fs.existsSync(runtimePath) || !fs.existsSync(checksumPath)) {
    throw new Error("Camera-Runtime oder SHA-256-Datei fehlt.");
  }

  const checksumLine = fs.readFileSync(checksumPath, "utf8").trim();
  const [expected, filename, ...unexpected] = checksumLine.split(/\s+/);
  if (
    unexpected.length
    || !/^[a-f0-9]{64}$/.test(expected)
    || filename !== runtimeName
    || sha256(runtimePath) !== expected
  ) {
    throw new Error("Die gebuendelte Camera-Runtime hat keine gueltige SHA-256-Pruefsumme.");
  }
  console.log(`Camera-Runtime verifiziert: ${expected}`);
}

function buildRuntime() {
  fs.mkdirSync(runtimeDirectory, { recursive: true });
  execFileSync(
    "bash",
    [path.join(repositoryRoot, "image-builder", "build-runtime.sh"), runtimeDirectory],
    { stdio: "inherit" }
  );
  verifyRuntime();
}

const command = process.argv[2];
if (command === "build") {
  buildRuntime();
} else if (command === "verify") {
  verifyRuntime();
} else {
  throw new Error("Aufruf: node scripts/runtime.js build|verify");
}
