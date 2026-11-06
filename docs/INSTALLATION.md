# Installation der Kamera

> Der belegte Stand der laufenden Untersuchung zu V4L2-/MJPEG-Frameverlusten
> steht in [CAPTURE_DIAGNOSIS.md](CAPTURE_DIAGNOSIS.md). Vor weiteren Änderungen
> dortige Messwerte, Ausschlüsse und offene Tests berücksichtigen.

Die produktiven Raspberry Pi 5 werden mit dem **Kaderblick Kamera Setup** vorbereitet. Am späteren Einsatzort ist keine Internetverbindung erforderlich.

## Voraussetzungen

- Raspberry Pi 5
- offizielle Raspberry Pi RTC Battery (`SC1163`, wiederaufladbare ML2020), wenn die Uhr ohne Internet und bei getrennter Stromversorgung korrekt weiterlaufen soll
- externe USB-3-Festplatte/SSD oder alternativ eine SD-Karte
- Arducam B0589 (`04b4:0822`)
- ausreichend dimensioniertes Netzteil; bei gleichzeitig angeschlossener USB-Kamera und USB-Festplatte ist die stabile Stromversorgung besonders wichtig
- Internetzugang auf dem Windows-, Linux- oder macOS-Rechner während der Vorbereitung
- Internetzugang über Ethernet beim einmaligen ersten Start des Raspberry Pi

## Datenträger vorbereiten

1. Portable Version oder Installer ab Version 0.3.0 aus dem neuesten GitHub
   Release starten. Ältere Versionen enthalten nicht den aktuellen
   ALSA-/Zeitstempel-Aufnahmepfad.
2. Kamera 1 oder Kamera 2 auswählen.
3. Konto, Passwort, IPv4-Adresse und Netzmaske eintragen.
4. Den für den Einsatz vorgesehenen Gateway eintragen (`192.168.178.1` im Heimnetz oder `192.168.178.2` am Kamera-Hotspot).
5. Die externe USB-Festplatte/SSD oder SD-Karte auswählen.
6. Die vollständige Löschung des exakt angezeigten Datenträgers bestätigen.

Das Tool lädt Raspberry Pi OS Lite direkt von Raspberry Pi und kontrolliert dessen offizielle SHA-256-Prüfsumme. Die Camera-API-Komponenten sind bereits im Setup-Tool enthalten und werden zusammen mit dem Betriebssystem und der individuellen Konfiguration auf den Datenträger geschrieben. GitHub stellt kein vorgefertigtes Kameraimage bereit.

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

Raspberry Pi 5 unterstützt USB-Massenspeicher als Bootmedium. Das Tool setzt `usb_max_current_enable=1` und aktiviert mit `dtparam=rtc_bbat_vchg=3000000` die 3,0-V-Ladung der offiziellen ML2020-RTC-Batterie. Es installiert außerdem das in Debian 13 separat ausgelieferte RTC-Werkzeug `hwclock` und schreibt die verifizierte Internetzeit bei der Ersteinrichtung in die Hardware-Uhr. Vor dem einmaligen Init ist die gewählte statische Kamera-IP bereits aktiv; der Internetzugang wird vorübergehend um eine DHCP-Route ergänzt, damit Camera API, USB-/Audio-Werkzeuge, SSH und SMB installiert werden können. Nach erfolgreicher Einrichtung schreibt das Init die endgültige statische Netzwerkkonfiguration mit dem gewählten Gateway, entfernt seinen eigenen Boot-Eintrag und startet genau einmal neu. Bei späteren Starts werden weder Init noch Updates erneut ausgeführt. Kamera und API funktionieren ohne Internet; eine erreichbare Internetverbindung wird nur für den automatischen NTP-Zeitabgleich genutzt.

Bei jedem späteren Boot übernimmt der Kernel die Zeit aus der Pi-5-Hardware-Uhr. `fake-hwclock` hält zusätzlich einen Offline-Rückfall vor und setzt die Systemzeit nur dann, wenn dessen gespeicherter Wert neuer ist. Ist beim Boot Internet erreichbar, gleicht ein auf 15 Sekunden begrenzter Einmaldienst die Uhr ab und schreibt das Ergebnis sofort in die echte RTC und den Rückfall. Unabhängig davon bleibt `systemd-timesyncd` aktiv: Ist zunächst kein NTP-Server erreichbar, versucht der Dienst den Abgleich später erneut. Nach erfolgreicher Synchronisierung hält der Kernel die Hardware-Uhr im ungefähr elfminütigen Rhythmus aktuell. Die Kamera-Dienste warten nicht auf NTP und laufen daher auch vollständig offline. TRIM läuft nur im Boot-Schritt. Automatische APT-, TRIM-, Logrotate-, Man-DB-, Dateisystemprüfungs- und temporäre Aufräumtimer sind deaktiviert; `cron` wird nicht gestartet.

Der Boot-Schritt begrenzt außerdem die maximale CPU-Frequenz auf 1,5 GHz. Auf
beiden produktiven Pis erzeugte ein Vierkern-Lasttest bei 2,4 GHz reproduzierbar
Kernel-Unterspannung; gleichzeitig verlor der UVC-Treiber Teile des
MJPEG-Datenstroms. Derselbe Test blieb mit 1,5 GHz auf beiden Geräten ohne
Unterspannung, Sequenzverlust oder ungültiges MJPEG-Frame. Der
`ondemand`-Governor bleibt aktiv, die Begrenzung verhindert nur die nicht stabil
versorgten Boost-Spitzen. Sie ersetzt kein ausreichend dimensioniertes Netzteil
und keine einwandfreien Stromkabel.

