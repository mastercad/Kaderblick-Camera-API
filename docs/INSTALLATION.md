# Installation der Kamera

Die produktiven Raspberry Pi 5 werden mit dem **Kaderblick Kamera Setup** vorbereitet. Am späteren Einsatzort ist keine Internetverbindung erforderlich.

## Voraussetzungen

- Raspberry Pi 5
- externe USB-3-Festplatte/SSD oder alternativ eine SD-Karte
- Arducam B0589 (`04b4:0822`)
- ausreichend dimensioniertes Netzteil; bei gleichzeitig angeschlossener USB-Kamera und USB-Festplatte ist die stabile Stromversorgung besonders wichtig
- Internetzugang auf dem Windows-, Linux- oder macOS-Rechner während der Vorbereitung
- Internetzugang über Ethernet beim einmaligen ersten Start des Raspberry Pi

## Datenträger vorbereiten

1. Portable Version oder Installer aus dem neuesten GitHub Release starten.
2. Kamera 1 oder Kamera 2 auswählen.
3. Konto, Passwort, IPv4-Adresse und Netzmaske eintragen.
4. Gateway nur eintragen, wenn Verkehr in ein anderes Subnetz geleitet werden muss. Für den lokalen Zugriff innerhalb `192.168.178.0/24` bleibt das Feld leer.
5. Die externe USB-Festplatte/SSD oder SD-Karte auswählen.
6. Die vollständige Löschung des exakt angezeigten Datenträgers bestätigen.

Das Tool lädt Raspberry Pi OS Lite direkt von Raspberry Pi und kontrolliert dessen offizielle SHA-256-Prüfsumme. Zusätzlich lädt es die geprüften Camera-API-Komponenten aus dem Kaderblick-Release und schreibt beides zusammen mit der individuellen Konfiguration auf den Datenträger. GitHub stellt kein vorgefertigtes Kameraimage bereit.

Standardwerte:

| Auswahl | Hostname | IPv4-Adresse |
|---|---|---|
| Kamera 1 | `kamera1` | `192.168.178.47` |
| Kamera 2 | `kamera2` | `192.168.178.48` |

Benutzer und Passwort sind standardmäßig jeweils `kaderblick`. Das Konto wird für Linux, SSH, Administration per `sudo` und SMB verwendet; die beiden Camera-Dienste laufen unter demselben Linux-Konto. Herunterfahren und Neustart darf die API gezielt ohne Kennwort auslösen, andere administrative Befehle erfordern das gesetzte Passwort. Der direkte root-Login ist gesperrt. Die HTTP-API selbst erhält dadurch keine zusätzliche Anmeldung.

## Erster Start

1. Den vorbereiteten Datenträger an einen blauen USB-3-Port des ausgeschalteten Raspberry Pi anschließen.
2. Keine weitere bootfähige SD-Karte einlegen.
3. Kamera, Audio-Hardware, Ethernet und Motorsteuerung anschließen.
4. Raspberry Pi einschalten.

Raspberry Pi 5 unterstützt USB-Massenspeicher als Bootmedium. Das Tool setzt `usb_max_current_enable=1`. Beim ersten Start erweitert Raspberry Pi OS die Root-Partition und installiert anschließend über die vorhandene Ethernet-Internetverbindung Camera API, USB-/Audio-Werkzeuge, SSH und SMB. Dabei kann der Pi selbstständig neu starten. Danach sind individuelle SSH-Hostschlüssel, Konto, Hostname, statisches Ethernet und SMB konfiguriert und die Camera-Dienste gestartet. Ab diesem Zeitpunkt benötigt die Kamera kein Internet mehr.

## Netzwerk

Der Raspberry stellt kein WLAN bereit. WLAN und Bluetooth sind im Image deaktiviert. Ethernet wird direkt durch `systemd-networkd` konfiguriert, ohne Netplan oder NetworkManager.

Ein Gateway ist für Geräte im selben Subnetz nicht erforderlich. Beispiele bei Netzmaske `255.255.255.0`:

- Kamera `192.168.178.47`, Steuergerät `192.168.178.20`: kein Gateway erforderlich.
- Kamera `192.168.178.47`, Zugriff aus einem anderen Subnetz: Routeradresse als Gateway eintragen.

Die Wahl von `.1` oder `.2` als Gateway verändert nicht die WLAN-Reichweite des separaten Hotspots.

## Vorinstallierte Komponenten

- Raspberry Pi OS Bookworm 64-bit, minimales bootfähiges System ohne Desktop
- Python-Venv und Camera API
- V4L2/UVC, Arducam-udev-Regel und USB-Reset-Berechtigung
- `lgpio`, OpenCV, ZeroMQ, FastAPI/Uvicorn
- ALSA/`arecord`
- OpenSSH
- Samba-Freigabe `recordings`
- Offline-Zeitfortschreibung mit `fake-hwclock`
- begrenztes persistentes Journal
- wöchentlicher `fstrim.timer`

Die Aufnahmen liegen unter `/srv/kaderblick/recordings` und werden durch den Share `recordings` bereitgestellt.

## Bewusst nicht verwendete Einstellungen

Folgende frühere Vorschläge werden für das produktive Image nicht gesetzt:

- `arm_freq=1800` und `gpu_freq=250`: keine belastbare Performanceverbesserung für den Pi 5; 1800 MHz läge unter seinem regulären CPU-Takt.
- `over_voltage=-2`: Undervolting ohne Messung kann USB- und Aufnahmestabilität verschlechtern.
- `commit=600`: vergrößert bei Stromausfall das mögliche Datenverlustfenster erheblich.
- synchrones `discard`: wird nicht parallel zu periodischem `fstrim` aktiviert.

`noatime` ist bereits Bestandteil des minimalen Basisimages.

## Diagnose

```bash
ssh <benutzer>@192.168.178.47
sudo systemctl status camera_service kaderblick_app smbd
sudo journalctl -u camera_service -u kaderblick_app --since boot
lsusb -t
v4l2-ctl --list-devices
```

API Kamera 1: `http://192.168.178.47:8000/docs`
SMB Kamera 1: `smb://192.168.178.47/recordings`
