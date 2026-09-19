"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("cameraSetup", {
  getAppIcon: () => ipcRenderer.invoke("app:icon"),
  listDrives: () => ipcRenderer.invoke("drives:list"),
  startFlash: (request) => ipcRenderer.invoke("flash:start", request),
  onDrivesChanged: (callback) => ipcRenderer.on("drives:changed", (_event, drives) => callback(drives)),
  onProgress: (callback) => ipcRenderer.on("flash:progress", (_event, progress) => callback(progress))
});
