# Kaderblick Kamera Setup

Das Desktop-Tool lädt das von GitHub Actions erzeugte Offline-Laufzeit-Image aus dem neuesten GitHub Release, prüft dessen SHA-256-Prüfsumme, schreibt es auf eine externe USB-Festplatte/SSD oder SD-Karte und trägt die individuelle Kamera-, Konto- und Ethernet-Konfiguration direkt in dessen FAT-Bootpartition ein. Der Setup-Rechner benötigt dafür Internet. Der fertig eingerichtete Raspberry Pi benötigt im Betrieb kein Internet.

## Entwicklung

```bash
cd setup-tool
npm ci
npm test
npm start
```

Das Schreiben eines Blockgeräts benötigt Administratorrechte. Für Entwicklungstests kann mit `KADERBLICK_IMAGE=/pfad/zum/image.img.xz npm start` ein lokales Image statt des GitHub-Downloads verwendet werden.

## Netzwerk

Der Raspberry Pi stellt kein WLAN bereit. `wlan0` und Bluetooth sind im Image deaktiviert. Die API und die SMB-Freigabe laufen ausschließlich über Ethernet. Das Gateway ist optional und für Zugriffe innerhalb desselben IPv4-Subnetzes nicht erforderlich.

## Veröffentlichung

Ein Tag im Format `v*` startet `.github/workflows/release.yml`. GitHub Actions baut zuerst das ARM64-Kameraimage und anschließend die nativen Setup-Pakete:

| Plattform | Portable | Installer |
|---|---|---|
| Linux x64 | AppImage | DEB |
| Windows x64 | Portable EXE | NSIS-Installer |
| macOS Intel/Apple Silicon | ZIP | DMG |

Alle Dateien einschließlich Image und SHA-256-Datei werden gemeinsam an das GitHub Release angehängt. Das Kaderblick-Kamera-Icon wird als Paket-/App-Icon und sichtbar in der Oberfläche verwendet. Ohne hinterlegte Signaturzertifikate sind die Pakete technisch vollständig, können aber Warnungen von Windows SmartScreen oder macOS Gatekeeper auslösen.
