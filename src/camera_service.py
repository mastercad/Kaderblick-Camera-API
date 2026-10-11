import zmq
import time
import threading
import logging
import os
import json
import fcntl
import struct
import glob as _glob
import queue
from datetime import datetime
import subprocess
from v4l2_mjpg_stream import V4L2MJPGStreamer
from find_usb_audio import find_usb_audio_device
from timestamped_audio import TimestampedAudioRecorder


# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


context = zmq.Context()
rep_socket = context.socket(zmq.REP)
rep_socket.bind("tcp://127.0.0.1:5556")
# PUB-Socket für MJPG-Frames (Preview)
pub_socket = context.socket(zmq.PUB)
pub_socket.setsockopt(zmq.SNDHWM, 1)  # max. 1 Frame im Sendepuffer – verhindert Latenz-Aufbau
pub_socket.bind("tcp://127.0.0.1:5555")


# Native MJPEG-fps der Kamera je Auflösung (Hardware-Limit, nicht Software-FPS)
MJPEG_NATIVE_FPS = {
    (3840, 2160): 30,
    (1920, 1080): 60,
    (1280,  720): 60,
    ( 640,  480): 60,
}

# USB-Reset: Arducam B0589 4K HDR (Cypress Semiconductor)
USBDEVFS_RESET = 0x5514       # Linux ioctl _IO('U', 20)
ARDUCAM_VENDOR_ID  = 0x04b4
ARDUCAM_PRODUCT_ID = 0x0822

# Flag: verhindert Watchdog-Eingriff während eines laufenden USB-Resets
_device_reset_in_progress = False

# === Livestream ===
# Die Kamera liefert bereits MJPEG. Die Vorschau reicht diese komprimierten
# Originalframes unverändert durch; auf dem Pi wird weder dekodiert noch erneut
# komprimiert. Das Event dient nur als sichtbarer Betriebszustand für Clients.
_stream_active = threading.Event()

# Diagnoseereignisse werden aus dem zeitkritischen Capture-Thread nur in eine
# Queue gestellt. Ein eigener Thread schreibt sie als JSONL dauerhaft weg.
_health_event_queue = queue.Queue(maxsize=10_000)
_health_log_stop = threading.Event()
_health_log_drop_count = 0
_health_log_event_count = 0
_recording_health_event_count = 0
current_health_log_filename = None
GLOBAL_HEALTH_LOG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "logs", "camera_health.jsonl"
)
HEALTH_LOG_MAX_BYTES = 10 * 1024 * 1024
HEALTH_LOG_BACKUPS = 5

# vcgencmd get_throttled: Bits 0..3 beschreiben den aktuellen Zustand.
POWER_CURRENT_UNDERVOLTAGE = 1 << 0
POWER_CURRENT_FREQ_CAPPED = 1 << 1
POWER_CURRENT_THROTTLED = 1 << 2
POWER_CURRENT_SOFT_TEMP_LIMIT = 1 << 3
POWER_CURRENT_MASK = 0xF
_power_current_flags = 0
_power_event_count = 0


def _rotate_health_log(path):
    if not os.path.exists(path) or os.path.getsize(path) < HEALTH_LOG_MAX_BYTES:
        return
    oldest = f"{path}.{HEALTH_LOG_BACKUPS}"
    if os.path.exists(oldest):
        os.remove(oldest)
    for index in range(HEALTH_LOG_BACKUPS - 1, 0, -1):
        source = f"{path}.{index}"
        if os.path.exists(source):
            os.replace(source, f"{path}.{index + 1}")
    os.replace(path, f"{path}.1")


def _append_health_event(path, event):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _rotate_health_log(path)
    with open(path, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def health_event_callback(event):
    """Queue-only Callback; blockiert weder V4L2-Capture noch den Writer."""
    global _health_log_drop_count, _health_log_event_count, _recording_health_event_count
    queued_event = dict(event)
    recording_log = current_health_log_filename
    if recording_log:
        queued_event["recording_health_log"] = os.path.basename(recording_log)
    try:
        _health_event_queue.put_nowait((queued_event, recording_log))
        _health_log_event_count += 1
        if recording_log:
            _recording_health_event_count += 1
    except queue.Full:
        _health_log_drop_count += 1
        if _health_log_drop_count == 1 or _health_log_drop_count % 100 == 0:
            logging.error(
                "[HEALTH LOG] Queue voll; %d Diagnoseereignis(se) nicht protokolliert",
                _health_log_drop_count,
            )


def _parse_throttled_flags(output: str) -> int:
    value = output.strip().split("=", 1)[-1]
    return int(value, 0)


def _power_issue_names(flags: int) -> list[str]:
    names = []
    if flags & POWER_CURRENT_UNDERVOLTAGE:
        names.append("Unterspannung")
    if flags & POWER_CURRENT_FREQ_CAPPED:
        names.append("CPU-Frequenz begrenzt")
    if flags & POWER_CURRENT_THROTTLED:
        names.append("System gedrosselt")
    if flags & POWER_CURRENT_SOFT_TEMP_LIMIT:
        names.append("Temperaturlimit aktiv")
    return names


def _read_current_power_flags() -> int:
    result = subprocess.run(
        ["vcgencmd", "get_throttled"],
        capture_output=True,
        text=True,
        timeout=2,
        check=True,
    )
    return _parse_throttled_flags(result.stdout) & POWER_CURRENT_MASK


def power_monitor():
    """Protokolliert nur neu auftretende aktuelle Versorgungs-/Drosselprobleme."""
    global _power_current_flags, _power_event_count
    previous_flags = 0
    while not _health_log_stop.is_set():
        try:
            current_flags = _read_current_power_flags()
            _power_current_flags = current_flags
            new_flags = current_flags & ~previous_flags
            if new_flags:
                _power_event_count += 1
                names = _power_issue_names(new_flags)
                health_event_callback({
                    "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                    "monotonic_ns": time.monotonic_ns(),
                    "type": "power_throttling",
                    "severity": "error",
                    "message": "Stromversorgungsproblem: " + ", ".join(names),
                    "recording": bool(streamer.recording),
                    "flags": current_flags,
                    "new_flags": new_flags,
                    "issues": names,
                    "event_count": _power_event_count,
                })
            previous_flags = current_flags
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            logging.debug("Power-Status konnte nicht gelesen werden: %s", error)
        _health_log_stop.wait(2.0)


def health_event_logger():
    while not _health_log_stop.is_set() or not _health_event_queue.empty():
        try:
            event, recording_log = _health_event_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            _append_health_event(GLOBAL_HEALTH_LOG_FILE, event)
            if recording_log:
                _append_health_event(recording_log, event)
        except Exception as error:
            logging.error("[HEALTH LOG] Diagnoseereignis konnte nicht geschrieben werden: %s", error)
        finally:
            _health_event_queue.task_done()

# Persistenz der Auflösung/FPS über Neustarts hinweg
RESOLUTION_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "resolution_config.json")

