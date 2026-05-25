"""
Tests für v4l2_mjpg_stream.V4L2MJPGStreamer

Getestet werden ausschließlich die in Python implementierten Zustands- und
Logik-Methoden, die KEINE Hardware-Interaktion erfordern. Alles was fcntl.ioctl
oder mmap benötigt, wird über Mocks abgedeckt.

Hardware-Mocks (v4l2, numpy, cv2) werden bereits durch tests/conftest.py gesetzt.
"""
import threading
import time
from unittest.mock import MagicMock, patch, mock_open

import pytest

from v4l2_mjpg_stream import V4L2MJPGStreamer


# ===========================================================================
# __init__ – Standardwerte und benutzerdefinierte Parameter
# ===========================================================================

class TestInit:
    def test_defaults(self):
        s = V4L2MJPGStreamer()
        assert s.device == "/dev/video0"
        assert s.width == 3840
        assert s.height == 2160
        assert s.fps == 30
        assert s.buffers == 4
        assert s.fd is None
        assert s.mmaps == []
        assert s.running is False
        assert s.recording is False
        assert s.record_file is None
        assert s.preview_callback is None
        assert s.thread is None
        assert s.avi_writer is None

    def test_defaults_health_tracking(self):
        s = V4L2MJPGStreamer()
        assert s.frames_captured == 0
        assert s.frames_written == 0
        assert s.last_frame_time is None
        assert s.capture_error is None
        assert s.recording_start_time is None

    def test_custom_params(self):
        s = V4L2MJPGStreamer(device="/dev/video1", width=1920, height=1080, fps=15, buffers=2)
        assert s.device == "/dev/video1"
        assert s.width == 1920
        assert s.height == 1080
        assert s.fps == 15
        assert s.buffers == 2


# ===========================================================================
# set_preview_callback
# ===========================================================================

class TestSetPreviewCallback:
    def test_stores_callback(self):
        s = V4L2MJPGStreamer()
        cb = MagicMock()
        s.set_preview_callback(cb)
        assert s.preview_callback is cb

    def test_replaces_existing_callback(self):
        s = V4L2MJPGStreamer()
        cb1 = MagicMock()
        cb2 = MagicMock()
        s.set_preview_callback(cb1)
        s.set_preview_callback(cb2)
        assert s.preview_callback is cb2

    def test_sets_none(self):
        s = V4L2MJPGStreamer()
        s.set_preview_callback(MagicMock())
        s.set_preview_callback(None)
        assert s.preview_callback is None


# ===========================================================================
# is_capture_healthy
# ===========================================================================

def _alive_thread():
    """Gibt einen laufenden Daemon-Thread zurück."""
    t = threading.Thread(target=lambda: time.sleep(60), daemon=True)
    t.start()
    return t


def _dead_thread():
    """Gibt einen bereits beendeten Thread zurück."""
    t = threading.Thread(target=lambda: None)
    t.start()
    t.join()
    return t


class TestIsCaptureHealthy:
    def test_no_thread_returns_false(self):
        s = V4L2MJPGStreamer()
        assert s.is_capture_healthy() is False

    def test_dead_thread_returns_false(self):
        s = V4L2MJPGStreamer()
        s.thread = _dead_thread()
        assert s.is_capture_healthy() is False

    def test_alive_thread_no_frame_yet_returns_true(self):
        """Thread gestartet, aber noch kein Frame empfangen → OK."""
        s = V4L2MJPGStreamer()
        s.thread = _alive_thread()
        s.last_frame_time = None
        assert s.is_capture_healthy() is True

    def test_alive_thread_recent_frame_returns_true(self):
        s = V4L2MJPGStreamer()
        s.thread = _alive_thread()
        s.last_frame_time = time.monotonic() - 1.0  # 1 Sekunde alt
        assert s.is_capture_healthy(max_frame_age_s=5.0) is True

    def test_alive_thread_stale_frame_returns_false(self):
        s = V4L2MJPGStreamer()
        s.thread = _alive_thread()
        s.last_frame_time = time.monotonic() - 10.0  # 10 Sekunden alt
        assert s.is_capture_healthy(max_frame_age_s=5.0) is False

    def test_exactly_at_threshold_is_healthy(self):
        """Frames die genau unterhalb der Schwelle liegen → healthy."""
        s = V4L2MJPGStreamer()
        s.thread = _alive_thread()
        s.last_frame_time = time.monotonic() - 4.9
        assert s.is_capture_healthy(max_frame_age_s=5.0) is True

    def test_custom_max_frame_age(self):
        s = V4L2MJPGStreamer()
        s.thread = _alive_thread()
        s.last_frame_time = time.monotonic() - 2.0
        assert s.is_capture_healthy(max_frame_age_s=1.0) is False
        assert s.is_capture_healthy(max_frame_age_s=10.0) is True


