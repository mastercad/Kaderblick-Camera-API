"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");
const { pipeline } = require("node:stream/promises");
const { Readable, Transform } = require("node:stream");

const RELEASE_API = "https://api.github.com/repos/mastercad/Kaderblick-Camera-API/releases/latest";
const IMAGE_PATTERN = /^kaderblick-camera-os-.*\.img\.xz$/;

async function githubFetch(url) {
  const response = await fetch(url, {
    redirect: "follow",
    headers: {
      Accept: "application/vnd.github+json",
      "User-Agent": "Kaderblick-Camera-Setup",
      "X-GitHub-Api-Version": "2022-11-28"
    }
  });
  if (!response.ok) throw new Error(`GitHub-Download fehlgeschlagen (HTTP ${response.status}).`);
  return response;
}

async function sha256(filename) {
  const hash = crypto.createHash("sha256");
  await pipeline(fs.createReadStream(filename), hash);
  return hash.digest("hex");
}

async function downloadFile(url, destination, totalBytes, onProgress) {
  const response = await githubFetch(url);
  let received = 0;
  const meter = new Transform({
    transform(chunk, _encoding, callback) {
      received += chunk.length;
      onProgress({
        type: "downloading",
        percentage: totalBytes ? received / totalBytes * 100 : 0,
        bytes: received,
        size: totalBytes
      });
      callback(null, chunk);
    }
  });
  await pipeline(Readable.fromWeb(response.body), meter, fs.createWriteStream(destination));
}

async function downloadLatestImage(cacheDirectory, onProgress) {
  const release = await (await githubFetch(RELEASE_API)).json();
  const imageAsset = release.assets.find((asset) => IMAGE_PATTERN.test(asset.name));
  const checksumAsset = release.assets.find((asset) => asset.name === `${imageAsset?.name}.sha256`);
  if (!imageAsset || !checksumAsset) {
    throw new Error("Das neueste GitHub Release enthält kein vollständiges Kamera-Image mit Prüfsumme.");
  }

  await fsp.mkdir(cacheDirectory, { recursive: true });
  const imagePath = path.join(cacheDirectory, imageAsset.name);
  const checksumPath = `${imagePath}.sha256`;
  const partialPath = `${imagePath}.part`;

  if (!(await fsp.stat(imagePath).catch(() => null))) {
    await downloadFile(imageAsset.browser_download_url, partialPath, imageAsset.size, onProgress);
    await fsp.rename(partialPath, imagePath);
  }
  if (!(await fsp.stat(checksumPath).catch(() => null))) {
    await downloadFile(checksumAsset.browser_download_url, checksumPath, checksumAsset.size, () => {});
  }

  onProgress({ type: "checking", percentage: 0 });
  const expected = (await fsp.readFile(checksumPath, "utf8")).trim().split(/\s+/)[0].toLowerCase();
  const actual = await sha256(imagePath);
  if (!/^[a-f0-9]{64}$/.test(expected) || actual !== expected) {
    await Promise.allSettled([fsp.unlink(imagePath), fsp.unlink(checksumPath)]);
    throw new Error("Die SHA-256-Prüfung des Kamera-Images ist fehlgeschlagen.");
  }
  onProgress({ type: "checking", percentage: 100 });
  return imagePath;
}

module.exports = { IMAGE_PATTERN, downloadLatestImage, sha256 };
