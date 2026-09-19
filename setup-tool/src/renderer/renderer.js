"use strict";

const form = document.querySelector("#setup-form");
const driveSelect = document.querySelector("#drive");
const flashButton = document.querySelector("#flash");
const statusBox = document.querySelector("#status");
const statusText = document.querySelector("#status-text");
const statusPercent = document.querySelector("#status-percent");
const progressBar = document.querySelector("#progress");

window.cameraSetup.getAppIcon().then((source) => {
  document.querySelector("#app-icon").src = source;
});

function formatBytes(bytes) {
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

function updateDrives(drives) {
  const selected = driveSelect.value;
  driveSelect.replaceChildren(new Option("USB-Festplatte oder SD-Karte auswählen …", ""));
  for (const drive of drives) {
    const mountpoints = drive.mountpoints.length ? ` · ${drive.mountpoints.join(", ")}` : "";
    driveSelect.add(new Option(`${drive.description} · ${drive.busType} · ${formatBytes(drive.size)} · ${drive.device}${mountpoints}`, drive.id));
  }
  if (drives.some((drive) => drive.id === selected)) driveSelect.value = selected;
}

function selectedCamera() {
  return Number(document.querySelector('input[name="camera"]:checked').value);
}

document.querySelectorAll('input[name="camera"]').forEach((radio) => {
  radio.addEventListener("change", () => {
    document.querySelector("#ip").value = selectedCamera() === 1 ? "192.168.178.47" : "192.168.178.48";
  });
});

document.querySelector("#show-password").addEventListener("change", (event) => {
  document.querySelector("#password").type = event.target.checked ? "text" : "password";
});

document.querySelector("#refresh").addEventListener("click", async () => updateDrives(await window.cameraSetup.listDrives()));
window.cameraSetup.onDrivesChanged(updateDrives);
window.cameraSetup.onProgress((progress) => {
  const percentage = Math.max(0, Math.min(100, Math.round(progress.percentage || 0)));
  const labels = { downloading: "Image wird aus GitHub geladen", checking: "Image-Prüfsumme wird geprüft", decompressing: "Image wird vorbereitet", flashing: "Datenträger wird geschrieben", verifying: "Datenträger wird geprüft", finished: "Fertig" };
  statusText.textContent = labels[progress.type] || "Datenträger wird vorbereitet";
  statusPercent.textContent = `${percentage} %`;
  progressBar.value = percentage;
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  flashButton.disabled = true;
  statusBox.hidden = false;
  statusText.textContent = "Vorbereitung …";
  statusPercent.textContent = "0 %";
  progressBar.value = 0;
  try {
    const result = await window.cameraSetup.startFlash({
      driveId: driveSelect.value,
      configuration: {
        camera: selectedCamera(),
        username: document.querySelector("#username").value,
        password: document.querySelector("#password").value,
        ip: document.querySelector("#ip").value,
        netmask: document.querySelector("#netmask").value,
        gateway: document.querySelector("#gateway").value
      }
    });
    if (result.cancelled) {
      statusBox.hidden = true;
    } else {
      statusText.textContent = "Fertig – Datenträger kann sicher entfernt werden";
      statusPercent.textContent = "100 %";
      progressBar.value = 100;
    }
  } catch (error) {
    statusText.textContent = `Fehler: ${error.message}`;
    statusPercent.textContent = "";
  } finally {
    flashButton.disabled = false;
  }
});

window.cameraSetup.listDrives().then(updateDrives);