# ===========================================================================
# start_recording / stop_recording
# ===========================================================================

class TestRecording:
    def test_start_recording_raw_sets_flags(self, tmp_path):
        s = V4L2MJPGStreamer()
        s.start_recording(str(tmp_path / "test.raw"))
        assert s.recording is True
        assert s.record_file is not None
        assert s.frames_written == 0
        assert s.capture_error is None
        assert s.recording_start_time is not None
        s.stop_recording()

    def test_start_recording_resets_counters(self, tmp_path):
        s = V4L2MJPGStreamer()
        s.frames_written = 99
        s.capture_error = "old error"
        s.start_recording(str(tmp_path / "test.raw"))
        assert s.frames_written == 0
        assert s.capture_error is None
        s.stop_recording()

    def test_start_recording_raw_no_avi_writer(self, tmp_path):
        s = V4L2MJPGStreamer()
        s.start_recording(str(tmp_path / "test.raw"))
        with s.avi_lock:
            assert s.avi_writer is None
        s.stop_recording()

    def test_stop_recording_clears_recording_flag(self, tmp_path):
        s = V4L2MJPGStreamer()
        s.start_recording(str(tmp_path / "test.raw"))
        s.stop_recording()
        assert s.recording is False

    def test_stop_recording_closes_file(self, tmp_path):
        s = V4L2MJPGStreamer()
        s.start_recording(str(tmp_path / "test.raw"))
        f = s.record_file
        s.stop_recording()
        assert s.record_file is None
        assert f.closed

    def test_start_recording_avi_uses_video_writer(self, tmp_path):
        s = V4L2MJPGStreamer()
        mock_writer = MagicMock()
        with patch("cv2.VideoWriter", return_value=mock_writer):
            with patch("cv2.VideoWriter_fourcc", return_value=0x47504A4D):
                s.start_recording(str(tmp_path / "test.avi"))
        assert s.recording is True
        assert s.record_file is None
        with s.avi_lock:
            assert s.avi_writer is mock_writer
        s.stop_recording()

    def test_stop_recording_releases_avi_writer(self):
        s = V4L2MJPGStreamer()
        mock_writer = MagicMock()
        s.recording = True
        with s.avi_lock:
            s.avi_writer = mock_writer
        s.stop_recording()
        mock_writer.release.assert_called_once()
        with s.avi_lock:
            assert s.avi_writer is None

    def test_stop_recording_avi_release_exception_does_not_raise(self):
        """Fehler beim AVI-Writer-Release darf keinen Absturz auslösen."""
        s = V4L2MJPGStreamer()
        mock_writer = MagicMock()
        mock_writer.release.side_effect = RuntimeError("release failed")
        s.recording = True
        with s.avi_lock:
            s.avi_writer = mock_writer
        s.stop_recording()  # darf nicht werfen
        assert s.recording is False

    def test_stop_recording_when_not_recording(self):
        """stop_recording auf nicht-laufende Aufnahme ist sicher."""
        s = V4L2MJPGStreamer()
        s.stop_recording()  # kein Crash
        assert s.recording is False

    def test_recording_start_time_set_correctly(self, tmp_path):
        s = V4L2MJPGStreamer()
        before = time.monotonic()
        s.start_recording(str(tmp_path / "test.raw"))
        after = time.monotonic()
        assert before <= s.recording_start_time <= after
        s.stop_recording()


# ===========================================================================
# _capture_loop – Timeout-Logik (isoliert über direkte Attributmanipulation)
# ===========================================================================