## Verhalten während einer Aufnahme

Es werden bei Aufnahmebeginn keine Systemdienste dynamisch beendet und danach wieder gestartet. Die nicht benötigten periodischen Arbeiten sind dauerhaft deaktiviert und können deshalb gar nicht erst in eine Aufnahme hineinlaufen. Dadurch entstehen keine zusätzlichen Start-/Stopp-Übergänge im Aufnahmebetrieb.

Aktiv bleiben die für den Betrieb notwendigen Komponenten:

- `camera_service`: Kamera, Aufnahme, Watchdog und Vorschaubilder
- `kaderblick_app`: HTTP-API einschließlich Statusprüfung und optionalem Stream
- NetworkManager, Netplan und die grundlegenden Systemdienste für Ethernet
- `smbd` für die Aufnahmefreigabe
- `sshd` für Administration
- Journal, Geräteverwaltung und D-Bus für Fehlerdiagnose und Hardwarebetrieb

API-Zugriffe werden nicht als einzelne Access-Log-Zeilen auf den Datenträger geschrieben. Fehler sowie Start, Stopp und Zustandsänderungen bleiben im begrenzten Journal erhalten. Der Swap-Dienst richtet beim Boot lediglich den vorhandenen Swap-Speicher ein und bleibt nicht als arbeitender Hintergrundprozess aktiv; der Swap wird als Notreserve gegen einen Speicherabbruch beibehalten.

## Netzwerk

Der Raspberry stellt kein WLAN bereit. WLAN und Bluetooth sind im Image deaktiviert. Ethernet wird wie auf der stabil laufenden PoC-Installation über Netplan mit NetworkManager konfiguriert. Während der einmaligen Einrichtung erhält die Verbindung zusätzlich zur festen Kamera-IP eine DHCP-Konfiguration für den Internetzugang. Danach bleibt ausschließlich die konfigurierte statische Netplan-Verbindung aktiv.

### Netplan-Referenzkonfigurationen

Die Konfiguration wird auf der Kamera als `/etc/netplan/01-static-ip.yaml` mit Dateimodus `0600` abgelegt.

Kamera 1 im Heimnetz:

```yaml
network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      dhcp4: false
      addresses:
        - 192.168.178.47/24
      nameservers:
        addresses: [8.8.8.8, 8.8.4.4]
      routes:
        - to: 0.0.0.0/0
          via: 192.168.178.1
```

Kamera 1 am Kamera-Hotspot:

```yaml
network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      dhcp4: false
      addresses:
        - 192.168.178.47/24
      nameservers:
        addresses: [8.8.8.8, 8.8.4.4]
      routes:
        - to: 0.0.0.0/0
          via: 192.168.178.2
```

Kamera 2 im Heimnetz:

```yaml
network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      dhcp4: false
      addresses:
        - 192.168.178.48/24
      nameservers:
        addresses: [8.8.8.8, 8.8.4.4]
      routes:
        - to: 0.0.0.0/0
          via: 192.168.178.1
```

Kamera 2 am Kamera-Hotspot:

```yaml
network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      dhcp4: false
      addresses:
        - 192.168.178.48/24
      nameservers:
        addresses: [8.8.8.8, 8.8.4.4]
      routes:
        - to: 0.0.0.0/0
          via: 192.168.178.2
```

## Vorinstallierte Komponenten

- Raspberry Pi OS Trixie 64-bit, minimales bootfähiges System ohne Desktop
- Python-Venv und Camera API
- V4L2/UVC, Arducam-udev-Regel und USB-Reset-Berechtigung
- `lgpio`, OpenCV, ZeroMQ, FastAPI/Uvicorn
- direkte ALSA-Aufnahme mit monotonen Zeitankern, 3-facher Pegelanhebung und
  Dual-Mono-Ausgabe
- OpenSSH
- Samba-Freigabe `recordings`
- batteriegepufferte Pi-5-RTC, automatischer NTP-Abgleich und Offline-Rückfall mit `fake-hwclock`
- begrenztes persistentes Journal
- schneller Zeitabgleich und TRIM beim Boot; spätere NTP-Wiederholungen blockieren die Kamera-Dienste nicht

Die Aufnahmen liegen unter `/srv/kaderblick/recordings` und werden durch den Share `recordings` bereitgestellt.

## Bewusst nicht verwendete Einstellungen

Folgende frühere Vorschläge werden für das produktive Image nicht gesetzt:

- `arm_freq=1800` und `gpu_freq=250`: Die Boot-Takte werden nicht fest
  überschrieben. Stattdessen setzt der gemessene Boot-Preflight ausschließlich
  die CPU-Obergrenze auf 1,5 GHz; der dynamische `ondemand`-Governor bleibt aktiv.
- `over_voltage=-2`: Undervolting ohne Messung kann USB- und Aufnahmestabilität verschlechtern.
- `commit=600`: vergrößert bei Stromausfall das mögliche Datenverlustfenster erheblich.
- synchrones `discard`: zusätzliche synchrone SSD-Arbeit während einer Aufnahme wird vermieden.

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
