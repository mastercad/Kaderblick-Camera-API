import v4l2
import os
import fcntl
import mmap
import threading
import select
import ctypes
import time
import json
import numpy as np
import cv2

class V4L2MJPGStreamer:
    def __init__(self, device='/dev/video0', width=3840, height=2160, fps=30, buffers=4):
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.camera_fps = fps  # tatsächliche Kamera-fps (kann > self.fps sein bei Frame-Dropping)
        self.buffers = buffers
        self.fd = None
        self.mmaps = []
        self.running = False
        self.recording = False
        self.record_file = None
        self.preview_callback = None
        self.thread = None
        self.avi_writer = None
        self.avi_lock = threading.Lock()
        # Health tracking
        self.frames_captured = 0       # Frames vom Kamera-Gerät empfangen
        self.frames_written = 0        # Frames in Datei geschrieben
        self.last_frame_time = None    # Zeitpunkt (monotonic) des letzten Frames
        self.capture_error = None      # Fehlermeldung wenn Capture-Loop abstürzt
        self.recording_start_time = None  # Zeitpunkt des Aufnahme-Starts
        # A/V-Sync: letzter geschriebener Frame (Kernel-Timestamp + Bytes für Duplikation)
        self._last_written_frame_ts = None
        self._prev_frame_bytes = None

    def open(self):
        self.fd = os.open(self.device, os.O_RDWR | os.O_NONBLOCK)
        fmt = v4l2.v4l2_format()
        fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        fmt.fmt.pix.width = self.width
        fmt.fmt.pix.height = self.height
        fmt.fmt.pix.pixelformat = v4l2.V4L2_PIX_FMT_MJPEG
        fmt.fmt.pix.field = v4l2.V4L2_FIELD_NONE
        fcntl.ioctl(self.fd, v4l2.VIDIOC_S_FMT, fmt)
        # Framerate per VIDIOC_S_PARM setzen (ermöglicht z.B. 4K@15fps)
        parm = v4l2.v4l2_streamparm()
        parm.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        parm.parm.capture.timeperframe.numerator = 1
        parm.parm.capture.timeperframe.denominator = self.camera_fps
        fcntl.ioctl(self.fd, v4l2.VIDIOC_S_PARM, parm)
        req = v4l2.v4l2_requestbuffers()
        req.count = self.buffers
        req.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        req.memory = v4l2.V4L2_MEMORY_MMAP
        fcntl.ioctl(self.fd, v4l2.VIDIOC_REQBUFS, req)
        self.mmaps = []
        for i in range(self.buffers):
            buf = v4l2.v4l2_buffer()
            buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
            buf.memory = v4l2.V4L2_MEMORY_MMAP
            buf.index = i
            fcntl.ioctl(self.fd, v4l2.VIDIOC_QUERYBUF, buf)
            mm = mmap.mmap(self.fd, buf.length, mmap.MAP_SHARED, mmap.PROT_READ, offset=buf.m.offset)
            self.mmaps.append((mm, buf.length))
            fcntl.ioctl(self.fd, v4l2.VIDIOC_QBUF, buf)
        buf_type = ctypes.c_int(v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE)
        fcntl.ioctl(self.fd, v4l2.VIDIOC_STREAMON, buf_type)

    def set_preview_callback(self, callback):
        self.preview_callback = callback

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
        if self.fd is not None:
            buf_type = ctypes.c_int(v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE)
            try:
                fcntl.ioctl(self.fd, v4l2.VIDIOC_STREAMOFF, buf_type)
            except Exception:
                pass
            for mm, _ in self.mmaps:
                mm.close()
            self.mmaps = []
            # Kernel-seitige DMA-Buffer freigeben (sauberes V4L2-Teardown)
            try:
                req = v4l2.v4l2_requestbuffers()
                req.count = 0
                req.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
                req.memory = v4l2.V4L2_MEMORY_MMAP
                fcntl.ioctl(self.fd, v4l2.VIDIOC_REQBUFS, req)
            except Exception:
                pass
            os.close(self.fd)
            self.fd = None

    def is_capture_healthy(self, max_frame_age_s=5.0):
        """Gibt True zurück, wenn der Capture-Thread läuft und kürzlich Frames liefert."""
        if not self.thread or not self.thread.is_alive():
            return False
        if self.last_frame_time is None:
            # Thread gerade gestartet, noch kein Frame – OK wenn <10s
            return True
        return (time.monotonic() - self.last_frame_time) < max_frame_age_s

    def _inject_com_marker(self, frame: bytes, fps: int, started_at: str) -> bytes:
        """Injiziert einen JPEG-COM-Marker (FF FE) mit fps und started_at nach dem SOI (FF D8)."""
        comment = json.dumps({"fps": fps, "started_at": started_at}).encode('utf-8')
        length = len(comment) + 2  # Längenfeld selbst (2 Bytes) + Nutzdaten
        com_segment = b'\xff\xfe' + length.to_bytes(2, 'big') + comment
        return frame[:2] + com_segment + frame[2:]

    def start_recording(self, filename, started_at=None):
        # Health-Counter zurücksetzen
        self.frames_written = 0
        self.capture_error = None
        self.recording_start_time = time.monotonic()
        self._recording_started_at = started_at or ''
        self._first_frame = True
        # Frame-Dropping: jeden N-ten Frame schreiben um Ziel-fps zu erreichen
        self._record_skip = max(1, round(self.camera_fps / self.fps)) if self.fps > 0 else 1
        self._record_counter = 0
        # A/V-Sync: Zustand zurücksetzen
        self._last_written_frame_ts = None
        self._prev_frame_bytes = None
        # AVI-Container, wenn .avi gewünscht
        if filename.lower().endswith('.avi'):
            import cv2
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            with self.avi_lock:
                self.avi_writer = cv2.VideoWriter(
                    filename, fourcc, self.fps, (self.width, self.height)
                )
            self.record_file = None
        else:
            self.record_file = open(filename, 'wb')
            with self.avi_lock:
                self.avi_writer = None
        self.recording = True

    def stop_recording(self):
        self.recording = False
        if self.record_file:
            self.record_file.close()
            self.record_file = None
        with self.avi_lock:
            if self.avi_writer is not None:
                try:
                    self.avi_writer.release()
                except Exception as e:
                    print(f"AVI writer release error: {e}")
                self.avi_writer = None

    def _capture_loop(self):
        consecutive_timeouts = 0
        MAX_CONSECUTIVE_TIMEOUTS = 10  # 10s ohne Frame → Fehler
        while self.running:
            r, _, _ = select.select([self.fd], [], [], 1)
            if not r:
                consecutive_timeouts += 1
                if consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS:
                    msg = (f"Kein Frame vom Kamera-Gerät seit {consecutive_timeouts}s – "
                           f"Hardware-Problem? (select.select Timeout)")
                    print(f"[CAPTURE ERROR] {msg}")
                    self.capture_error = msg
                    if self.recording:
                        self.recording = False
                    # Weiterlaufen um Recovery zu ermöglichen, aber Error ist gesetzt
                continue
            consecutive_timeouts = 0
            buf = v4l2.v4l2_buffer()
            buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
            buf.memory = v4l2.V4L2_MEMORY_MMAP
            try:
                fcntl.ioctl(self.fd, v4l2.VIDIOC_DQBUF, buf)
            except OSError as e:
                if e.errno == 11:
                    continue
                msg = f"DQBUF ioctl fehlgeschlagen: {e}"
                print(f"[CAPTURE ERROR] {msg}")
                self.capture_error = msg
                self.recording = False
                self.running = False
                break
            mm, length = self.mmaps[buf.index]
            frame = mm[:buf.bytesused]
            # Frame-Health-Tracking
            self.frames_captured += 1
            self.last_frame_time = time.monotonic()
            self.capture_error = None  # Frame empfangen → kein Fehler
            if self.recording:
                self._record_counter = (self._record_counter + 1) % self._record_skip
                if self._record_counter == 0:
                    # Kernel-Timestamp dieses Frames
                    frame_ts = buf.timestamp.secs + buf.timestamp.usecs / 1_000_000
                    if self.record_file:
                        # Erster Frame: COM-Marker mit fps + started_at injizieren
                        if self._first_frame:
                            self._first_frame = False
                            frame = self._inject_com_marker(frame, self.fps, self._recording_started_at)
                        # A/V-Sync: fehlende Frames durch Duplikate auffüllen
                        if self._last_written_frame_ts is not None and self._prev_frame_bytes is not None:
                            elapsed = frame_ts - self._last_written_frame_ts
                            n_dup = max(0, min(round(elapsed * self.fps) - 1, 15))
                            if n_dup > 0:
                                print(f"[SYNC] {n_dup} Frame(s) gedroppt – fülle mit Duplikaten auf (elapsed={elapsed:.3f}s)")
                                for _ in range(n_dup):
                                    try:
                                        self.record_file.write(self._prev_frame_bytes)
                                        self.frames_written += 1
                                    except OSError as e:
                                        msg = f"Schreibfehler beim Duplikat-Frame: {e}"
                                        print(f"[CAPTURE ERROR] {msg}")
                                        self.capture_error = msg
                                        self.recording = False
                                        break
                        try:
                            self.record_file.write(frame)
                            self.frames_written += 1
                            self._last_written_frame_ts = frame_ts
                            self._prev_frame_bytes = frame
                        except OSError as e:
                            msg = f"Schreibfehler in Aufnahmedatei: {e}"
                            print(f"[CAPTURE ERROR] {msg}")
                            self.capture_error = msg
                            self.recording = False
                    else:
                        with self.avi_lock:
                            if self.avi_writer is not None:
                                # MJPG-Frame als BGR-Image decodieren und in AVI schreiben
                                arr = np.frombuffer(frame, dtype=np.uint8)
                                img = cv2.imdecode(arr, 1)
                                if img is not None:
                                    self.avi_writer.write(img)
                                    self.frames_written += 1
            if self.preview_callback is not None and len(frame) > 0:
                self.preview_callback(frame)
            buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
            buf.memory = v4l2.V4L2_MEMORY_MMAP
            try:
                fcntl.ioctl(self.fd, v4l2.VIDIOC_QBUF, buf)
            except OSError as e:
                msg = f"QBUF ioctl fehlgeschlagen: {e}"
                print(f"[CAPTURE ERROR] {msg}")
                self.capture_error = msg
                self.recording = False
                self.running = False
                break
