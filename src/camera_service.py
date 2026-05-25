import zmq
import time
import threading
import logging
import os
import json
import fcntl
import struct
import glob as _glob
from datetime import datetime
import subprocess
from v4l2_mjpg_stream import V4L2MJPGStreamer
from find_usb_audio import find_usb_audio_device


# Logging setup
logging.basicConfig(
    level=logging.DEBUG,
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

# Preview-Callback: sendet MJPG-Bytes direkt über PUB (max 3fps für Preview)
PREVIEW_MAX_FPS = 3
_last_preview_time = 0.0

def preview_callback_mjpg(frame_bytes):
    global _last_preview_time
    now = time.monotonic()
    if now - _last_preview_time < 1.0 / PREVIEW_MAX_FPS:
        return  # Frame für Preview überspringen – Recording unberührt
    _last_preview_time = now
    try:
        pub_socket.send(frame_bytes, zmq.NOBLOCK)
    except Exception as e:
        logging.error(f"Preview PUB send error: {e}")


# Streamer-Objekt initialisieren (letzte Auflösung/FPS aus Config wiederherstellen)
_res_cfg = _load_resolution_config()
streamer = V4L2MJPGStreamer(device='/dev/video0', width=_res_cfg["width"], height=_res_cfg["height"], fps=_res_cfg["fps"])
streamer.camera_fps = _res_cfg["camera_fps"]
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

audio_proc = None           # Für parallele Audioaufnahme
audio_error_msg = None      # Fehlermeldung wenn arecord abstirbt
current_video_filename = None
current_audio_filename = None
current_meta_filename = None

logging.info("[camera_service] Service bereit und wartet auf Kommandos...")


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
                if streamer.recording:
                    logging.error("[WATCHDOG] Aufnahme war aktiv – Aufnahme wird als FEHLGESCHLAGEN markiert.")
                    streamer.recording = False
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
    """Überwacht den arecord-Prozess und loggt Fehler wenn er vorzeitig endet."""
    global audio_proc, audio_error_msg
    while True:
        time.sleep(2)
        if audio_proc is not None:
            rc = audio_proc.poll()
            if rc is not None:
                if audio_error_msg is None:  # Nur einmal loggen
                    audio_error_msg = f"arecord unerwartet beendet (Exit-Code {rc})"
                    logging.error(f"[AUDIO MONITOR] {audio_error_msg}")


def handle_commands():
    global audio_proc, audio_error_msg, current_video_filename, current_audio_filename, current_meta_filename
    while True:
        try:
            msg = rep_socket.recv_string()
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
                            # arecord-Prozesse killen
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
                        current_video_filename = video_filename
                        current_audio_filename = audio_filename
                        current_meta_filename = meta_filename
                        audio_error_msg = None

                        # JSON-Sidecar anlegen
                        try:
                            with open(meta_filename, 'w') as mf:
                                json.dump({"fps": streamer.fps, "started_at": started_at}, mf)
                        except Exception as e:
                            logging.warning(f"Konnte JSON-Sidecar nicht anlegen: {e}")

                        logging.info(f"Starte Aufnahme: {video_filename} + {audio_filename}")

                        # Audioaufnahme ZUERST starten (minimiert A/V-Versatz)
                        audio_device = find_usb_audio_device("Huawei Technologies Co., Ltd. EarPods")
                        if audio_device:
                            logging.info(f"Starte Audioaufnahme von {audio_device}")
                            audio_proc = subprocess.Popen([
                                "arecord", "-D", audio_device, "-f", "cd", "-t", "wav", "-r", "48000", "-c", "1", audio_filename
                            ])
                            # Kurz warten damit arecord wirklich aufzeichnet bevor Video startet
                            time.sleep(0.2)
                            # Prüfen ob arecord sofort gecrasht ist
                            if audio_proc.poll() is not None:
                                audio_error_msg = f"arecord sofort beendet (Exit-Code {audio_proc.poll()})"
                                logging.error(f"[START] {audio_error_msg}")
                                audio_proc = None
                        else:
                            logging.error("USB-Audio-Device nicht gefunden! Keine Audioaufnahme.")

                        # Videoaufnahme starten
                        streamer.start_recording(video_filename, started_at=started_at)
                        logging.info(f"Aufnahme gestartet. Capture-Thread alive: {streamer.thread.is_alive()}")
                    else:
                        logging.info("Aufnahme läuft bereits.")
                rep_socket.send_string("OK")
                logging.info("Antwort gesendet: OK")

            elif msg == "STOP":
                with recording_lock:
                    if streamer.recording:
                        logging.info("Stoppe Aufnahme...")
                        streamer.stop_recording()
                        # JSON-Sidecar mit ended_at ergänzen
                        if current_meta_filename and os.path.exists(current_meta_filename):
                            try:
                                with open(current_meta_filename, 'r') as mf:
                                    meta = json.load(mf)
                                meta["ended_at"] = datetime.now().isoformat()
                                with open(current_meta_filename, 'w') as mf:
                                    json.dump(meta, mf)
                            except Exception as e:
                                logging.warning(f"Konnte JSON-Sidecar nicht aktualisieren: {e}")
                        # Audioaufnahme stoppen
                        if audio_proc and audio_proc.poll() is None:
                            audio_proc.terminate()
                            try:
                                audio_proc.wait(timeout=2)
                                logging.info("Audioaufnahme gestoppt.")
                            except Exception:
                                logging.warning("Audioaufnahme konnte nicht sauber beendet werden.")
                        audio_proc = None
                        current_video_filename = None
                        current_audio_filename = None
                        current_meta_filename = None
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

                    status = {
                        "recording": actually_recording,
                        "recording_flag": streamer.recording,
                        "capture_thread_alive": capture_thread_alive,
                        "frames_captured": frames_captured,
                        "frames_written": frames_written,
                        "last_frame_age_s": last_frame_age,
                        "capture_error": capture_error,
                        "audio_available": audio_running,
                        "audio_exit_code": audio_exit_code,
                        "audio_error": audio_error_msg,
                        "video_file_bytes": video_file_bytes,
                        "width": streamer.width,
                        "height": streamer.height,
                        "fps": streamer.fps,
                    }
                rep_socket.send_string(json.dumps(status))
                logging.info(f"Antwort gesendet: STATUS {status}")
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
    cmd_thread = threading.Thread(target=handle_commands, daemon=True)
    cmd_thread.start()
    logging.info("Kommando-Thread gestartet.")

    watchdog_thread = threading.Thread(target=capture_watchdog, daemon=True)
    watchdog_thread.start()
    logging.info("Watchdog-Thread gestartet.")

    audio_monitor_thread = threading.Thread(target=audio_monitor, daemon=True)
    audio_monitor_thread.start()
    logging.info("Audio-Monitor-Thread gestartet.")

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
            if streamer.recording:
                logging.info("Stoppe laufende Aufnahme beim Beenden.")
                streamer.stop_recording()
        streamer.stop()
        rep_socket.close()
        context.term()
        logging.info("Service sauber beendet.")

if __name__ == "__main__":
    main()
