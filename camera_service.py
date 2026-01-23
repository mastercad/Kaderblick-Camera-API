import zmq
import time
import threading
import logging
import os
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
pub_socket.bind("tcp://127.0.0.1:5555")


# Preview-Callback: sendet MJPG-Bytes direkt über PUB
def preview_callback_mjpg(frame_bytes):
    try:
        pub_socket.send(frame_bytes, zmq.NOBLOCK)
    except Exception as e:
        logging.error(f"Preview PUB send error: {e}")


# Streamer-Objekt initialisieren 
streamer = V4L2MJPGStreamer(device='/dev/video0', width=3840, height=2160, fps=30)
try:
    streamer.open()
    logging.info("Streamer opened device /dev/video0 (3840x2160@30)")
    streamer.set_preview_callback(preview_callback_mjpg)
    streamer.start()
    logging.info("Streamer started.")
except Exception as e:
    logging.error(f"Streamer init failed: {e}")
    raise


# Thread-sicheres Flag für Aufnahme
recording_lock = threading.Lock()


audio_proc = None  # Für parallele Audioaufnahme
logging.info("[camera_service_full] Service bereit und wartet auf Kommandos...")


def handle_commands():
    global audio_proc
    while True:
        try:
            msg = rep_socket.recv_string()
            logging.info(f"ZMQ empfangen: {msg}")
            if msg == "START":
                with recording_lock:
                    if not streamer.recording:
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
                        recordings_dir = os.path.join(os.path.dirname(__file__), "recordings")
                        os.makedirs(recordings_dir, exist_ok=True)
                        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                        video_filename = os.path.join(recordings_dir, f"aufnahme_{timestamp}.mjpg")
                        audio_filename = os.path.join(recordings_dir, f"aufnahme_{timestamp}.wav")
                        logging.info(f"Starte Aufnahme: {video_filename} + {audio_filename}")
                        streamer.start_recording(video_filename)
                        # Audioaufnahme starten
                        audio_device = find_usb_audio_device("Huawei Technologies Co., Ltd. EarPods")
                        if audio_device:
                            logging.info(f"Starte Audioaufnahme von {audio_device}")
                            audio_proc = subprocess.Popen([
                                "arecord", "-D", audio_device, "-f", "cd", "-t", "wav", "-r", "48000", "-c", "1", audio_filename
                            ])
                        else:
                            logging.error("USB-Audio-Device nicht gefunden! Keine Audioaufnahme.")
                    else:
                        logging.info("Aufnahme läuft bereits.")
                rep_socket.send_string("OK")
                logging.info("Antwort gesendet: OK")
            elif msg == "STOP":
                with recording_lock:
                    if streamer.recording:
                        logging.info("Stoppe Aufnahme...")
                        streamer.stop_recording()
                        # Audioaufnahme stoppen
                        if audio_proc and audio_proc.poll() is None:
                            audio_proc.terminate()
                            try:
                                audio_proc.wait(timeout=2)
                                logging.info("Audioaufnahme gestoppt.")
                            except Exception:
                                logging.warning("Audioaufnahme konnte nicht sauber beendet werden.")
                            audio_proc = None
                    else:
                        logging.info("Aufnahme war nicht aktiv.")
                rep_socket.send_string("OK")
                logging.info("Antwort gesendet: OK")
            elif msg == "STATUS":
                # Status-Objekt als JSON zurückgeben
                import json
                status = {
                    "recording": streamer.recording,
                    "audio_available": audio_proc is not None and audio_proc.poll() is None
                }
                rep_socket.send_string(json.dumps(status))
                logging.info(f"Antwort gesendet: STATUS {status}")
            else:
                logging.warning(f"Unbekanntes Kommando: {msg}")
                rep_socket.send_string("UNKNOWN")
        except Exception as e:
            logging.error(f"[camera_service_full] Fehler: {e}")
            try:
                rep_socket.send_string("ERROR")
                logging.info("Antwort gesendet: ERROR")
            except Exception as send_err:
                logging.error(f"Fehler beim Senden der Fehlerantwort: {send_err}")


def main():
    cmd_thread = threading.Thread(target=handle_commands, daemon=True)
    cmd_thread.start()
    logging.info("Kommando-Thread gestartet.")
    try:
        while True:
            time.sleep(1)
            # Logge Status zyklisch
            logging.debug(f"Streamer recording: {streamer.recording}")
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
