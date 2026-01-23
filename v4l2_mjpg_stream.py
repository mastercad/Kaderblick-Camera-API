import v4l2
import os
import fcntl
import mmap
import threading
import select
import ctypes
import numpy as np
import cv2

class V4L2MJPGStreamer:
    def __init__(self, device='/dev/video0', width=3840, height=2160, fps=30, buffers=4):
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
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

    def open(self):
        self.fd = os.open(self.device, os.O_RDWR | os.O_NONBLOCK)
        fmt = v4l2.v4l2_format()
        fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        fmt.fmt.pix.width = self.width
        fmt.fmt.pix.height = self.height
        fmt.fmt.pix.pixelformat = v4l2.V4L2_PIX_FMT_MJPEG
        fmt.fmt.pix.field = v4l2.V4L2_FIELD_NONE
        fcntl.ioctl(self.fd, v4l2.VIDIOC_S_FMT, fmt)
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
            fcntl.ioctl(self.fd, v4l2.VIDIOC_STREAMOFF, buf_type)
            for mm, _ in self.mmaps:
                mm.close()
            os.close(self.fd)
            self.fd = None

    def start_recording(self, filename):
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
        while self.running:
            r, _, _ = select.select([self.fd], [], [], 1)
            if not r:
                continue
            buf = v4l2.v4l2_buffer()
            buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
            buf.memory = v4l2.V4L2_MEMORY_MMAP
            try:
                fcntl.ioctl(self.fd, v4l2.VIDIOC_DQBUF, buf)
            except OSError as e:
                if e.errno == 11:
                    continue
                print(f"DQBUF ioctl failed: {e}")
                break
            mm, length = self.mmaps[buf.index]
            frame = mm[:buf.bytesused]
            if self.recording:
                if self.record_file:
                    self.record_file.write(frame)
                else:
                    with self.avi_lock:
                        if self.avi_writer is not None:
                            # MJPG-Frame als BGR-Image decodieren und in AVI schreiben
                            arr = np.frombuffer(frame, dtype=np.uint8)
                            img = cv2.imdecode(arr, 1)
                            if img is not None:
                                self.avi_writer.write(img)
            if self.preview_callback is not None and len(frame) > 0:
                self.preview_callback(frame)
            buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
            buf.memory = v4l2.V4L2_MEMORY_MMAP
            try:
                fcntl.ioctl(self.fd, v4l2.VIDIOC_QBUF, buf)
            except OSError as e:
                print(f"QBUF ioctl failed: {e}")
                break