def _load_resolution_config() -> dict:
    if os.path.exists(RESOLUTION_CONFIG_FILE):
        try:
            with open(RESOLUTION_CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            w, h, fps = cfg["width"], cfg["height"], cfg["fps"]
            camera_fps = cfg.get("camera_fps", MJPEG_NATIVE_FPS.get((w, h), fps))
            return {"width": w, "height": h, "fps": fps, "camera_fps": camera_fps}
        except Exception as e:
            logging.warning(f"resolution_config.json konnte nicht gelesen werden: {e} – nutze Defaults")
    return {"width": 3840, "height": 2160, "fps": 30, "camera_fps": 30}

def _save_resolution_config(width: int, height: int, fps: int, camera_fps: int):
    try:
        with open(RESOLUTION_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"width": width, "height": height, "fps": fps, "camera_fps": camera_fps}, f)
    except Exception as e:
        logging.error(f"resolution_config.json konnte nicht gespeichert werden: {e}")

def _usb_reset_arducam() -> bool:
    """Führt einen USB-Level-Reset des Arducam-Geräts durch.
    Findet das Gerät anhand Vendor/Product-ID in /dev/bus/usb und sendet USBDEVFS_RESET.
    Gibt True zurück wenn erfolgreich, False sonst (z.B. fehlende Berechtigungen)."""
    for bus_path in sorted(_glob.glob('/dev/bus/usb/*/*')):
        try:
            with open(bus_path, 'rb') as f:
                desc = f.read(18)
            if len(desc) < 12:
                continue
            vid = struct.unpack_from('<H', desc, 8)[0]
            pid = struct.unpack_from('<H', desc, 10)[0]
            if vid != ARDUCAM_VENDOR_ID or pid != ARDUCAM_PRODUCT_ID:
                continue
            logging.info(f"[USB-RESET] Arducam gefunden: {bus_path}")
            fd_usb = os.open(bus_path, os.O_RDWR)
            try:
                fcntl.ioctl(fd_usb, USBDEVFS_RESET, 0)
            finally:
                os.close(fd_usb)
            logging.info("[USB-RESET] USB-Reset erfolgreich gesendet.")
            return True
        except PermissionError:
            logging.warning(
                f"[USB-RESET] Kein Zugriff auf {bus_path} – "
                "udev-Regel fehlt oder kaderblick nicht in 'video'-Gruppe."
            )
        except Exception as e:
            logging.debug(f"[USB-RESET] {bus_path}: {e}")
    logging.error("[USB-RESET] Arducam nicht gefunden oder USB-Reset fehlgeschlagen.")
    return False

