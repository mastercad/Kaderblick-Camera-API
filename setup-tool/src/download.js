"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");
const { pipeline } = require("node:stream/promises");
const { Readable, Transform } = require("node:stream");

const OFFICIAL_IMAGE_URL = "https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2025-05-13/2025-05-13-raspios-bookworm-arm64-lite.img.xz";
const OFFICIAL_CHECKSUM_URL = `${OFFICIAL_IMAGE_URL}.sha256`;

async function checkedFetch(url) {
  const response = await fetch(url, {
    redirect: "follow",
    headers: {
      Accept: "*/*",
      "User-Agent": "Kaderblick-Camera-Setup"
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

module.exports = {
  OFFICIAL_IMAGE_URL,
  downloadOfficialImage,
  sha256
};