class TestCaptureLoopTimeoutLogic:
    """
    Testet die Timeout-Logik des _capture_loop durch direktes Aufrufen
    des Loops mit vollständig gemocktem select/fcntl/v4l2.
    """

    def _make_streamer_with_mocked_fd(self):
        """Streamer mit fake fd und mmaps."""
        s = V4L2MJPGStreamer()
        s.fd = 42
        # Fake mmap: bytes liefern
        fake_mm = MagicMock()
        fake_mm.__getitem__ = lambda self, key: b"\xff\xd8\xff\xe0" + b"\x00" * 100  # JPEG-ähnlich
        s.mmaps = [(fake_mm, 1024)]
        return s

    def test_timeout_sets_capture_error_after_10(self):
        """10 aufeinanderfolgende Timeouts → capture_error gesetzt."""
        s = self._make_streamer_with_mocked_fd()
        s.running = True

        call_count = [0]

        def fake_select(rlist, wlist, xlist, timeout):
            call_count[0] += 1
            if call_count[0] > 10:
                s.running = False  # Loop beenden
            return [], [], []  # Timeout

        import select as real_select
        with patch.object(real_select, "select", fake_select):
            s._capture_loop()

        assert s.capture_error is not None
        assert "Kein Frame" in s.capture_error

    def test_timeout_stops_recording_after_10(self):
        """10 Timeouts → Aufnahme wird gestoppt."""
        s = self._make_streamer_with_mocked_fd()
        s.running = True
        s.recording = True

        call_count = [0]

        def fake_select(rlist, wlist, xlist, timeout):
            call_count[0] += 1
            if call_count[0] > 10:
                s.running = False
            return [], [], []

        import select as real_select
        with patch.object(real_select, "select", fake_select):
            s._capture_loop()

        assert s.recording is False

    def test_timeout_below_threshold_no_error(self):
        """Weniger als 10 Timeouts → noch kein Fehler."""
        s = self._make_streamer_with_mocked_fd()
        s.running = True

        call_count = [0]

        def fake_select(rlist, wlist, xlist, timeout):
            call_count[0] += 1
            if call_count[0] >= 9:
                s.running = False
            return [], [], []

        import select as real_select
        with patch.object(real_select, "select", fake_select):
            s._capture_loop()

        assert s.capture_error is None

    def test_frame_received_resets_timeout_counter(self):
        """Nach einem Frame-Empfang wird der Timeout-Zähler zurückgesetzt."""
        import fcntl
        import v4l2 as _v4l2

        s = self._make_streamer_with_mocked_fd()
        s.running = True

        call_count = [0]
        buf_mock = MagicMock()
        buf_mock.index = 0
        buf_mock.bytesused = 104

        def fake_select(rlist, wlist, xlist, timeout):
            call_count[0] += 1
            if call_count[0] <= 5:
                return [], [], []  # Timeout
            if call_count[0] == 6:
                return [s.fd], [], []  # Frame
            s.running = False
            return [], [], []

        def fake_ioctl(fd, req, buf):
            if hasattr(buf, "index"):
                buf.index = 0
                buf.bytesused = 104

        import select as real_select
        with patch.object(real_select, "select", fake_select):
            with patch("fcntl.ioctl", fake_ioctl):
                with patch("v4l2.v4l2_buffer", return_value=buf_mock):
                    s._capture_loop()

        # Nach dem Frame darf capture_error nicht gesetzt sein
        assert s.capture_error is None
        assert s.frames_captured >= 1


# ===========================================================================
# _inject_com_marker
# ===========================================================================

import json
import struct