def _wait_for_video_device(device: str = '/dev/video0', timeout: float = 10.0) -> bool:
    """Wartet bis das Video-Device nach einem USB-Reset wieder verfügbar ist."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(device):
            time.sleep(1.0)  # udev braucht kurz um Permissions zu setzen
            return True
        time.sleep(0.2)
    logging.error(f"[USB-RESET] {device} nach {timeout}s nicht wieder verfügbar.")
    return False

# Original-MJPEG-Vorschau. Drei Bilder pro Sekunde reichen zur Überwachung und
# begrenzen gleichzeitig Netzwerk- und Speicherkopierlast.
PREVIEW_MAX_FPS = 3
_last_preview_time = 0.0

def preview_callback_mjpg(frame_bytes):
    global _last_preview_time
    now = time.monotonic()
    if now - _last_preview_time < 1.0 / PREVIEW_MAX_FPS:
        return
    _last_preview_time = now
    try:
        pub_socket.send(frame_bytes, zmq.NOBLOCK)
    except Exception as e:
        logging.error(f"Preview PUB send error: {e}")


def _start_raw_stream():
    _stream_active.set()
    logging.info("[STREAM] Original-MJPEG-Livestream aktiviert (kein Downscaling).")


def _stop_raw_stream():
    _stream_active.clear()
    logging.info("[STREAM] Original-MJPEG-Livestream deaktiviert.")


def _reset_camera_before_initial_open() -> bool:
    """Bereinigt den instabilen UVC-Zustand nach einem vollständigen Einschalten."""
    logging.info("[STARTUP] Setze Arducam vor dem ersten Streamstart per USB zurück.")
    if not _usb_reset_arducam():
        logging.warning("[STARTUP] USB-Reset nicht möglich; versuche direkten Kamerastart.")
        return False
    if not _wait_for_video_device('/dev/video0'):
        raise RuntimeError("Arducam ist nach dem initialen USB-Reset nicht verfügbar")
    logging.info("[STARTUP] Arducam nach USB-Reset wieder verfügbar.")
    return True


# Streamer-Objekt initialisieren (letzte Auflösung/FPS aus Config wiederherstellen)
_reset_camera_before_initial_open()
_res_cfg = _load_resolution_config()
streamer = V4L2MJPGStreamer(device='/dev/video0', width=_res_cfg["width"], height=_res_cfg["height"], fps=_res_cfg["fps"])
streamer.camera_fps = _res_cfg["camera_fps"]
streamer.set_health_event_callback(health_event_callback)
# Letzte bekannte gute Auflösung – für Watchdog-Fallback bei wiederholten Fehlstarts
_last_known_good_res: dict | None = None
try:
    streamer.open()
    logging.info(f"Streamer opened device /dev/video0 ({_res_cfg['width']}x{_res_cfg['height']}@{_res_cfg['fps']}fps, camera_fps={_res_cfg['camera_fps']})")
    streamer.set_preview_callback(preview_callback_mjpg)
    streamer.start()
    logging.info("Streamer started.")
    _last_known_good_res = {"width": streamer.width, "height": streamer.height, "fps": streamer.fps, "camera_fps": streamer.camera_fps}
except Exception as e:
    logging.error(f"Streamer init failed: {e}")
    raise


# Thread-sicheres Flag für Aufnahme
recording_lock = threading.Lock()

audio_proc = None           # TimestampedAudioRecorder der parallelen Audioaufnahme
audio_error_msg = None      # Fehlermeldung wenn die Audioaufnahme abstirbt
current_video_filename = None
current_audio_filename = None
current_meta_filename = None

logging.info("[camera_service] Service bereit und wartet auf Kommandos...")


def _finalize_recording_session(stop_video=True):
    """Schließt Video, Sidecar und Audio auch nach einem asynchronen Fehler."""
    global audio_proc, current_video_filename, current_audio_filename, current_meta_filename
    global current_health_log_filename

    writer_failed = isinstance(getattr(streamer, "writer_error", None), str)
    if stop_video and (streamer.recording or writer_failed):
        try:
            streamer.stop_recording()
        except Exception as e:
            logging.warning(f"Videoaufnahme konnte nicht sauber beendet werden: {e}")

    if current_meta_filename and os.path.exists(current_meta_filename):
        try:
            with open(current_meta_filename, 'r') as mf:
                meta = json.load(mf)
            meta["ended_at"] = datetime.now().isoformat()
            meta["health_log"] = (
                os.path.basename(current_health_log_filename)
                if current_health_log_filename else None
            )
            meta["health_summary"] = {
                "events": int(getattr(streamer, "health_event_count", 0)),
                "v4l2_sequence_gaps": int(getattr(streamer, "sequence_gaps", 0)),
                "v4l2_sequence_frames_lost": int(getattr(streamer, "sequence_frames_lost", 0)),
                "v4l2_sequence_resets": int(getattr(streamer, "sequence_resets", 0)),
                "v4l2_timestamp_gaps": int(getattr(streamer, "timestamp_gaps", 0)),
                "v4l2_buffer_errors": int(getattr(streamer, "buffer_errors", 0)),
                "invalid_mjpeg_frames": int(getattr(streamer, "invalid_mjpeg_frames", 0)),
                "mjpeg_padding_frames_trimmed": int(
                    getattr(streamer, "mjpeg_padding_frames_trimmed", 0)
                ),
                "mjpeg_padding_bytes_trimmed": int(
                    getattr(streamer, "mjpeg_padding_bytes_trimmed", 0)
                ),
                "writer_queue_drops": int(getattr(streamer, "writer_queue_drops", 0)),
                "writer_error": (
                    streamer.writer_error
                    if isinstance(getattr(streamer, "writer_error", None), str) else None
                ),
                "capture_error": (
                    streamer.capture_error
                    if isinstance(getattr(streamer, "capture_error", None), str) else None
                ),
                "health_log_drops": _health_log_drop_count,
            }
            if writer_failed:
                meta["error"] = streamer.writer_error
            serialized_meta = json.dumps(meta)
            with open(current_meta_filename, 'w') as mf:
                mf.write(serialized_meta)
        except Exception as e:
            logging.warning(f"Konnte JSON-Sidecar nicht aktualisieren: {e}")

    if audio_proc and audio_proc.poll() is None:
        audio_proc.terminate()
        try:
            audio_proc.wait(timeout=2)
            logging.info(
                "Audioaufnahme gestoppt "
                f"(frames={audio_proc.frames_written}, "
                f"timestamps={audio_proc.timestamp_records}, "
                f"xruns={audio_proc.xrun_count}, "
                f"clipped_samples={audio_proc.clipped_samples})."
            )
        except Exception as e:
            logging.warning(f"Audioaufnahme konnte nicht sauber beendet werden: {e}")

    audio_proc = None
    current_video_filename = None
    current_audio_filename = None
    current_meta_filename = None
    current_health_log_filename = None


def _restart_capture_thread():
    """Startet nur den Capture-Thread neu (wenn fd noch gültig ist)."""
    logging.warning("[WATCHDOG] Starte Capture-Thread neu ...")
    streamer.capture_error = None
    streamer.running = True
    new_thread = threading.Thread(target=streamer._capture_loop, daemon=True)
    streamer.thread = new_thread
    new_thread.start()
    logging.warning("[WATCHDOG] Capture-Thread neu gestartet.")


def _full_device_restart():
    """Vollständiger Neustart: USB-Reset → Device warten → öffnen → Thread starten."""
    logging.warning("[WATCHDOG] Vollständiger Device-Neustart (USB-Reset → open → start) ...")
    try:
        streamer.stop()
    except Exception as e:
        logging.warning(f"[WATCHDOG] stop() Fehler (ignoriert): {e}")
    if _usb_reset_arducam():
        logging.info("[WATCHDOG] Warte auf Device-Re-Enumeration ...")
        _wait_for_video_device(streamer.device)
    else:
        logging.warning("[WATCHDOG] USB-Reset nicht möglich – 2s Pause")
        time.sleep(2)
    try:
        streamer.capture_error = None
        streamer.open()
        streamer.set_preview_callback(preview_callback_mjpg)
        streamer.start()
        logging.warning("[WATCHDOG] Device-Neustart erfolgreich.")
    except Exception as e:
        logging.error(f"[WATCHDOG] Device-Neustart open/start fehlgeschlagen: {e}")
        raise


def _maybe_apply_fallback(consecutive_count: int) -> bool:
    """Setzt Streamer-Parameter auf letzte bekannte gute Auflösung zurück (bei wiederholten Fehlstarts).
    Gibt True zurück wenn Fallback angewendet wurde."""
    global _last_known_good_res
    if consecutive_count < 2:
        return False
    if _last_known_good_res is None:
        logging.error("[WATCHDOG] Kein Fallback verfügbar – kein stabiler Zustand bisher bekannt.")
        return False
    if (streamer.width == _last_known_good_res["width"] and
            streamer.height == _last_known_good_res["height"] and
            streamer.fps == _last_known_good_res["fps"]):
        logging.error(
            f"[WATCHDOG] {consecutive_count} Fehlstarts – Auflösung bereits identisch mit letztem "
            f"guten Zustand, kein weiterer Fallback möglich."
        )
        return False
    logging.warning(
        f"[WATCHDOG] {consecutive_count} Fehlstarts – Fallback auf letzte gute Auflösung: "
        f"{_last_known_good_res['width']}x{_last_known_good_res['height']}"
        f"@{_last_known_good_res['fps']}fps (camera_fps={_last_known_good_res['camera_fps']})"
    )
    streamer.width = _last_known_good_res["width"]
    streamer.height = _last_known_good_res["height"]
    streamer.fps = _last_known_good_res["fps"]
    streamer.camera_fps = _last_known_good_res["camera_fps"]
    _save_resolution_config(streamer.width, streamer.height, streamer.fps, streamer.camera_fps)
    return True


def capture_watchdog():
    """Überwacht den Capture-Thread und startet ihn bei Absturz oder anhaltenden Fehlern neu."""
    error_since: float | None = None        # Zeitpunkt seit dem capture_error besteht
    MAX_ERROR_SECONDS = 30                  # Nach 30s Fehler → vollständiger Device-Neustart
    consecutive_failed_restarts = 0         # Zählt aufeinanderfolgende Fehlstarts
    while True:
        time.sleep(3)
        if _device_reset_in_progress:
            logging.debug("[WATCHDOG] Device-Reset durch SET_RESOLUTION läuft – überspringe Check.")
            continue
        if not streamer.thread or not streamer.thread.is_alive():
            logging.error("[WATCHDOG] Capture-Thread ist nicht mehr am Leben!")
            error_since = None
            with recording_lock:
                if streamer.recording or audio_proc is not None:
                    logging.error("[WATCHDOG] Aufnahme war aktiv – Aufnahme wird als FEHLGESCHLAGEN markiert.")
                    _finalize_recording_session()
            _maybe_apply_fallback(consecutive_failed_restarts)
            try:
                _full_device_restart()
            except Exception as e:
                logging.error(f"[WATCHDOG] Neustart fehlgeschlagen: {e}")
            finally:
                consecutive_failed_restarts += 1
        elif streamer.capture_error:
            if error_since is None:
                error_since = time.monotonic()
                logging.warning(f"[WATCHDOG] capture_error seit {time.strftime('%H:%M:%S')}: {streamer.capture_error}")
                with recording_lock:
                    if streamer.recording or audio_proc is not None:
                        _finalize_recording_session()
            elif time.monotonic() - error_since >= MAX_ERROR_SECONDS:
                logging.error(
                    f"[WATCHDOG] Capture-Fehler seit {int(time.monotonic() - error_since)}s – "
                    f"vollständiger Device-Neustart!"
                )
                with recording_lock:
                    if streamer.recording:
                        streamer.recording = False
                _maybe_apply_fallback(consecutive_failed_restarts)
                try:
                    _full_device_restart()
                except Exception as e:
                    logging.error(f"[WATCHDOG] Vollständiger Neustart fehlgeschlagen: {e}")
                finally:
                    consecutive_failed_restarts += 1
                    error_since = None  # Timer in jedem Fall zurücksetzen
            else:
                logging.warning(
                    f"[WATCHDOG] capture_error seit {int(time.monotonic() - error_since)}s – "
                    f"warte auf {MAX_ERROR_SECONDS}s ..."
                )
        else:
            if error_since is not None:
                logging.info("[WATCHDOG] Capture-Fehler behoben.")
            if consecutive_failed_restarts > 0:
                logging.info(f"[WATCHDOG] Kamera läuft wieder stabil – setze Fehlstart-Zähler zurück ({consecutive_failed_restarts}).")
                consecutive_failed_restarts = 0
            error_since = None
            # Aktuelle stabile Auflösung für nächsten Fallback merken
            global _last_known_good_res
            _last_known_good_res = {
                "width": streamer.width, "height": streamer.height,
                "fps": streamer.fps, "camera_fps": streamer.camera_fps,
            }


def audio_monitor():
    """Überwacht den Audiorecorder und loggt Fehler wenn er vorzeitig endet."""
    global audio_proc, audio_error_msg
    while True:
        time.sleep(2)
        if audio_proc is not None:
            rc = audio_proc.poll()
            if rc is not None and not getattr(audio_proc, "stop_requested", False):
                if audio_error_msg is None:  # Nur einmal loggen
                    detail = getattr(audio_proc, "error", None)
                    audio_error_msg = f"Audioaufnahme unerwartet beendet (Exit-Code {rc})"
                    if detail:
                        audio_error_msg += f": {detail}"
                    logging.error(f"[AUDIO MONITOR] {audio_error_msg}")
                    health_event_callback({
                        "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                        "monotonic_ns": time.monotonic_ns(),
                        "type": "audio_capture_stopped",
                        "severity": "error",
                        "message": audio_error_msg,
                        "recording": bool(streamer.recording),
                        "exit_code": rc,
                    })


def handle_commands():
    global audio_proc, audio_error_msg, current_video_filename, current_audio_filename, current_meta_filename
    global current_health_log_filename, _recording_health_event_count
    while True:
        try:
            msg = rep_socket.recv_string()
            if msg == "STATUS":
                logging.debug("ZMQ empfangen: STATUS")
            else:
                logging.info(f"ZMQ empfangen: {msg}")
            if msg == "START":
                with recording_lock:
                    if not streamer.recording:
                        # Capture-Thread muss laufen und gesund sein
                        if not streamer.thread or not streamer.thread.is_alive():
                            logging.error("START abgelehnt: Capture-Thread läuft nicht! Starte neu...")
                            try:
                                _restart_capture_thread()
                                time.sleep(1)  # kurz warten bis Thread startet
                            except Exception as e:
                                logging.error(f"Capture-Thread-Neustart fehlgeschlagen: {e}")
                                rep_socket.send_string("ERROR: Capture-Thread läuft nicht")
                                continue

                        # Vor Aufnahme: alle blockierenden Prozesse beenden (arecord, ggf. Kamera)
                        try:
                            import signal
                            import psutil
                            # Verwaiste arecord-Prozesse älterer Versionen killen
                            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                                if 'arecord' in proc.info['name'] or (proc.info['cmdline'] and any('arecord' in c for c in proc.info['cmdline'])):
                                    try:
                                        os.kill(proc.info['pid'], signal.SIGKILL)
                                    except Exception:
                                        pass
                            # Kamera-Blocker killen 
                            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                                if proc.info['pid'] == os.getpid():
                                    continue
                                if proc.info['cmdline'] and any('/dev/video0' in c for c in proc.info['cmdline']):
                                    try:
                                        os.kill(proc.info['pid'], signal.SIGKILL)
                                    except Exception:
                                        pass
                        except Exception as e:
                            logging.warning(f"Fehler beim Freigeben der Ressourcen: {e}")

                        # Zielverzeichnis und Dateinamen erzeugen
                        recordings_dir = os.path.join(os.path.dirname(__file__), "..", "recordings")
                        os.makedirs(recordings_dir, exist_ok=True)
                        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                        started_at = datetime.now().isoformat()
                        video_filename = os.path.join(recordings_dir, f"aufnahme_{timestamp}.mjpg")
                        audio_filename = os.path.join(recordings_dir, f"aufnahme_{timestamp}.wav")
                        meta_filename = os.path.join(recordings_dir, f"aufnahme_{timestamp}.json")
                        health_log_filename = os.path.join(
                            recordings_dir, f"aufnahme_{timestamp}_health.jsonl"
                        )
                        current_video_filename = video_filename
                        current_audio_filename = audio_filename
                        current_meta_filename = meta_filename
                        _recording_health_event_count = 0
                        current_health_log_filename = health_log_filename
                        audio_error_msg = None

                        # Auch eine fehlerfreie Aufnahme besitzt damit einen
                        # eindeutigen, leeren Ereignislog als Nachweis.
                        try:
                            open(health_log_filename, "a", encoding="utf-8").close()
                        except Exception as e:
                            logging.warning(f"Konnte Health-Log nicht anlegen: {e}")

                        # JSON-Sidecar anlegen
                        try:
                            with open(meta_filename, 'w') as mf:
                                json.dump({
                                    "fps": streamer.fps,
                                    "started_at": started_at,
                                    "health_log": os.path.basename(health_log_filename),
                                }, mf)
                        except Exception as e:
                            logging.warning(f"Konnte JSON-Sidecar nicht anlegen: {e}")

                        logging.info(f"Starte Aufnahme: {video_filename} + {audio_filename}")

                        # Audioaufnahme ZUERST starten (minimiert A/V-Versatz)
                        audio_device = find_usb_audio_device("Huawei Technologies Co., Ltd. EarPods")
                        if audio_device:
                            logging.info(f"Starte Audioaufnahme von {audio_device}")
                            try:
                                audio_proc = TimestampedAudioRecorder(
                                    audio_device,
                                    audio_filename,
                                    health_event_callback=health_event_callback,
                                ).start()
                            except Exception as e:
                                audio_error_msg = f"Audioaufnahme konnte nicht starten: {e}"
                                logging.error(f"[START] {audio_error_msg}")
                                health_event_callback({
                                    "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                                    "monotonic_ns": time.monotonic_ns(),
                                    "type": "audio_start_failed",
                                    "severity": "error",
                                    "message": audio_error_msg,
                                    "recording": True,
                                })
                                audio_proc = None
                            if audio_proc is not None and not audio_proc.wait_for_first_timestamp(2.0):
                                audio_error_msg = "Kein ALSA-Zeitstempel innerhalb von 2 Sekunden"
                                logging.error(f"[START] {audio_error_msg}")
                                health_event_callback({
                                    "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                                    "monotonic_ns": time.monotonic_ns(),
                                    "type": "audio_start_timeout",
                                    "severity": "error",
                                    "message": audio_error_msg,
                                    "recording": True,
                                })
                                audio_proc.terminate()
                                audio_proc.wait(timeout=2)
                                audio_proc = None
                        else:
                            audio_error_msg = "USB-Audio-Gerät nicht gefunden; keine Audioaufnahme"
                            logging.error(audio_error_msg)
                            health_event_callback({
                                "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                                "monotonic_ns": time.monotonic_ns(),
                                "type": "audio_device_missing",
                                "severity": "error",
                                "message": audio_error_msg,
                                "recording": True,
                            })

                        # Videoaufnahme starten
                        streamer.start_recording(video_filename, started_at=started_at)
                        logging.info(f"Aufnahme gestartet. Capture-Thread alive: {streamer.thread.is_alive()}")
                    else:
                        logging.info("Aufnahme läuft bereits.")
                rep_socket.send_string("OK")
                logging.info("Antwort gesendet: OK")

            elif msg == "STOP":
                with recording_lock:
                    if streamer.recording or audio_proc is not None or current_meta_filename is not None:
                        logging.info("Stoppe Aufnahme...")
                        _finalize_recording_session()
                    else:
                        logging.info("Aufnahme war nicht aktiv.")
                rep_socket.send_string("OK")
                logging.info("Antwort gesendet: OK")

            elif msg.startswith("SET_RESOLUTION:"):
                # Format: SET_RESOLUTION:3840x2160:15
                with recording_lock:
                    if streamer.recording:
                        rep_socket.send_string("ERROR:Aufnahme läuft – erst stoppen")
                        continue
                try:
                    parts = msg.split(":")
                    w, h = map(int, parts[1].split("x"))
                    fps_val = int(parts[2])
                except Exception as e:
                    logging.error(f"SET_RESOLUTION Parse-Fehler: {e}")
                    rep_socket.send_string(f"ERROR:{str(e)}")
                    continue
                logging.info(f"SET_RESOLUTION: {w}x{h}@{fps_val}fps")
                camera_fps = MJPEG_NATIVE_FPS.get((w, h), fps_val)
                if w == streamer.width and h == streamer.height:
                    # Nur fps-Änderung: Kamera-Hardware NICHT anfassen.
                    # Die Arducam-Firmware überlebt kein close/reopen im Betrieb.
                    # Frame-Dropping erledigt den Rest in Software.
                    streamer.fps = fps_val
                    streamer.camera_fps = camera_fps
                    _save_resolution_config(w, h, fps_val, camera_fps)
                    logging.info(f"Nur fps geändert (kein Kamera-Neustart): {w}x{h}@{fps_val}fps")
                    rep_socket.send_string(f"OK:{w}x{h}:{fps_val}")
                    continue
                # Auflösungswechsel: USB-Level-Reset für saubere Firmware-Initialisierung
                global _device_reset_in_progress
                _device_reset_in_progress = True
                try:
                    streamer.stop()
                    logging.info(
                        f"[SET_RESOLUTION] USB-Reset für Auflösungswechsel "
                        f"{streamer.width}x{streamer.height} → {w}x{h}"
                    )
                    if _usb_reset_arducam():
                        logging.info("[SET_RESOLUTION] Warte auf Device-Re-Enumeration ...")
                        if not _wait_for_video_device(streamer.device):
                            logging.error("[SET_RESOLUTION] Device kam nach USB-Reset nicht zurück!")
                            rep_socket.send_string("ERROR:Device nach USB-Reset nicht verfügbar")
                            continue
                    else:
                        logging.warning("[SET_RESOLUTION] USB-Reset nicht möglich – 2s Pause")
                        time.sleep(2)
                    streamer.width = w
                    streamer.height = h
                    streamer.fps = fps_val
                    streamer.camera_fps = camera_fps
                    streamer.open()
                    streamer.set_preview_callback(preview_callback_mjpg)
                    streamer.start()
                    _save_resolution_config(w, h, fps_val, camera_fps)
                    logging.info(f"[SET_RESOLUTION] Streamer läuft bei {w}x{h}@{fps_val}fps")
                    rep_socket.send_string(f"OK:{w}x{h}:{fps_val}")
                except Exception as e:
                    logging.error(f"SET_RESOLUTION Fehler: {e}")
                    rep_socket.send_string(f"ERROR:{str(e)}")
                finally:
                    _device_reset_in_progress = False

            elif msg == "STATUS":
                with recording_lock:
                    capture_thread_alive = streamer.thread is not None and streamer.thread.is_alive()
                    frames_captured = streamer.frames_captured
                    frames_written = streamer.frames_written
                    capture_error = streamer.capture_error
                    last_frame_age = None
                    if streamer.last_frame_time is not None:
                        last_frame_age = round(time.monotonic() - streamer.last_frame_time, 1)

                    # Echter Recording-Status: Flag UND Thread lebt UND kein Fehler
                    actually_recording = (
                        streamer.recording
                        and capture_thread_alive
                        and capture_error is None
                    )

                    # Dateigröße prüfen (nur wenn Aufnahme läuft)
                    video_file_bytes = None
                    if current_video_filename and os.path.exists(current_video_filename):
                        try:
                            video_file_bytes = os.path.getsize(current_video_filename)
                        except Exception:
                            pass

                    audio_running = audio_proc is not None and audio_proc.poll() is None
                    audio_exit_code = audio_proc.poll() if audio_proc is not None else None
                    audio_progress_age = None
                    if audio_proc is not None:
                        last_audio_progress = getattr(audio_proc, "last_progress_monotonic", None)
                        if isinstance(last_audio_progress, (int, float)):
                            audio_progress_age = round(
                                max(0.0, time.monotonic() - last_audio_progress), 1
                            )
                    audio_stalled = (
                        audio_running
                        and audio_progress_age is not None
                        and audio_progress_age > 2.0
                    )
                    if audio_stalled:
                        audio_running = False

                    health_issues = []
                    health_status = "ok"
                    if not capture_thread_alive:
                        health_issues.append("Capture-Thread läuft nicht")
                        health_status = "error"
                    if capture_error:
                        health_issues.append(str(capture_error))
                        health_status = "error"
                    if getattr(streamer, "writer_error", None):
                        health_issues.append(str(streamer.writer_error))
                        health_status = "error"
                    if audio_error_msg:
                        health_issues.append(str(audio_error_msg))
                        health_status = "error"
                    if audio_stalled:
                        health_issues.append(
                            f"ALSA liefert seit {audio_progress_age:.1f}s keine Audiodaten"
                        )
                        health_status = "error"
                    if last_frame_age is not None and last_frame_age > 2.0:
                        health_issues.append(f"Letztes Kameraframe ist {last_frame_age:.1f}s alt")
                        health_status = "error"
                    if _power_current_flags:
                        health_issues.append(
                            "Stromversorgung: " + ", ".join(_power_issue_names(_power_current_flags))
                        )
                        health_status = "error"
                    warning_counters = {
                        "V4L2-Sequenzsprünge": int(getattr(streamer, "sequence_gaps", 0)),
                        "V4L2-Pufferfehler": int(getattr(streamer, "buffer_errors", 0)),
                        "ungültige MJPEG-Frames": int(getattr(streamer, "invalid_mjpeg_frames", 0)),
                        "Writer-Queue-Drops": int(getattr(streamer, "writer_queue_drops", 0)),
                    }
                    for label, count in warning_counters.items():
                        if count:
                            health_issues.append(f"{label}: {count}")
                            if health_status == "ok":
                                health_status = "warning"

                    status = {
                        "recording": actually_recording,
                        "recording_flag": streamer.recording,
                        "capture_thread_alive": capture_thread_alive,
                        "frames_captured": frames_captured,
                        "frames_written": frames_written,
                        "v4l2_sequence_gaps": int(getattr(streamer, "sequence_gaps", 0)),
                        "v4l2_sequence_frames_lost": int(getattr(streamer, "sequence_frames_lost", 0)),
                        "v4l2_sequence_resets": int(getattr(streamer, "sequence_resets", 0)),
                        "v4l2_timestamp_gaps": int(getattr(streamer, "timestamp_gaps", 0)),
                        "v4l2_buffer_errors": int(getattr(streamer, "buffer_errors", 0)),
                        "invalid_mjpeg_frames": int(getattr(streamer, "invalid_mjpeg_frames", 0)),
                        "mjpeg_padding_frames_trimmed": int(
                            getattr(streamer, "mjpeg_padding_frames_trimmed", 0)
                        ),
                        "mjpeg_padding_bytes_trimmed": int(
                            getattr(streamer, "mjpeg_padding_bytes_trimmed", 0)
                        ),
                        "v4l2_allocated_buffers": int(getattr(streamer, "allocated_buffers", 0)),
                        "max_buffer_hold_ms": round(float(getattr(streamer, "max_buffer_hold_ms", 0.0)), 3),
                        "max_write_ms": round(float(getattr(streamer, "max_write_ms", 0.0)), 3),
                        "writer_queue_max_depth": int(getattr(streamer, "writer_queue_max_depth", 0)),
                        "writer_queue_drops": int(getattr(streamer, "writer_queue_drops", 0)),
                        "health_event_count": int(getattr(streamer, "health_event_count", 0)),
                        "health_log_event_count": int(_health_log_event_count),
                        "recording_health_event_count": int(_recording_health_event_count),
                        "health_log_drops": int(_health_log_drop_count),
                        "health_log_file": (
                            os.path.basename(current_health_log_filename)
                            if current_health_log_filename else None
                        ),
                        "health_status": health_status,
                        "health_issues": health_issues,
                        "writer_error": (
                            streamer.writer_error
                            if isinstance(getattr(streamer, "writer_error", None), str)
                            else None
                        ),
                        "last_frame_age_s": last_frame_age,
                        "capture_error": capture_error,
                        "audio_available": audio_running,
                        "audio_exit_code": audio_exit_code,
                        "audio_error": audio_error_msg,
                        "audio_progress_age_s": audio_progress_age,
                        "audio_xruns": int(getattr(audio_proc, "xrun_count", 0)) if audio_proc else 0,
                        "audio_recovery_restarts": int(
                            getattr(audio_proc, "recovery_restart_count", 0)
                        ) if audio_proc else 0,
                        "audio_writer_queue_depth": int(
                            getattr(audio_proc, "writer_queue_depth", 0)
                        ) if audio_proc else 0,
                        "audio_writer_queue_max_depth": int(
                            getattr(audio_proc, "writer_queue_max_depth", 0)
                        ) if audio_proc else 0,
                        "power_current_flags": int(_power_current_flags),
                        "power_undervoltage_now": bool(
                            _power_current_flags & POWER_CURRENT_UNDERVOLTAGE
                        ),
                        "power_throttled_now": bool(
                            _power_current_flags & POWER_CURRENT_THROTTLED
                        ),
                        "power_event_count": int(_power_event_count),
                        "video_file_bytes": video_file_bytes,
                        "width": streamer.width,
                        "height": streamer.height,
                        "fps": streamer.fps,
                        "stream_active": _stream_active.is_set(),
                    }
                rep_socket.send_string(json.dumps(status))
                logging.debug(f"Antwort gesendet: STATUS {status}")
            elif msg == "STREAM_START":
                _start_raw_stream()
                rep_socket.send_string("OK")
                logging.info("Antwort gesendet: OK (STREAM_START)")

            elif msg == "STREAM_STOP":
                _stop_raw_stream()
                rep_socket.send_string("OK")
                logging.info("Antwort gesendet: OK (STREAM_STOP)")

            else:
                logging.warning(f"Unbekanntes Kommando: {msg}")
                rep_socket.send_string("UNKNOWN")
        except Exception as e:
            logging.error(f"[camera_service] Fehler: {e}")
            try:
                rep_socket.send_string("ERROR")
                logging.info("Antwort gesendet: ERROR")
            except Exception as send_err:
                logging.error(f"Fehler beim Senden der Fehlerantwort: {send_err}")


def main():
    health_logger_thread = threading.Thread(
        target=health_event_logger, name="camera-health-log", daemon=True
    )
    health_logger_thread.start()
    logging.info("Health-Event-Logger gestartet: %s", GLOBAL_HEALTH_LOG_FILE)

    cmd_thread = threading.Thread(target=handle_commands, daemon=True)
    cmd_thread.start()
    logging.info("Kommando-Thread gestartet.")

    watchdog_thread = threading.Thread(target=capture_watchdog, daemon=True)
    watchdog_thread.start()
    logging.info("Watchdog-Thread gestartet.")

    audio_monitor_thread = threading.Thread(target=audio_monitor, daemon=True)
    audio_monitor_thread.start()
    logging.info("Audio-Monitor-Thread gestartet.")

    power_monitor_thread = threading.Thread(
        target=power_monitor, name="power-health-monitor", daemon=True
    )
    power_monitor_thread.start()
    logging.info("Power-Monitor-Thread gestartet.")

    try:
        while True:
            time.sleep(5)
            alive = streamer.thread.is_alive() if streamer.thread else False
            logging.debug(
                f"Streamer recording: {streamer.recording} | "
                f"capture_thread_alive: {alive} | "
                f"frames_captured: {streamer.frames_captured} | "
                f"frames_written: {streamer.frames_written} | "
                f"capture_error: {streamer.capture_error}"
            )
    except KeyboardInterrupt:
        logging.info("Beende Service...")
        with recording_lock:
            if streamer.recording or audio_proc is not None:
                logging.info("Stoppe laufende Aufnahme beim Beenden.")
                _finalize_recording_session()
        streamer.stop()
        _health_log_stop.set()
        health_logger_thread.join(timeout=3)
        rep_socket.close()
        context.term()
        logging.info("Service sauber beendet.")

if __name__ == "__main__":
    main()
