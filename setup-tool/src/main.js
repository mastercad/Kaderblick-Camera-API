"use strict";

const path = require("node:path");
const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const { validateConfiguration } = require("./config");
const { getDrive, listDrives, startScanner, stopScanner } = require("./drives");
const { downloadLatestImage } = require("./download");
const { elevatedFlash } = require("./elevated-flash");

let mainWindow;
let flashing = false;

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
    const imagePath = process.env.KADERBLICK_IMAGE || await downloadLatestImage(
      path.join(app.getPath("userData"), "images"),
      sendProgress
    );
    await elevatedFlash({
      helperPath: path.join(app.getAppPath(), "src", "helper.js"),
      imagePath,
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
