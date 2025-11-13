import cv2
import zmq
import threading
import queue
import time
import os
from datetime import datetime

# Konfiguration
FRAME_WIDTH = 3840
FRAME_HEIGHT = 2160
JPEG_QUALITY = 95
OUTPUT_DIR = "recordings"
io_queue = queue.Queue(maxsize=100)
WATCHDOG_TIMEOUT = 5 # Sekunden

# ZeroMQ Setup
context = zmq.Context()
pub_socket = context.socket(zmq.PUB)
pub_socket.bind("tcp://*:5555")
req_socket = context.socket(zmq.REP)
req_socket.bind("tcp://*:5556")

# Aufnahmeflag
recording = False
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Disk-Writer Thread
def disk_writer():
    while True:
        item = io_queue.get()
        if item is None:
            break
        filename, jpg_bytes = item
        with open(filename, 'wb') as f:
            f.write(jpg_bytes)
threading.Thread(target=disk_writer, daemon=True).start()

# Kamera Setup
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

print("Camera service started.")
last_frame_time = time.time()

while True:
    ret, frame = cap.read()
    if not ret:
        print("Frame read failed")
        continue
    else:
        print(f"Frame captured: {frame.shape}")

    # Encode JPEG
    _, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    jpg_bytes = jpg.tobytes()

    # PUB Socket senden (Preview)
    pub_socket.send(jpg_bytes)
    last_frame_time = time.time()

    # Aufnahme auf Disk
    if recording:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = os.path.join(OUTPUT_DIR, f"frame_{timestamp}.jpg")
        try:
            io_queue.put_nowait((filename, jpg_bytes))
        except queue.Full:
            pass

    # Steueranfragen
    try:
        if req_socket.poll(1):
            msg = req_socket.recv_string()
            if msg == "START":
                recording = True
                req_socket.send_string("OK")
            elif msg == "STOP":
                recording = False
                req_socket.send_string("OK")
            else:
                req_socket.send_string("UNKNOWN")
    except zmq.ZMQError:
        continue

    # Watchdog Check
    if time.time() - last_frame_time > WATCHDOG_TIMEOUT:
        print("Watchdog: Frame timeout detected, restarting capture")
        cap.release()
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        last_frame_time = time.time()

cap.release()
