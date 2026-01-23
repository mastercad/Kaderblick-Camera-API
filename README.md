# Kaderblick Camera API

Fernsteuerung für die Arducam B0589 4K HDR Kamera mit Servo/Stepper-Motor-Steuerung auf Raspberry Pi 5.

## 📋 Übersicht

Dieses Projekt bietet eine FastAPI-basierte Lösung zur Fernsteuerung einer USB-Kamera (Arducam B0589 4K HDR) mit:

- **MJPEG Live-Stream** über ZMQ (Zero Message Queue)
- **Video-Aufnahme** mit Audio (WAV) und automatischer Konvertierung zu MP4
- **Kamera-Steuerung** (Pan/Tilt via Servo MG90S + Stepper ULN2003)
- **V4L2 Camera Controls** (Contrast, Saturation, Gain, Sharpness, Exposure)
- **System-Monitoring** (CPU, RAM, Disk, Temperatur)
- **Remote-Steuerung** (Shutdown, Reboot)

## 🏗️ Architektur

Das System besteht aus zwei Services:

### 1. **Camera Service** (`camera_service.py`)
- Greift direkt auf `/dev/video0` zu (V4L2)
- Captured MJPEG-Frames @ 30 FPS in 4K (3840x2160)
- Streamt Frames via **ZMQ PUB** Socket (`tcp://127.0.0.1:5555`)
- Nimmt Aufnahme-Befehle via **ZMQ REP** Socket entgegen (`tcp://127.0.0.1:5556`)
- Verwaltet Audio-Aufnahme (falls USB-Audio verfügbar)
- Speichert Aufnahmen in Session-Ordnern (`recordings/session_YYYYMMDD_HHMMSS/`)

### 2. **FastAPI App** (`fastapi_app.py`)
- REST API für externe Steuerung
- Empfängt MJPEG-Stream vom Camera Service via **ZMQ SUB**
- Steuert GPIO-Hardware (Servo + Stepper) via `lgpio`
- Bietet Endpunkte für Kamera-Controls (v4l2-ctl)
- System-Management (Info, Shutdown, Reboot)

```
┌──────────────────┐          ┌──────────────────┐
│  Camera Service  │  ZMQ PUB │   FastAPI App    │
│  (camera_service │◄─────────┤ (fastapi_app.py) │
│       .py)       │  ZMQ REQ │                  │
│                  │◄─────────┤   Port 8000      │
└────────┬─────────┘          └─────────┬────────┘
         │                              │
         │ /dev/video0                  │ GPIO (lgpio)
         ▼                              ▼
   Arducam B0589              Servo + Stepper Motor
```

## 📦 Hardware

- **Raspberry Pi 5** (mit lgpio)
- **Arducam B0589 4K HDR** USB-Kamera
- **MG90S Servo** (GPIO 18, PWM)
- **28BYJ-48 Stepper Motor** mit ULN2003 Driver (GPIO 17, 27, 20, 21)
- Optional: **USB-Audio-Device** für Ton-Aufnahme

## 🚀 Installation

Siehe [docs/INSTALLATION.md](docs/INSTALLATION.md) für detaillierte Installationsanweisungen:

```bash
# System-Pakete
sudo apt-get install -y portaudio19-dev python3-pyaudio ffmpeg python3-rpi-lgpio

# Python-Umgebung
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements.txt

# Services einrichten
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now camera_service
sudo systemctl enable --now kaderblick_app
```

## 🎮 Verwendung

### Services Starten/Stoppen

```bash
# Status prüfen
sudo systemctl status camera_service
sudo systemctl status kaderblick_app

# Logs anzeigen
sudo journalctl -u camera_service -f
sudo journalctl -u kaderblick_app -f

# Service neu starten
sudo systemctl restart camera_service
sudo systemctl restart kaderblick_app
```

### Manueller Start (Entwicklung)

```bash
# Terminal 1: Camera Service
python camera_service.py

# Terminal 2: FastAPI App
uvicorn fastapi_app:app --host 0.0.0.0 --port 8000
```

## 📡 API Endpunkte

### Live-Preview & Aufnahme

| Methode | Endpunkt | Beschreibung |
|---------|----------|--------------|
| `GET` | `/preview` | MJPEG Live-Stream |
| `POST` | `/start_record` | Aufnahme starten |
| `POST` | `/stop_record` | Aufnahme stoppen |
| `GET` | `/status` | Vollständiger Status (Aufnahme, Stream, Hardware) |

### Hardware-Steuerung

| Methode | Endpunkt | Beschreibung |
|---------|----------|--------------|
| `POST` | `/servo` | Servo relativ bewegen (Grad) |
| `POST` | `/servo/absolute` | Servo absolut positionieren (0-180°) |
| `GET` | `/servo` | Aktuelle Servo-Position |
| `POST` | `/stepper` | Stepper relativ bewegen (Schritte) |
| `POST` | `/stepper/absolute` | Stepper absolut positionieren |
| `GET` | `/stepper` | Aktuelle Stepper-Position |
| `GET` | `/camera-position-status` | Beide Positionen (Servo + Stepper) |

### Kamera-Controls (V4L2)

| Methode | Endpunkt | Beschreibung |
|---------|----------|--------------|
| `GET` | `/camera/controls` | Alle verfügbaren Controls mit Limits & aktuellen Werten |
| `POST` | `/camera/controls` | Einzelnen Control setzen |
| `POST` | `/camera/controls/reset` | Control(s) auf Default zurücksetzen |

