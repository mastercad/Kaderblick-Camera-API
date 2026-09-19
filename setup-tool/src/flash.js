"use strict";

const { promisify } = require("node:util");
const { interact } = require("balena-image-fs");
const { multiWrite, sourceDestination } = require("etcher-sdk");

async function configureBootPartition(disk, configuration) {
  await interact(disk, 1, async (filesystem) => {
    const writeFile = promisify(filesystem.writeFile.bind(filesystem));
    await writeFile("/kaderblick-config.json", `${JSON.stringify(configuration, null, 2)}\n`);
  });
}

async function flashImage({ imagePath, destination, configuration, onProgress }) {
  const source = new sourceDestination.File({ path: imagePath, write: false });
  const result = await multiWrite.decompressThenFlash({
    source,
    destinations: [destination],
    verify: true,
    trim: false,
    decompressFirst: imagePath.endsWith(".xz"),
    configure: (disk) => configureBootPartition(disk, configuration),
    onFail: (_drive, error) => { throw error; },
    onProgress,
    numBuffers: 16
  });
  if (result.failures.size) throw Array.from(result.failures.values())[0];
  return result;
}

module.exports = { configureBootPartition, flashImage };
