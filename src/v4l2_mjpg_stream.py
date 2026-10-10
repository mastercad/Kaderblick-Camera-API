import v4l2
import os
import fcntl
import mmap
import threading
import select
import ctypes
import time
import json
import queue
import struct
from datetime import datetime
import numpy as np
import cv2


_WRITER_STOP = object()
_V4L2_BUF_FLAG_ERROR = 0x0040
_FRAME_METADATA_MAGIC = b"KBFM"
_FRAME_METADATA_VERSION = 1
# magic, version, flags, header size, frame index, V4L2 sequence,
# V4L2 timestamp ns, userspace receive monotonic ns, V4L2 buffer flags
_FRAME_METADATA_STRUCT = struct.Struct(">4sBBHQIQQI")


class V4L2MJPGStreamer:
    def __init__(self, device='/dev/video0', width=3840, height=2160, fps=30, buffers=12,
                 writer_queue_size=128):
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.camera_fps = fps  # tatsächliche Kamera-fps (kann > self.fps sein bei Frame-Dropping)
        self.buffers = buffers
        self.allocated_buffers = 0
        self.writer_queue_size = writer_queue_size
        self.fd = None
        self.mmaps = []
        self.running = False
        self.recording = False
        self.record_file = None
        self.preview_callback = None
        self.health_event_callback = None
        self.thread = None
        self.avi_writer = None
        self.avi_lock = threading.Lock()
        self._recording_state_lock = threading.Lock()
        self._writer_queue = None
        self._writer_thread = None
        self._next_frame_index = 0
        # Health tracking
        self.frames_captured = 0       # Frames vom Kamera-Gerät empfangen
        self.frames_written = 0        # Frames in Datei geschrieben
        self.last_frame_time = None    # Zeitpunkt (monotonic) des letzten Frames
        self.capture_error = None      # Fehlermeldung wenn Capture-Loop abstürzt
        self.recording_start_time = None  # Zeitpunkt des Aufnahme-Starts
        # V4L2 diagnostics: distinguish device/USB loss from userspace stalls.
        self.last_sequence = None
        self.sequence_gaps = 0
        self.sequence_frames_lost = 0
        self.sequence_resets = 0
        self.timestamp_gaps = 0
        self.buffer_errors = 0
        self.invalid_mjpeg_frames = 0
        self.max_buffer_hold_ms = 0.0
        self.max_write_ms = 0.0
        self.writer_queue_max_depth = 0
        self.writer_queue_drops = 0
        self.writer_error = None
        self.health_event_count = 0
        self._last_capture_ts = None
        self._last_buffer_hold_ms = 0.0

    def open(self):
        # Ein neu geöffneter UVC-Stream beginnt wieder bei einer eigenen
        # Sequenz-/Zeitbasis. Werte des vorherigen Streams dürfen deshalb nicht
        # als Frameverlust über einen USB-Reset hinweg interpretiert werden.
        self.last_sequence = None
        self._last_capture_ts = None
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
        self.allocated_buffers = int(req.count)
        if self.allocated_buffers < 2:
            raise RuntimeError(
                f"V4L2 stellt nur {self.allocated_buffers} Capture-Puffer bereit"
            )
        self.mmaps = []
        for i in range(self.allocated_buffers):
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

    def set_health_event_callback(self, callback):
        """Registriert einen nicht blockierenden Empfänger für Diagnoseereignisse."""
        self.health_event_callback = callback

    def _emit_health_event(self, event_type, message, severity="warning", **details):
        """Meldet eine Auffälligkeit, ohne den Capture-Pfad bei Fehlern zu stoppen."""
        self.health_event_count += 1
        callback = self.health_event_callback
        if callback is None:
            return
        event = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "monotonic_ns": time.monotonic_ns(),
            "type": event_type,
            "severity": severity,
            "message": message,
            "recording": bool(self.recording),
            **details,
        }
        try:
            callback(event)
        except Exception as error:
            print(f"[HEALTH LOG ERROR] Diagnoseereignis konnte nicht gemeldet werden: {error}", flush=True)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self):
        if self._writer_thread is not None or self.record_file is not None or self.avi_writer is not None:
            self.stop_recording()
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
            self.allocated_buffers = 0

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
        return frame[:2] + self._build_com_segment(fps, started_at) + frame[2:]

    def _build_com_segment(self, fps: int, started_at: str) -> bytes:
        comment = json.dumps({"fps": fps, "started_at": started_at}).encode('utf-8')
        length = len(comment) + 2  # Längenfeld selbst (2 Bytes) + Nutzdaten
        return b'\xff\xfe' + length.to_bytes(2, 'big') + comment

    def _build_frame_metadata_segment(self, frame_index, sequence, timestamp_ns,
                                      receive_monotonic_ns, buffer_flags):
        """Erzeugt den privaten APP15-Metadatenmarker eines JPEG-Frames."""
        payload = _FRAME_METADATA_STRUCT.pack(
            _FRAME_METADATA_MAGIC,
            _FRAME_METADATA_VERSION,
            0,  # reservierte Metadaten-Flags; Rohframes sind nie synthetisch
            _FRAME_METADATA_STRUCT.size,
            frame_index,
            sequence,
            timestamp_ns,
            receive_monotonic_ns,
            buffer_flags,
        )
        return b'\xff\xef' + (len(payload) + 2).to_bytes(2, 'big') + payload

    def start_recording(self, filename, started_at=None):
        if self._writer_thread is not None:
            if self._writer_thread.is_alive():
                raise RuntimeError("Eine Aufnahme ist bereits aktiv oder wird noch beendet")
            # Nach einem Writer-Fehler verbliebene Datei-/Container-Ressourcen aufräumen.
            self.stop_recording()
        # Health-Counter zurücksetzen
        self.frames_written = 0
        self.capture_error = None
        self.sequence_gaps = 0
        self.sequence_frames_lost = 0
        self.sequence_resets = 0
        self.timestamp_gaps = 0
        self.buffer_errors = 0
        self.invalid_mjpeg_frames = 0
        self.max_buffer_hold_ms = 0.0
        self.max_write_ms = 0.0
        self.writer_queue_max_depth = 0
        self.writer_queue_drops = 0
        self.writer_error = None
        self.health_event_count = 0
        self.recording_start_time = time.monotonic()
        self._recording_started_at = started_at or ''
        self._first_frame = True
        # Frame-Dropping: jeden N-ten Frame schreiben um Ziel-fps zu erreichen
        self._record_skip = max(1, round(self.camera_fps / self.fps)) if self.fps > 0 else 1
        self._record_counter = 0
        self._next_frame_index = 0
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
            # Ungepuffert: Die dedizierte Queue ist der einzige und kontrollierte Puffer.
            self.record_file = open(filename, 'wb', buffering=0)
            with self.avi_lock:
                self.avi_writer = None
        self._writer_queue = queue.Queue(maxsize=self.writer_queue_size)
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="v4l2-record-writer",
            daemon=True,
        )
        self._writer_thread.start()
        with self._recording_state_lock:
            self.recording = True

    def stop_recording(self):
        with self._recording_state_lock:
            self.recording = False
            writer_queue = self._writer_queue
            writer_thread = self._writer_thread

        # Das Stop-Sentinel steht hinter allen bereits angenommenen Frames. Der Writer
        # schreibt die Queue vollständig leer, bevor Datei/Container geschlossen werden.
        if writer_queue is not None and writer_thread is not None:
            sentinel_queued = False
            while writer_thread.is_alive() and not sentinel_queued:
                try:
                    writer_queue.put(_WRITER_STOP, timeout=0.2)
                    sentinel_queued = True
                except queue.Full:
                    pass
            if sentinel_queued:
                writer_thread.join()

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
        self._writer_thread = None
        self._writer_queue = None
        print(
            f"[V4L2-DIAG] Aufnahme-Zusammenfassung: "
            f"sequence_gaps={self.sequence_gaps}, "
            f"sequence_frames_lost={self.sequence_frames_lost}, "
            f"sequence_resets={self.sequence_resets}, "
            f"timestamp_gaps={self.timestamp_gaps}, "
            f"buffer_errors={self.buffer_errors}, "
            f"invalid_mjpeg_frames={self.invalid_mjpeg_frames}, "
            f"allocated_buffers={self.allocated_buffers}, "
            f"max_buffer_hold_ms={self.max_buffer_hold_ms:.3f}, "
            f"max_write_ms={self.max_write_ms:.3f}, "
            f"writer_queue_max_depth={self.writer_queue_max_depth}, "
            f"writer_queue_drops={self.writer_queue_drops}, "
            f"writer_error={self.writer_error!r}",
            flush=True,
        )

    def _writer_loop(self):
        """Schreibt Frames außerhalb des zeitkritischen V4L2-Capture-Threads."""
        writer_queue = self._writer_queue
        if writer_queue is None:
            return
        try:
            while True:
                item = writer_queue.get()
                try:
                    if item is _WRITER_STOP:
                        return
                    frame, metadata = item
                    self._write_record_frame(frame, metadata)
                finally:
                    writer_queue.task_done()
        except Exception as e:
            msg = f"Schreibfehler in Aufnahmedatei: {e}"
            print(f"[WRITER ERROR] {msg}", flush=True)
            self.writer_error = msg
            self.capture_error = msg
            self._emit_health_event("writer_error", msg, severity="error")
            with self._recording_state_lock:
                self.recording = False

    @staticmethod
    def _writev_all(fd, chunks):
        """Schreibt alle Buffer vollständig, auch wenn ``writev`` nur teilweise schreibt."""
        pending = [memoryview(chunk) for chunk in chunks if len(chunk)]
        while pending:
            written = os.writev(fd, pending)
            if written <= 0:
                raise OSError("writev hat keine Daten geschrieben")
            while pending and written >= len(pending[0]):
                written -= len(pending[0])
                pending.pop(0)
            if pending and written:
                pending[0] = pending[0][written:]

    def _write_record_frame(self, frame, metadata):
        write_started_at = time.monotonic()
        try:
            if self.record_file is not None:
                frame_view = memoryview(frame)
                if len(frame_view) < 2 or bytes(frame_view[:2]) != b'\xff\xd8':
                    self.invalid_mjpeg_frames += 1
                    self._emit_health_event(
                        "invalid_mjpeg_frame",
                        "Writer hat ein MJPEG-Frame ohne JPEG-SOI verworfen",
                        source="writer",
                        total=self.invalid_mjpeg_frames,
                    )
                    print(
                        "[WRITER WARNING] Ungültiges MJPEG-Frame ohne JPEG-SOI "
                        "verworfen.",
                        flush=True,
                    )
                    return
                chunks = [frame_view[:2]]
                if self._first_frame:
                    self._first_frame = False
                    # Bestehende globale Aufnahme-Metadaten bleiben für ältere
                    # Werkzeuge im ersten Frame erhalten.
                    chunks.append(
                        self._build_com_segment(self.fps, self._recording_started_at)
                    )
                chunks.append(self._build_frame_metadata_segment(*metadata))
                chunks.append(frame_view[2:])
                self._writev_all(self.record_file.fileno(), chunks)
                self.frames_written += 1
                return

            with self.avi_lock:
                if self.avi_writer is not None:
                    arr = np.frombuffer(frame, dtype=np.uint8)
                    img = cv2.imdecode(arr, 1)
                    if img is not None:
                        self.avi_writer.write(img)
                        self.frames_written += 1
        finally:
            write_ms = (time.monotonic() - write_started_at) * 1000
            self.max_write_ms = max(self.max_write_ms, write_ms)

    def _enqueue_record_frame(self, frame, v4l2_timestamp_ns, sequence,
                              receive_monotonic_ns, v4l2_buffer_flags):
        """Nimmt einen Frame ohne Blockieren des Capture-Threads zur Aufnahme an."""
        with self._recording_state_lock:
            if not self.recording or self._writer_queue is None:
                return
            self._record_counter = (self._record_counter + 1) % self._record_skip
            if self._record_counter != 0:
                return
            try:
                metadata = (
                    self._next_frame_index,
                    sequence,
                    v4l2_timestamp_ns,
                    receive_monotonic_ns,
                    v4l2_buffer_flags,
                )
                self._writer_queue.put_nowait((frame, metadata))
                self._next_frame_index += 1
                self.writer_queue_max_depth = max(
                    self.writer_queue_max_depth, self._writer_queue.qsize()
                )
            except queue.Full:
                self.writer_queue_drops += 1
                self._emit_health_event(
                    "writer_queue_drop",
                    "Aufnahme-Queue war voll; Frame wurde verworfen",
                    drops=self.writer_queue_drops,
                    capacity=self.writer_queue_size,
                )
                print(
                    f"[WRITER WARNING] Aufnahme-Queue voll; Frame verworfen "
                    f"(drops={self.writer_queue_drops}, capacity={self.writer_queue_size})",
                    flush=True,
                )

    def _requeue_buffer(self, buf, dequeued_at):
        buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        buf.memory = v4l2.V4L2_MEMORY_MMAP
        fcntl.ioctl(self.fd, v4l2.VIDIOC_QBUF, buf)
        hold_ms = (time.monotonic() - dequeued_at) * 1000
        self._last_buffer_hold_ms = hold_ms
        self.max_buffer_hold_ms = max(self.max_buffer_hold_ms, hold_ms)

    def _track_sequence(self, sequence):
        """Erfasst echte Vorwärtssprünge, ohne Resets als Milliardenverlust zu zählen."""
        if self.last_sequence is None:
            self.last_sequence = sequence
            return

        previous = self.last_sequence
        sequence_delta = (sequence - previous) & 0xffffffff
        self.last_sequence = sequence
        if sequence_delta == 1:
            return
        if sequence_delta == 0 or sequence_delta > 0x7fffffff:
            self.sequence_resets += 1
            self._emit_health_event(
                "v4l2_sequence_reset",
                f"V4L2-Sequenz wurde von {previous} auf {sequence} zurückgesetzt",
                previous_sequence=previous,
                sequence=sequence,
                resets=self.sequence_resets,
            )
            print(
                f"[V4L2-DIAG] Sequenz-Reset {previous}->{sequence} "
                f"(resets={self.sequence_resets})",
                flush=True,
            )
            return

        lost = sequence_delta - 1
        self.sequence_gaps += 1
        self.sequence_frames_lost += lost
        self._emit_health_event(
            "v4l2_sequence_gap",
            f"V4L2-Sequenzsprung: {lost} Frame(s) fehlen",
            previous_sequence=previous,
            sequence=sequence,
            frames_lost=lost,
            frames_lost_total=self.sequence_frames_lost,
            previous_buffer_hold_ms=round(self._last_buffer_hold_ms, 3),
            max_buffer_hold_ms=round(self.max_buffer_hold_ms, 3),
        )
        print(
            f"[V4L2-DIAG] Sequenzsprung {previous}->{sequence} "
            f"(lost={lost}, previous_buffer_hold_ms={self._last_buffer_hold_ms:.3f}, "
            f"max_buffer_hold_ms={self.max_buffer_hold_ms:.3f})",
            flush=True,
        )

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
                    if consecutive_timeouts == MAX_CONSECUTIVE_TIMEOUTS:
                        self._emit_health_event("capture_timeout", msg, severity="error")
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
                self._emit_health_event("dqbuf_error", msg, severity="error")
                self.recording = False
                self.running = False
                break
            mm, length = self.mmaps[buf.index]
            dequeued_at = time.monotonic()
            receive_monotonic_ns = time.monotonic_ns()
            frame_ts_ns = (
                int(buf.timestamp.secs) * 1_000_000_000
                + int(buf.timestamp.usecs) * 1_000
            )
            frame_ts = frame_ts_ns / 1_000_000_000
            sequence = int(buf.sequence)
            if buf.flags & _V4L2_BUF_FLAG_ERROR:
                self.buffer_errors += 1
                self._emit_health_event(
                    "v4l2_buffer_error",
                    "V4L2 lieferte einen Puffer mit gesetztem ERROR-Flag",
                    sequence=sequence,
                    bytesused=int(buf.bytesused),
                    total=self.buffer_errors,
                )
                print(
                    f"[V4L2-DIAG] V4L2_BUF_FLAG_ERROR sequence={sequence} "
                    f"bytesused={buf.bytesused}",
                    flush=True,
                )
                try:
                    self._requeue_buffer(buf, dequeued_at)
                except OSError as e:
                    self._handle_qbuf_error(e)
                    break
                continue
            if buf.bytesused <= 0:
                try:
                    self._requeue_buffer(buf, dequeued_at)
                except OSError as e:
                    self._handle_qbuf_error(e)
                    break
                continue
            self._track_sequence(sequence)
            if self._last_capture_ts is not None and self.camera_fps > 0:
                timestamp_delta = frame_ts - self._last_capture_ts
                expected_delta = 1.0 / self.camera_fps
                if timestamp_delta > expected_delta * 1.5:
                    self.timestamp_gaps += 1
                    self._emit_health_event(
                        "v4l2_timestamp_gap",
                        f"V4L2-Zeitstempellücke von {timestamp_delta:.6f}s",
                        sequence=sequence,
                        delta_s=round(timestamp_delta, 6),
                        expected_delta_s=round(expected_delta, 6),
                        total=self.timestamp_gaps,
                    )
                    print(
                        f"[V4L2-DIAG] Timestamp-Luecke {timestamp_delta:.6f}s "
                        f"(expected={expected_delta:.6f}s, sequence={sequence})",
                        flush=True,
                    )
            self._last_capture_ts = frame_ts
            frame = mm[:buf.bytesused]
            # Frame-Health-Tracking
            self.frames_captured += 1
            self.last_frame_time = time.monotonic()
            if self.writer_error is None:
                self.capture_error = None  # Frame empfangen → kein Capture-Fehler

            # Manche Arducam-UVC-Fehlerbursts liefern nach der Kernel-
            # Resynchronisierung einen Puffer ohne gesetztes ERROR-Flag, dessen
            # Nutzdaten trotzdem kein JPEG sind. Solche Frames dürfen weder die
            # Aufnahme beenden noch Preview-Clients vergiften.
            if len(frame) < 2 or frame[:2] != b'\xff\xd8':
                self.invalid_mjpeg_frames += 1
                prefix = frame[:16].hex()
                self._emit_health_event(
                    "invalid_mjpeg_frame",
                    "Capture lieferte ein MJPEG-Frame ohne JPEG-SOI",
                    source="capture",
                    sequence=sequence,
                    bytesused=int(buf.bytesused),
                    prefix=prefix,
                    total=self.invalid_mjpeg_frames,
                )
                print(
                    f"[V4L2-DIAG] Ungültiges MJPEG-Frame verworfen "
                    f"(sequence={sequence}, bytesused={buf.bytesused}, "
                    f"prefix={prefix}, total={self.invalid_mjpeg_frames})",
                    flush=True,
                )
                try:
                    self._requeue_buffer(buf, dequeued_at)
                except OSError as e:
                    self._handle_qbuf_error(e)
                    break
                continue

            self._enqueue_record_frame(
                frame,
                frame_ts_ns,
                sequence,
                receive_monotonic_ns,
                int(buf.flags),
            )

            # Der Kernel-Puffer wird direkt nach der Byte-Kopie zurückgegeben. Weder
            # SSD-I/O noch Preview-Verarbeitung verlängern damit seine Haltezeit.
            try:
                self._requeue_buffer(buf, dequeued_at)
            except OSError as e:
                self._handle_qbuf_error(e)
                break

            if self.preview_callback is not None:
                try:
                    self.preview_callback(frame)
                except Exception as e:
                    # Preview ist optional und darf die Aufnahme nie beenden.
                    print(f"[PREVIEW ERROR] Callback fehlgeschlagen: {e}", flush=True)

    def _handle_qbuf_error(self, error):
        msg = f"QBUF ioctl fehlgeschlagen: {error}"
        print(f"[CAPTURE ERROR] {msg}")
        self.capture_error = msg
        self._emit_health_event("qbuf_error", msg, severity="error")
        with self._recording_state_lock:
            self.recording = False
        self.running = False
