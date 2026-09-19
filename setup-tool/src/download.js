"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");
const { pipeline } = require("node:stream/promises");
const { Readable, Transform } = require("node:stream");

const OFFICIAL_IMAGE_URL = "https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2025-05-13/2025-05-13-raspios-bookworm-arm64-lite.img.xz";
const OFFICIAL_CHECKSUM_URL = `${OFFICIAL_IMAGE_URL}.sha256`;
const RELEASE_API = "https://api.github.com/repos/mastercad/Kaderblick-Camera-API/releases/latest";
const RUNTIME_NAME = "kaderblick-camera-runtime-bookworm-arm64.tar.xz";

async function checkedFetch(url) {
  const github = new URL(url).hostname === "api.github.com";
  const response = await fetch(url, {
    redirect: "follow",
    headers: {
      Accept: github ? "application/vnd.github+json" : "*/*",
      "User-Agent": "Kaderblick-Camera-Setup",
      ...(github ? { "X-GitHub-Api-Version": "2022-11-28" } : {})
    }
  });
  if (!response.ok) throw new Error(`Download fehlgeschlagen (HTTP ${response.status}).`);
  return response;
}

async function sha256(filename) {
  const hash = crypto.createHash("sha256");
  await pipeline(fs.createReadStream(filename), hash);
  return hash.digest("hex");
}

async function downloadFile(url, destination, totalBytes, onProgress) {
  const response = await checkedFetch(url);
  const expectedBytes = totalBytes || Number(response.headers.get("content-length")) || 0;
  let received = 0;
  const meter = new Transform({
    transform(chunk, _encoding, callback) {
      received += chunk.length;
      onProgress({
        type: "downloading",
        percentage: expectedBytes ? received / expectedBytes * 100 : 0,
        bytes: received,
        size: expectedBytes
      });
      callback(null, chunk);
    }
  });
  await pipeline(Readable.fromWeb(response.body), meter, fs.createWriteStream(destination));
}

async function downloadOfficialImage(cacheDirectory, onProgress) {
  await fsp.mkdir(cacheDirectory, { recursive: true });
  const imageName = path.basename(new URL(OFFICIAL_IMAGE_URL).pathname);
  const imagePath = path.join(cacheDirectory, imageName);
  const checksumPath = `${imagePath}.sha256`;
  const partialPath = `${imagePath}.part`;

  if (!(await fsp.stat(imagePath).catch(() => null))) {
    await downloadFile(OFFICIAL_IMAGE_URL, partialPath, 0, onProgress);
    await fsp.rename(partialPath, imagePath);
  }
  if (!(await fsp.stat(checksumPath).catch(() => null))) {
    await downloadFile(OFFICIAL_CHECKSUM_URL, checksumPath, 0, () => {});
  }

  onProgress({ type: "checking", percentage: 0 });
  const expected = (await fsp.readFile(checksumPath, "utf8")).trim().split(/\s+/)[0].toLowerCase();
  const actual = await sha256(imagePath);
  if (!/^[a-f0-9]{64}$/.test(expected) || actual !== expected) {
    await Promise.allSettled([fsp.unlink(imagePath), fsp.unlink(checksumPath)]);
    throw new Error("Die SHA-256-Prüfung des offiziellen Raspberry-Pi-OS-Images ist fehlgeschlagen.");
  }
  onProgress({ type: "checking", percentage: 100 });
  return imagePath;
}

async function downloadRuntimeBundle(cacheDirectory, onProgress) {
  const release = await (await checkedFetch(RELEASE_API)).json();
  const bundleAsset = release.assets.find((asset) => asset.name === RUNTIME_NAME);
  const checksumAsset = release.assets.find((asset) => asset.name === `${RUNTIME_NAME}.sha256`);
  if (!bundleAsset || !checksumAsset) {
    throw new Error("Das aktuelle Setup-Release enthält kein Camera-API-Laufzeitpaket.");
  }

  await fsp.mkdir(cacheDirectory, { recursive: true });
  const bundlePath = path.join(cacheDirectory, RUNTIME_NAME);
  const checksumPath = `${bundlePath}.sha256`;
  const partialPath = `${bundlePath}.part`;
  if (!(await fsp.stat(bundlePath).catch(() => null))) {
    await downloadFile(bundleAsset.browser_download_url, partialPath, bundleAsset.size, (progress) => {
      onProgress({ ...progress, type: "downloading-runtime" });
    });
    await fsp.rename(partialPath, bundlePath);
  }
  await downloadFile(checksumAsset.browser_download_url, checksumPath, checksumAsset.size, () => {});

  onProgress({ type: "checking-runtime", percentage: 0 });
  const expected = (await fsp.readFile(checksumPath, "utf8")).trim().split(/\s+/)[0].toLowerCase();
  const actual = await sha256(bundlePath);
  if (!/^[a-f0-9]{64}$/.test(expected) || actual !== expected) {
    await Promise.allSettled([fsp.unlink(bundlePath), fsp.unlink(checksumPath)]);
    throw new Error("Die SHA-256-Prüfung des Camera-API-Laufzeitpakets ist fehlgeschlagen.");
  }
  onProgress({ type: "checking-runtime", percentage: 100 });
  return bundlePath;
}

module.exports = {
  OFFICIAL_IMAGE_URL,
  RUNTIME_NAME,
  downloadOfficialImage,
  downloadRuntimeBundle,
  sha256
};
