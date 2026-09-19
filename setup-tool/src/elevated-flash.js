"use strict";

const { spawn } = require("node:child_process");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

function quote(argument) {
  if (process.platform === "win32") return `"${argument.replaceAll('"', '\\"')}"`;
  return `'${argument.replaceAll("'", "'\\''")}'`;
}

async function pollProgress(progressPath, onProgress, done) {
  let previous = "";
  while (!done.value) {
    try {
      const current = await fs.readFile(progressPath, "utf8");
      if (current !== previous) {
        previous = current;
        onProgress(JSON.parse(current));
      }
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
}

function executeHelper(helperPath, jobPath) {
  const environment = { ...process.env, ELECTRON_RUN_AS_NODE: "1" };
  if (process.platform === "win32") {
    return new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [helperPath, jobPath], { env: environment, windowsHide: true });
      let stderr = "";
      child.stderr.on("data", (chunk) => { stderr += chunk; });
      child.on("error", reject);
      child.on("exit", (code) => code === 0 ? resolve() : reject(new Error(stderr.trim() || `Hilfsprozess beendet: ${code}`)));
    });
  }
  return new Promise((resolve, reject) => {
    let executable;
    let args;
    if (process.platform === "darwin") {
      const command = `/usr/bin/env ELECTRON_RUN_AS_NODE=1 ${quote(process.execPath)} ${quote(helperPath)} ${quote(jobPath)}`;
      const appleScript = `do shell script "${command.replaceAll("\\", "\\\\").replaceAll('"', '\\"')}" with administrator privileges`;
      executable = "/usr/bin/osascript";
      args = ["-e", appleScript];
    } else {
      executable = "pkexec";
      args = ["/usr/bin/env", "ELECTRON_RUN_AS_NODE=1", process.execPath, helperPath, jobPath];
    }
    const child = spawn(executable, args, { env: process.env });
    let stderr = "";
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", (error) => {
      const hint = process.platform === "linux" && error.code === "ENOENT" ? " (polkit/pkexec fehlt)" : "";
      reject(new Error(`${error.message}${hint}`));
    });
    child.on("exit", (code) => code === 0 ? resolve() : reject(new Error(stderr.trim() || `Administratorfreigabe abgebrochen (${code}).`)));
  });
}

async function elevatedFlash({ helperPath, imagePath, drive, configuration, onProgress }) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "kaderblick-flash-"));
  const jobPath = path.join(directory, "job.json");
  const progressPath = path.join(directory, "progress.json");
  const job = {
    imagePath,
    driveRaw: drive.raw,
    driveSize: drive.size,
    configuration,
    progressPath
  };
  await fs.writeFile(jobPath, JSON.stringify(job), { mode: 0o600 });
  const done = { value: false };
  const polling = pollProgress(progressPath, onProgress, done);
  try {
    await executeHelper(helperPath, jobPath);
  } finally {
    done.value = true;
    await polling;
    await Promise.allSettled([
      fs.unlink(jobPath),
      fs.unlink(progressPath),
      fs.unlink(`${progressPath}.new`)
    ]);
    await fs.rmdir(directory).catch(() => {});
  }
}

module.exports = { elevatedFlash, quote };
