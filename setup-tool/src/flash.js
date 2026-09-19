"use strict";

const { promisify } = require("node:util");
const fs = require("node:fs/promises");
const { interact } = require("balena-image-fs");
const { multiWrite, sourceDestination } = require("etcher-sdk");

function prepareCmdline(contents) {
  const tokens = String(contents).trim().split(/\s+/);
  const managed = ["systemd.run=", "systemd.run_success_action=", "systemd.unit="];
  const additions = [
    "systemd.run=/boot/firmware/kaderblick-install.sh",
    "systemd.run_success_action=reboot",
    "systemd.unit=kernel-command-line.target"
  ];
  return `${[...tokens.filter((token) => !managed.some((prefix) => token.startsWith(prefix))), ...additions].join(" ")}\n`;
}

function prepareConfig(contents) {
  const marker = "# Kaderblick Camera API";
  const original = String(contents).split(marker, 1)[0].trimEnd();
  return `${original}\n\n${marker}\ndtoverlay=disable-wifi\ndtoverlay=disable-bt\nusb_max_current_enable=1\n`;
}

async function configureBootPartition(disk, configuration, runtimePath, installScriptPath) {
  await interact(disk, 1, async (filesystem) => {
    const writeFile = promisify(filesystem.writeFile.bind(filesystem));
    const readFile = promisify(filesystem.readFile.bind(filesystem));
    await writeFile("/kaderblick-config.json", `${JSON.stringify(configuration, null, 2)}\n`);
    await writeFile("/kaderblick-runtime-bookworm-arm64.tar.xz", await fs.readFile(runtimePath));
    await writeFile("/kaderblick-install.sh", await fs.readFile(installScriptPath));

    await writeFile("/cmdline.txt", prepareCmdline((await readFile("/cmdline.txt")).toString("utf8")));
    await writeFile("/config.txt", prepareConfig((await readFile("/config.txt")).toString("utf8")));
  });
}

async function flashImage({ imagePath, runtimePath, installScriptPath, destination, configuration, onProgress }) {
  const source = new sourceDestination.File({ path: imagePath, write: false });
  const result = await multiWrite.decompressThenFlash({
    source,
    destinations: [destination],
    verify: true,
    trim: false,
    decompressFirst: imagePath.endsWith(".xz"),
    configure: (disk) => configureBootPartition(disk, configuration, runtimePath, installScriptPath),
    onFail: (_drive, error) => { throw error; },
    onProgress,
    numBuffers: 16
  });
  if (result.failures.size) throw Array.from(result.failures.values())[0];
  return result;
}

module.exports = { configureBootPartition, flashImage, prepareCmdline, prepareConfig };
