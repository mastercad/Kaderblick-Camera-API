"use strict";

const fs = require("node:fs/promises");
const drivelist = require("drivelist");
const { sourceDestination } = require("etcher-sdk");
const { validateConfiguration } = require("./config");
const { flashImage } = require("./flash");

async function writeProgress(filename, progress) {
  const temporary = `${filename}.new`;
  await fs.writeFile(temporary, JSON.stringify(progress), { mode: 0o644 });
  await fs.rename(temporary, filename);
}

async function main() {
  const jobPath = process.argv[2];
  if (!jobPath) throw new Error("Flash-Auftrag fehlt.");
  const job = JSON.parse(await fs.readFile(jobPath, "utf8"));
  const configuration = validateConfiguration(job.configuration);
  const drives = await drivelist.list();
  const drive = drives.find((candidate) => candidate.raw === job.driveRaw);
  if (!drive || drive.isSystem || drive.isVirtual || drive.isReadOnly) {
    throw new Error("Der Zieldatenträger ist nicht verfügbar oder nicht beschreibbar.");
  }
  if (drive.size !== job.driveSize) {
    throw new Error("Der Zieldatenträger hat sich seit der Bestätigung geändert.");
  }

  const destination = new sourceDestination.BlockDevice({
    drive,
    unmountOnSuccess: true,
    write: true,
    direct: true
  });
  let progressWrites = Promise.resolve();
  await flashImage({
    imagePath: job.imagePath,
    destination,
    configuration,
    onProgress: (progress) => {
      progressWrites = progressWrites.then(() => writeProgress(job.progressPath, progress));
    }
  });
  await progressWrites;
  await writeProgress(job.progressPath, { type: "finished", percentage: 100 });
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
