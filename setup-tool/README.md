# Kaderblick Kamera Setup

Das Desktop-Tool lädt beim Einrichten das offizielle Raspberry Pi OS Lite direkt von Raspberry Pi, prüft dessen offizielle SHA-256-Prüfsumme und kombiniert es mit den bereits in der App enthaltenen Camera-API-Komponenten. Erst danach schreibt und konfiguriert es die externe USB-Festplatte/SSD oder SD-Karte vollständig. GitHub Actions erzeugt kein fertiges Raspberry-Pi-Image.

Der Windows-, Linux- oder macOS-Rechner benötigt während der Vorbereitung Internet. Beim einmaligen ersten Start benötigt auch der Raspberry Pi Internet über Ethernet, um die schlanken System- und Python-Pakete zu installieren. Der spätere Kamerabetrieb ist vollständig ohne Internet möglich.

## Entwicklung

```bash
cd setup-tool
npm ci
npm test
npm start
```

Das Schreiben eines Blockgeräts benötigt Administratorrechte. Für Entwicklungstests können mit `KADERBLICK_IMAGE=/pfad/zum/image.img.xz` und `KADERBLICK_RUNTIME=/pfad/zum/runtime.tar.xz` lokale Dateien statt der Downloads verwendet werden.

## Netzwerk

Der Raspberry Pi stellt kein WLAN bereit. `wlan0` und Bluetooth sind im Image deaktiviert. Die API und die SMB-Freigabe laufen ausschließlich über Ethernet. Das Gateway ist optional und für Zugriffe innerhalb desselben IPv4-Subnetzes nicht erforderlich.

## Veröffentlichung

Ein Tag im Format `v*` startet `.github/workflows/release.yml`. GitHub Actions bündelt die Camera-API-Installationsdateien und baut die nativen Setup-Pakete. Ein bootfähiges Raspberry-Pi-Image wird nicht in CI gebaut oder veröffentlicht:

| Plattform | Portable | Installer |
|---|---|---|
| Linux x64 | AppImage | DEB |
| Windows x64 | Portable EXE | NSIS-Installer |
| macOS Intel/Apple Silicon | ZIP | DMG |

Die Camera-API-Komponenten sind direkt in allen Installer-/Portable-Paketen enthalten. Das Kaderblick-Kamera-Icon wird als Paket-/App-Icon und sichtbar in der Oberfläche verwendet. Ohne hinterlegte Signaturzertifikate sind die Pakete technisch vollständig, können aber Warnungen von Windows SmartScreen oder macOS Gatekeeper auslösen.