class TestInjectComMarker:
    """Tests für V4L2MJPGStreamer._inject_com_marker()"""

    def _make_fake_jpeg(self, payload: bytes = b'\xff\xe0\x00\x10JFIF') -> bytes:
        """Minimales JPEG: SOI (FF D8) + weiterer Payload."""
        return b'\xff\xd8' + payload

    def _parse_com_result(self, result: bytes):
        """Gibt (length_value, json_bytes) aus dem injizierten COM-Segment zurück."""
        length = struct.unpack('>H', result[4:6])[0]
        json_bytes = result[6: 4 + length]
        return length, json_bytes

    def test_soi_preserved_at_start(self):
        s = V4L2MJPGStreamer()
        result = s._inject_com_marker(self._make_fake_jpeg(), fps=30, started_at='2026-05-24T10:00:00')
        assert result[:2] == b'\xff\xd8'

    def test_com_marker_ff_fe_at_offset_2(self):
        s = V4L2MJPGStreamer()
        result = s._inject_com_marker(self._make_fake_jpeg(), fps=30, started_at='2026-05-24T10:00:00')
        assert result[2:4] == b'\xff\xfe'

    def test_length_field_correct(self):
        """Längenfeld = len(JSON-Bytes) + 2 (Längenfeld selbst)."""
        s = V4L2MJPGStreamer()
        fps, started_at = 15, '2026-05-24T10:00:00.123456'
        result = s._inject_com_marker(self._make_fake_jpeg(), fps=fps, started_at=started_at)
        length, _ = self._parse_com_result(result)
        expected_comment = json.dumps({"fps": fps, "started_at": started_at}).encode('utf-8')
        assert length == len(expected_comment) + 2

    def test_json_contains_fps(self):
        s = V4L2MJPGStreamer()
        fps = 25
        result = s._inject_com_marker(self._make_fake_jpeg(), fps=fps, started_at='2026-05-24T12:00:00')
        _, json_bytes = self._parse_com_result(result)
        assert json.loads(json_bytes.decode('utf-8'))['fps'] == fps

    def test_json_contains_started_at(self):
        s = V4L2MJPGStreamer()
        started_at = '2026-05-24T08:15:00.000000'
        result = s._inject_com_marker(self._make_fake_jpeg(), fps=30, started_at=started_at)
        _, json_bytes = self._parse_com_result(result)
        assert json.loads(json_bytes.decode('utf-8'))['started_at'] == started_at

    def test_json_has_only_fps_and_started_at(self):
        s = V4L2MJPGStreamer()
        result = s._inject_com_marker(self._make_fake_jpeg(), fps=30, started_at='2026-05-24T10:00:00')
        _, json_bytes = self._parse_com_result(result)
        assert set(json.loads(json_bytes.decode('utf-8')).keys()) == {'fps', 'started_at'}

    def test_original_payload_preserved_after_com_segment(self):
        s = V4L2MJPGStreamer()
        payload = b'\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
        frame = b'\xff\xd8' + payload
        result = s._inject_com_marker(frame, fps=30, started_at='2026-05-24T10:00:00')
        length, _ = self._parse_com_result(result)
        end_of_com = 4 + length  # Offset nach COM-Segment: pos Längenfeld (4) + Längenwert
        assert result[end_of_com:] == payload

    def test_result_length_equals_frame_plus_com_segment(self):
        s = V4L2MJPGStreamer()
        fps, started_at = 30, '2026-05-24T10:00:00'
        payload = b'\xab\xcd\xef\x00' * 10
        frame = b'\xff\xd8' + payload
        result = s._inject_com_marker(frame, fps=fps, started_at=started_at)
        comment = json.dumps({"fps": fps, "started_at": started_at}).encode('utf-8')
        com_segment_size = 2 + 2 + len(comment)  # FF FE + Längenfeld + Nutzdaten
        assert len(result) == len(frame) + com_segment_size

    def test_different_fps_values_stored_correctly(self):
        s = V4L2MJPGStreamer()
        for fps in (15, 25, 30, 60):
            result = s._inject_com_marker(self._make_fake_jpeg(), fps=fps, started_at='2026-05-24T10:00:00')
            _, json_bytes = self._parse_com_result(result)
            assert json.loads(json_bytes.decode('utf-8'))['fps'] == fps


# ===========================================================================
# start_recording – Metadaten-Flags (started_at, _first_frame)
# ===========================================================================

class TestStartRecordingMetadata:
    """Tests für die Metadaten-Initialisierung in start_recording()."""

    def test_first_frame_flag_is_true_after_start(self, tmp_path):
        s = V4L2MJPGStreamer()
        s.start_recording(str(tmp_path / 'test.mjpg'), started_at='2026-05-24T10:00:00')
        assert s._first_frame is True
        s.stop_recording()

    def test_recording_started_at_set_to_passed_value(self, tmp_path):
        s = V4L2MJPGStreamer()
        started_at = '2026-05-24T10:00:00.000000'
        s.start_recording(str(tmp_path / 'test.mjpg'), started_at=started_at)
        assert s._recording_started_at == started_at
        s.stop_recording()

    def test_recording_started_at_defaults_to_empty_string(self, tmp_path):
        s = V4L2MJPGStreamer()
        s.start_recording(str(tmp_path / 'test.mjpg'))
        assert s._recording_started_at == ''
        s.stop_recording()

    def test_first_frame_reset_on_second_start(self, tmp_path):
        """_first_frame muss bei jedem Aufnahme-Start auf True zurückgesetzt werden."""
        s = V4L2MJPGStreamer()
        s.start_recording(str(tmp_path / 'a.mjpg'), started_at='2026-05-24T09:00:00')
        s._first_frame = False  # simuliert: erster Frame wurde bereits geschrieben
        s.stop_recording()
        s.start_recording(str(tmp_path / 'b.mjpg'), started_at='2026-05-24T10:00:00')
        assert s._first_frame is True
        s.stop_recording()

    def test_started_at_updated_on_second_start(self, tmp_path):
        s = V4L2MJPGStreamer()
        s.start_recording(str(tmp_path / 'a.mjpg'), started_at='2026-05-24T09:00:00')
        s.stop_recording()
        second_ts = '2026-05-24T10:30:00.000000'
        s.start_recording(str(tmp_path / 'b.mjpg'), started_at=second_ts)
        assert s._recording_started_at == second_ts
        s.stop_recording()
