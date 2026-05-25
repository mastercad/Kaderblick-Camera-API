import os
import threading
import time
from threading import Lock

import zmq

from config import DISK_SPACE_LIMIT_GB

# ==============================
# ZMQ-Setup
# ==============================
_context = zmq.Context()

req_socket = _context.socket(zmq.REQ)
req_socket.connect("tcp://127.0.0.1:5556")
req_lock = Lock()

_sub_socket = _context.socket(zmq.SUB)
_sub_socket.setsockopt(zmq.CONFLATE, 1)   # immer nur neuesten Frame, kein Pufferaufbau
_sub_socket.connect("tcp://127.0.0.1:5555")
_sub_socket.setsockopt_string(zmq.SUBSCRIBE, "")
_sub_socket.RCVTIMEO = 100  # ms – damit recv() nicht ewig blockiert

# ==============================
# Geteilter Zustand
# ==============================
latest_frame: bytes | None = None
new_frame_event = threading.Event()   # signalisiert sofort, wenn ein neues Frame anliegt
stop_event = threading.Event()
disk_space_error = threading.Event()   # gesetzt, wenn Speicherplatz-Limit unterschritten


# ==============================
# Hintergrund-Threads
# ==============================

def _frame_listener() -> None:
    """Empfängt MJPEG-Frames vom ZMQ-SUB-Socket und legt sie in latest_frame ab."""
    global latest_frame
    while not stop_event.is_set():
        try:
            frame = _sub_socket.recv()
            latest_frame = frame
            new_frame_event.set()
        except zmq.Again:
            pass  # RCVTIMEO abgelaufen – kein Frame, einfach weiter


def _disk_space_monitor() -> None:
    """Überwacht den freien Speicherplatz; stoppt die Aufnahme bei Unterschreitung des Limits."""
    output_dir = os.path.join(os.path.dirname(__file__), "..", "recordings")
    while not stop_event.is_set():
        try:
            path = output_dir if os.path.exists(output_dir) else "/"
            st = os.statvfs(path)
            free_gb = (st.f_bavail * st.f_frsize) / (1024 ** 3)
            if free_gb < DISK_SPACE_LIMIT_GB:
                disk_space_error.set()
                try:
                    with req_lock:
                        req_socket.send_string("STOP")
                        if req_socket.poll(1000):
                            req_socket.recv_string()
                except Exception:
                    pass
            else:
                disk_space_error.clear()
        except Exception:
            pass
        time.sleep(5)


threading.Thread(target=_frame_listener, daemon=True).start()
threading.Thread(target=_disk_space_monitor, daemon=True).start()
