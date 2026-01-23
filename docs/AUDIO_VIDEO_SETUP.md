# Audio + Video Aufnahme Setup

## Installation der neuen Abhängigkeiten

```bash
# Erst system-dependencies für pyaudio installieren
sudo apt-get update
sudo apt-get install -y portaudio19-dev python3-pyaudio ffmpeg

# Dann Python-Pakete installieren
pip install -r requirements.txt
```

## Funktionsweise

### Aufnahme-Struktur

Wenn du `START` aufrufst, wird automatisch ein neuer Session-Ordner erstellt:

```
recordings/
  └── session_20251113_143022/
      ├── frames/              # JPEG Frames für KI-Auswertung
      │   ├── frame_20251113_143022_123456.jpg
      │   ├── frame_20251113_143022_123789.jpg
      │   └── ...
      ├── audio/               # Audio-Aufnahme
      │   └── audio.wav
      ├── video.mp4            # Video ohne Audio (Zwischendatei)
      └── video_with_audio.mp4 # Fertiges Video mit Audio (zum Hochladen)
```

### Was wird aufgenommen?

**Parallel werden erstellt:**
1. **JPEG Frames** (für KI-Auswertung) - einzelne Bilder mit Timestamps
2. **Video mit Audio** - fertiges MP4-Video zum direkten Hochladen

### Audio-Gerät

Das USB-Mikrofon (EarPods) wird automatisch erkannt. Der Service sucht beim Start nach:
- Geräten mit "EarPods" im Namen
- Oder generell "USB Audio" Geräten

Falls kein Audio-Gerät gefunden wird, läuft der Service trotzdem weiter, nur ohne Audio-Aufnahme.

## Nutzung

### Service starten

```bash
python camera_service.py
```

Ausgabe beim Start:
```
Audio device found: EarPods (Index: 2)
Camera service started.
```

### Aufnahme starten

```bash
# Via API
curl http://localhost:8000/start_record

# Oder direkt mit ZMQ (für Tests)
```

Der Service erstellt automatisch einen neuen Session-Ordner und startet:
- JPEG Frame-Speicherung
- Video-Aufnahme
- Audio-Aufnahme

### Aufnahme stoppen

```bash
curl http://localhost:8000/stop_record
```

Beim Stoppen:
1. Audio-Aufnahme wird beendet und als WAV gespeichert
2. Video-Datei wird geschlossen
3. Audio und Video werden automatisch mit ffmpeg kombiniert zu `video_with_audio.mp4`

## Konfiguration

In `camera_service.py` kannst du folgende Parameter anpassen:

```python
# Video-Qualität
FRAME_WIDTH = 3840
FRAME_HEIGHT = 2160
JPEG_QUALITY = 95
FPS = 30

# Audio-Qualität
AUDIO_CHANNELS = 1      # Mono
AUDIO_RATE = 48000      # 48kHz
AUDIO_FORMAT = pyaudio.paInt16  # 16-bit
```

## Troubleshooting

### Audio-Gerät nicht gefunden

Prüfe verfügbare Geräte:
```bash
arecord -l
```

Teste Audio-Aufnahme:
```bash
arecord -D plughw:2,0 -f S16_LE -r 48000 -c 1 test.wav
```

### Video-Kombinierung schlägt fehl

Wenn ffmpeg das Video und Audio nicht kombinieren kann, hast du trotzdem:
- `video.mp4` (Video ohne Audio)
- `audio/audio.wav` (Audio separat)

Du kannst sie manuell kombinieren:
```bash
cd recordings/session_XXXXXXXX_XXXXXX/
ffmpeg -i video.mp4 -i audio/audio.wav -c:v copy -c:a aac video_final.mp4
```

## Für die KI-Auswertung

Die JPEG Frames im `frames/` Ordner haben alle Timestamps im Dateinamen:
```
frame_20251113_143022_123456.jpg
```

Format: `frame_YYYYMMDD_HHMMSS_microseconds.jpg`

Das ermöglicht zeitgenaue Zuordnung für die KI-Analyse.
