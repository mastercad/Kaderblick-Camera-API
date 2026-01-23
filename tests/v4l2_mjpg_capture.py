import threading
import time
import numpy as np
from pynv4l2 import Device
import cv2

class V4L2MJPGCapture:
    def __init__(self, device='/dev/video0', width=3840, height=2160, fps=30):
        self.device_path = device
        self.width = width
        self.height = height
        self.fps = fps
        self.dev = None
        self.running = False
        self.recording = False
        self.record_file = None
        self.lock = threading.Lock()
        self.preview_callback = None
        self.thread = None

    def open(self):
        self.dev = Device(self.device_path)
        self.dev.set_format(self.width, self.height, fourcc='MJPG')
        self.dev.set_fps(self.fps)
        print(f"[V4L2MJPGCapture] Opened {self.device_path} {self.width}x{self.height}@{self.fps} MJPG")

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
        if self.dev:
            self.dev.close()
            self.dev = None

    def start_recording(self, filename):
        with self.lock:
            self.record_file = open(filename, 'wb')
            self.recording = True

    def stop_recording(self):
        with self.lock:
            self.recording = False
            if self.record_file:
                self.record_file.close()
                self.record_file = None

    def set_preview_callback(self, callback):
        self.preview_callback = callback

    def _capture_loop(self):
        while self.running:
            frame = self.dev.read()
            if frame is None:
                time.sleep(0.01)
                continue
            with self.lock:
                if self.recording and self.record_file:
                    self.record_file.write(frame)
            if self.preview_callback:
                # MJPG zu RGB für Preview dekodieren
                arr = np.frombuffer(frame, dtype=np.uint8)
                img = cv2.imdecode(arr, 1)
                if img is not None:
                    self.preview_callback(img)
                else:
                    print("[V4L2MJPGCapture] cv2.imdecode failed!")
            time.sleep(0.001)