**Unterstützte Controls:**
- `contrast` (0-4, default: 2)
- `saturation` (0-4, default: 2)
- `gain` (1-16, default: 1)
- `sharpness` (0-6, default: 3)
- `auto_exposure` (0-3, default: 0 = Auto Mode)
- `exposure_time_absolute` (10-660, default: 10, nur wenn auto_exposure ≠ 0)

**Beispiele:**
```bash
# Alle Controls abrufen
curl http://192.168.178.47:8000/camera/controls

# Kontrast auf Maximum setzen
curl -X POST http://192.168.178.47:8000/camera/controls \
  -H "Content-Type: application/json" \
  -d '{"control": "contrast", "value": 4}'

# Gain erhöhen
curl -X POST http://192.168.178.47:8000/camera/controls \
  -H "Content-Type: application/json" \
  -d '{"control": "gain", "value": 8}'

# Einzelnen Control zurücksetzen
curl -X POST http://192.168.178.47:8000/camera/controls/reset \
  -H "Content-Type: application/json" \
  -d '{"control": "contrast"}'

# Alle Controls auf Default zurücksetzen
curl -X POST http://192.168.178.47:8000/camera/controls/reset
```

### System-Management

| Methode | Endpunkt | Beschreibung |
|---------|----------|--------------|
| `GET` | `/system/info` | CPU, RAM, Disk, Temperatur, Aufnahme-Dateien |
| `POST` | `/system/shutdown` | System herunterfahren |
| `POST` | `/system/reboot` | System neu starten |

## 📖 Interaktive API-Dokumentation

FastAPI generiert automatisch interaktive Dokumentation:

- **Swagger UI:** http://192.168.178.47:8000/docs
- **ReDoc:** http://192.168.178.47:8000/redoc

## 📝 Weitere Dokumentation

- **[docs/INSTALLATION.md](docs/INSTALLATION.md)** - Detaillierte Installations- und Setup-Anweisungen
- **[docs/COMMANDS.md](docs/COMMANDS.md)** - Command-Line-Beispiele (curl, v4l2-ctl, ffmpeg)
- **[docs/AUDIO_VIDEO_SETUP.md](docs/AUDIO_VIDEO_SETUP.md)** - Audio/Video-Aufnahme-Details

## 🎥 Aufnahme-Workflow

1. **Aufnahme starten:**
   ```bash
   curl -X POST http://192.168.178.47:8000/start_record
   ```

2. **Live-Stream ansehen:**
   ```
   http://192.168.178.47:8000/preview
   ```

3. **Kamera ausrichten während Aufnahme:**
   ```bash
   # Servo bewegen (Y-Achse)
   curl -X POST http://192.168.178.47:8000/servo/absolute \
     -H "Content-Type: application/json" -d '{"angle": 120}'
   
   # Stepper bewegen (X-Achse)
   curl -X POST http://192.168.178.47:8000/stepper \
     -H "Content-Type: application/json" -d '{"steps": 100}'
   ```

4. **Bildqualität anpassen während Aufnahme:**
   ```bash
   curl -X POST http://192.168.178.47:8000/camera/controls \
     -H "Content-Type: application/json" \
     -d '{"control": "sharpness", "value": 5}'
   ```

5. **Aufnahme stoppen:**
   ```bash
   curl -X POST http://192.168.178.47:8000/stop_record
   ```

6. **Ergebnis:**
   - Ordner: `recordings/session_YYYYMMDD_HHMMSS/`
   - Video mit Audio: `video_with_audio.mp4`
   - Einzelne Frames: `frames/*.jpg` (für KI-Auswertung)

## 🔧 Konfiguration

### Kamera-Device ändern

In `fastapi_app.py`:
```python
CAMERA_DEVICE = "/dev/video0"  # Ändern falls andere Kamera
```

### Speicherplatz-Limit

In `fastapi_app.py`:
```python
DISK_SPACE_LIMIT_GB = 30  # Aufnahme stoppt automatisch bei < 30GB frei
```

### GPIO-Pins

In `fastapi_app.py`:
```python
SERVO_PIN = 18                    # PWM für Servo
STEPPER_PINS = [17, 27, 20, 21]  # ULN2003 IN1-IN4
```

## 🐛 Troubleshooting

### Kamera nicht gefunden
```bash
# Alle verfügbaren V4L2-Devices anzeigen
v4l2-ctl --list-devices

# Kamera-Infos prüfen
v4l2-ctl --device /dev/video0 --all
```

### ZMQ-Verbindungsfehler
```bash
# Prüfen ob Camera Service läuft
sudo systemctl status camera_service

# Ports prüfen
ss -tulpn | grep -E '5555|5556'
```

### GPIO-Fehler
```bash
# lgpio-Berechtigungen prüfen
ls -l /dev/gpiochip0

# User zur gpio-Gruppe hinzufügen
sudo usermod -a -G gpio $USER
```

### Camera Controls werden nicht geladen
```bash
# Manuell testen
v4l2-ctl --device /dev/video0 --list-ctrls

# Logs prüfen
sudo journalctl -u kaderblick_app -f
```

## 📄 Lizenz

Dieses Projekt ist für den internen Gebrauch des Fußballvereins Wurgwitz entwickelt.

## 👥 Kontakt

Bei Fragen oder Problemen bitte ein Issue erstellen oder die Projekt-Dokumentation konsultieren.
