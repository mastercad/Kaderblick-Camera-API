"use strict";

const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const { validateConfiguration } = require("./config");
const { getDrive, listDrives, startScanner, stopScanner } = require("./drives");
const { downloadOfficialImage } = require("./download");
const { elevatedFlash } = require("./elevated-flash");

const execFileAsync = promisify(execFile);
const RUNTIME_NAME = "kaderblick-camera-runtime-bookworm-arm64.tar.xz";

let mainWindow;
let flashing = false;

async function getRuntimePath() {
  if (process.env.KADERBLICK_RUNTIME) return process.env.KADERBLICK_RUNTIME;
  if (app.isPackaged) return path.join(process.resourcesPath, "assets", RUNTIME_NAME);

  const outputDirectory = path.join(app.getPath("userData"), "development-runtime");
  const buildScript = path.join(__dirname, "..", "..", "image-builder", "build-runtime.sh");
  await execFileAsync("bash", [buildScript, outputDirectory]);
  return path.join(outputDirectory, RUNTIME_NAME);
}

function createWindow() {
  const iconPath = app.isPackaged
    ? path.join(process.resourcesPath, "assets", "kaderblick_camera_api_appicon.png")
    : path.join(__dirname, "..", "..", "assets", "kaderblick_camera_api_appicon.png");
  mainWindow = new BrowserWindow({
    width: 760,
    height: 820,
    minWidth: 680,
    minHeight: 700,
    icon: iconPath,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  mainWindow.removeMenu();
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
  mainWindow.once("ready-to-show", () => mainWindow.show());
}

app.whenReady().then(async () => {
  createWindow();
  await startScanner(() => mainWindow?.webContents.send("drives:changed", listDrives()));
  mainWindow?.webContents.send("drives:changed", listDrives());
});

app.on("window-all-closed", () => app.quit());
app.on("before-quit", stopScanner);

ipcMain.handle("drives:list", () => listDrives());
ipcMain.handle("app:icon", async () => {
  const iconPath = app.isPackaged
    ? path.join(process.resourcesPath, "assets", "kaderblick_camera_api_appicon.png")
    : path.join(__dirname, "..", "..", "assets", "kaderblick_camera_api_appicon.png");
  const data = await require("node:fs/promises").readFile(iconPath);
  return `data:image/png;base64,${data.toString("base64")}`;
});

ipcMain.handle("flash:start", async (_event, request) => {
  if (flashing) throw new Error("Ein Schreibvorgang läuft bereits.");
  const configuration = validateConfiguration(request.configuration);
  const destination = getDrive(request.driveId);
  if (!destination || destination.isSystem) throw new Error("Der gewählte Datenträger ist nicht mehr verfügbar.");

  const response = await dialog.showMessageBox(mainWindow, {
    type: "warning",
    buttons: ["Abbrechen", "Datenträger vollständig löschen"],
    defaultId: 0,
    cancelId: 0,
    noLink: true,
    title: "Alle Daten werden gelöscht",
    message: `${destination.description} · ${(destination.size / 1000 ** 3).toFixed(1)} GB · ${destination.device}`,
    detail: `Dieser Datenträger wird vollständig überschrieben. Alle Partitionen und Dateien gehen unwiderruflich verloren.${destination.mountpoints.length ? `\n\nAktuell eingebunden: ${destination.mountpoints.join(", ")}` : ""}`
  });
  if (response.response !== 1) return { cancelled: true };

  flashing = true;
  try {
    const sendProgress = (progress) => mainWindow?.webContents.send("flash:progress", progress);
    const imagePath = process.env.KADERBLICK_IMAGE || await downloadOfficialImage(
      path.join(app.getPath("userData"), "images"),
      sendProgress
    );
    const runtimePath = await getRuntimePath();
    const installScriptPath = app.isPackaged
      ? path.join(process.resourcesPath, "assets", "install-runtime.sh")
      : path.join(__dirname, "..", "..", "image-builder", "stage-kaderblick", "00-runtime", "files", "install-runtime.sh");
    await elevatedFlash({
      helperPath: path.join(app.getAppPath(), "src", "helper.js"),
      imagePath,
      runtimePath,
      installScriptPath,
      drive: {
        raw: destination.raw,
        size: destination.size
      },
      configuration,
      onProgress: sendProgress
    });
    return { cancelled: false, success: true };
  } finally {
    flashing = false;
  }
});
