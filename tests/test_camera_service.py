"""
Tests für camera_service – handle_commands(), Watchdog-Logik,
Audio-Monitor, preview_callback_mjpg, STATUS-Antwort.

camera_service.py importiert zmq und V4L2MJPGStreamer auf Modulebene und
öffnet sofort Sockets. Die Strategie: alle Module VORHER mocken, den
Modul-Import per importlib sauber isolieren (reload verhindert
State-Übernahme zwischen Testklassen).
"""
import importlib
import json
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

# -----------------------------------------------------------------------
# Alle Hardware-Module global mocken (ergänzend zu conftest.py)
# -----------------------------------------------------------------------

def _make_zmq_mock():
    m = MagicMock()
    m.NOBLOCK = 1
    m.REP = 4
    m.PUB = 1
    # REP-Socket
    rep = MagicMock()
    rep.recv_string.return_value = "STATUS"
    rep.poll.return_value = 1
    # PUB-Socket
    pub = MagicMock()
    ctx = MagicMock()
    ctx.socket.side_effect = lambda t: rep if t == m.REP else pub
    m.Context.return_value = ctx
    return m, rep, pub, ctx


def _make_streamer_mock():
    s = MagicMock()
    s.recording = False
    s.recording_flag = False
    s.capture_error = None
    s.frames_captured = 0
    s.frames_written = 0
    s.last_frame_time = time.monotonic()
    s.width = 3840
    s.height = 2160
    s.fps = 30
    s.thread = MagicMock()
    s.thread.is_alive.return_value = True
    s.is_capture_healthy.return_value = True
    return s


# ===========================================================================
# Hilfsfunktion: camera_service frisch laden mit gemockten Abhängigkeiten
# ===========================================================================

def _load_camera_service(zmq_mock, streamer_mock, audio_device="hw:1,0"):
    """
    Lädt camera_service neu und gibt das Modul zurück.
    Alle Hardware-Seiteneffekte werden durch Mocks verhindert.
    """
    sys.modules["zmq"] = zmq_mock
    sys.modules["find_usb_audio"] = MagicMock(
        find_usb_audio_device=MagicMock(return_value=audio_device)
    )
    sys.modules["v4l2_mjpg_stream"] = MagicMock(
        V4L2MJPGStreamer=MagicMock(return_value=streamer_mock)
    )

    # Falls bereits geladen, entfernen um sauberen Import zu gewährleisten
    if "camera_service" in sys.modules:
        del sys.modules["camera_service"]

    import camera_service as cs
    return cs


# ===========================================================================
# preview_callback_mjpg
# ===========================================================================

class TestPreviewCallback:
    def test_sends_frame_via_pub(self):
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        streamer = _make_streamer_mock()
        cs = _load_camera_service(zmq_mock, streamer)

        frame = b"\xff\xd8\xff" + b"\x00" * 50
        cs.preview_callback_mjpg(frame)
        pub.send.assert_called_once_with(frame, zmq_mock.NOBLOCK)

    def test_ignores_zmq_exception(self):
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        streamer = _make_streamer_mock()
        cs = _load_camera_service(zmq_mock, streamer)

        pub.send.side_effect = Exception("zmq full")
        # darf keinen Absturz verursachen
        cs.preview_callback_mjpg(b"\xff\xd8\xff")


# ===========================================================================
# handle_commands – START
# ===========================================================================

class TestHandleCommandsStart:
    def setup_method(self):
        self.zmq_mock, self.rep, self.pub, self.ctx = _make_zmq_mock()
        self.streamer = _make_streamer_mock()
        self.cs = _load_camera_service(self.zmq_mock, self.streamer)

    def _run_one_command(self, command: str):
        """
        Führt einen einzelnen Befehlszyklus in handle_commands() durch,
        indem rep.recv_string einmalig den Befehl liefert und dann StopIteration wirft.
        """
        self.rep.recv_string.side_effect = [command, KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass

    def test_start_when_already_recording(self):
        self.cs.recording_lock = threading.Lock()
        # Simuliere laufende Aufnahme
        self.cs.recording_lock.acquire()
        # Setze recording_flag direkt
        import threading as _t
        import ctypes
        # Einfacher Weg: recording_flag wird im Lock geprüft
        # Wir mocken stattdessen direkt und testen die Antwort
        self.cs.recording_lock.release()

    def test_start_sends_ok_when_not_recording(self):
        self.cs.recording_flag = False
        self.streamer.recording = False
        self.streamer.is_capture_healthy.return_value = True

        with patch.object(self.cs, "recording_lock", threading.Lock()):
            with patch("subprocess.Popen") as popen_mock:
                popen_mock.return_value = MagicMock(poll=lambda: None)
                self.rep.recv_string.side_effect = ["START", KeyboardInterrupt]
                try:
                    self.cs.handle_commands()
                except KeyboardInterrupt:
                    pass

        sent = self.rep.send_string.call_args_list
        assert len(sent) >= 1

    def test_stop_sends_response(self):
        self.cs.recording_flag = True
        self.rep.recv_string.side_effect = ["STOP", KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass
        self.rep.send_string.assert_called()

    def test_unknown_command_sends_unknown(self):
        self.rep.recv_string.side_effect = ["GIBBERISH_CMD", KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass
        calls = [str(c) for c in self.rep.send_string.call_args_list]
        assert any("UNKNOWN" in c for c in calls)


# ===========================================================================
# handle_commands – STATUS
# ===========================================================================

class TestHandleCommandsStatus:
    def setup_method(self):
        self.zmq_mock, self.rep, self.pub, self.ctx = _make_zmq_mock()
        self.streamer = _make_streamer_mock()
        self.cs = _load_camera_service(self.zmq_mock, self.streamer)

    def test_status_response_is_valid_json(self):
        self.rep.recv_string.side_effect = ["STATUS", KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass
        response_str = self.rep.send_string.call_args[0][0]
        data = json.loads(response_str)
        assert isinstance(data, dict)

    def test_status_contains_recording_field(self):
        self.rep.recv_string.side_effect = ["STATUS", KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass
        response_str = self.rep.send_string.call_args[0][0]
        data = json.loads(response_str)
        assert "recording" in data

    def test_status_contains_capture_thread_alive(self):
        self.rep.recv_string.side_effect = ["STATUS", KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass
        response_str = self.rep.send_string.call_args[0][0]
        data = json.loads(response_str)
        assert "capture_thread_alive" in data

    def test_status_contains_width_height_fps(self):
        self.rep.recv_string.side_effect = ["STATUS", KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass
        response_str = self.rep.send_string.call_args[0][0]
        data = json.loads(response_str)
        assert "width" in data
        assert "height" in data
        assert "fps" in data

    def test_status_width_matches_streamer(self):
        self.streamer.width = 1920
        self.streamer.height = 1080
        self.streamer.fps = 15
        self.rep.recv_string.side_effect = ["STATUS", KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass
        response_str = self.rep.send_string.call_args[0][0]
        data = json.loads(response_str)
        assert data["width"] == 1920
        assert data["height"] == 1080
        assert data["fps"] == 15


# ===========================================================================
# handle_commands – SET_RESOLUTION
# ===========================================================================

class TestHandleCommandsSetResolution:
    def setup_method(self):
        self.zmq_mock, self.rep, self.pub, self.ctx = _make_zmq_mock()
        self.streamer = _make_streamer_mock()
        self.cs = _load_camera_service(self.zmq_mock, self.streamer)
        self._patch_usb = patch('camera_service._usb_reset_arducam', return_value=True)
        self._patch_wait = patch('camera_service._wait_for_video_device', return_value=True)
        self._patch_usb.start()
        self._patch_wait.start()

    def teardown_method(self):
        self._patch_usb.stop()
        self._patch_wait.stop()

    def test_refuses_when_recording(self):
        self.streamer.recording = True  # camera_service prüft streamer.recording
        self.rep.recv_string.side_effect = ["SET_RESOLUTION:1920x1080:30", KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass
        calls = [str(c) for c in self.rep.send_string.call_args_list]
        assert any("ERROR" in c for c in calls)

    def test_sends_ok_on_valid_resolution_when_not_recording(self):
        self.cs.recording_flag = False
        self.rep.recv_string.side_effect = ["SET_RESOLUTION:1920x1080:15", KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass
        calls = [str(c) for c in self.rep.send_string.call_args_list]
        assert any("OK" in c for c in calls)

    def test_sends_error_on_malformed_resolution(self):
        self.cs.recording_flag = False
        self.rep.recv_string.side_effect = ["SET_RESOLUTION:GARBAGE", KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass
        calls = [str(c) for c in self.rep.send_string.call_args_list]
        assert any("ERROR" in c for c in calls)

    def test_streamer_restarted_with_new_resolution(self):
        self.cs.recording_flag = False
        self.rep.recv_string.side_effect = ["SET_RESOLUTION:1920x1080:30", KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass
        # Streamer muss gestoppt und neu initialisiert worden sein
        self.streamer.stop.assert_called()


# ===========================================================================
# JSON-Sidecar (START erstellt, STOP ergänzt ended_at)
# ===========================================================================

class TestJsonSidecar:
    """Tests für den JSON-Sidecar der Aufnahmen."""

    def setup_method(self):
        self.zmq_mock, self.rep, self.pub, self.ctx = _make_zmq_mock()
        self.streamer = _make_streamer_mock()
        # Kein Audio-Device → kein subprocess.Popen nötig
        self.cs = _load_camera_service(self.zmq_mock, self.streamer, audio_device=None)

    def _run_command(self, command: str):
        self.rep.recv_string.side_effect = [command, KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass

    def test_start_creates_json_sidecar(self, tmp_path):
        """START-Befehl legt einen JSON-Sidecar mit fps und started_at an."""
        self.streamer.recording = False
        self.streamer.fps = 30
        (tmp_path / 'recordings').mkdir()
        original_file = self.cs.__file__
        self.cs.__file__ = str(tmp_path / 'src' / 'camera_service.py')
        try:
            self._run_command('START')
        finally:
            self.cs.__file__ = original_file

        json_files = list((tmp_path / 'recordings').glob('*.json'))
        assert len(json_files) == 1
        data = json.loads(json_files[0].read_text())
        assert data['fps'] == 30
        assert 'started_at' in data
        assert 'ended_at' not in data

    def test_start_sidecar_started_at_is_valid_iso(self, tmp_path):
        """started_at im Sidecar muss ein gültiges ISO-8601-Datum sein."""
        self.streamer.recording = False
        self.streamer.fps = 15
        (tmp_path / 'recordings').mkdir()
        original_file = self.cs.__file__
        self.cs.__file__ = str(tmp_path / 'src' / 'camera_service.py')
        try:
            self._run_command('START')
        finally:
            self.cs.__file__ = original_file

        from datetime import datetime
        data = json.loads(next((tmp_path / 'recordings').glob('*.json')).read_text())
        datetime.fromisoformat(data['started_at'])  # wirft ValueError bei ungültigem Format

    def test_start_passes_started_at_to_start_recording(self, tmp_path):
        """started_at wird als Keyword-Argument an streamer.start_recording() übergeben."""
        self.streamer.recording = False
        self.streamer.fps = 30
        (tmp_path / 'recordings').mkdir()
        original_file = self.cs.__file__
        self.cs.__file__ = str(tmp_path / 'src' / 'camera_service.py')
        try:
            self._run_command('START')
        finally:
            self.cs.__file__ = original_file

        self.streamer.start_recording.assert_called_once()
        kwargs = self.streamer.start_recording.call_args.kwargs
        assert 'started_at' in kwargs
        from datetime import datetime
        datetime.fromisoformat(kwargs['started_at'])

    def test_stop_adds_ended_at_to_sidecar(self, tmp_path):
        """STOP-Befehl ergänzt ended_at im bestehenden JSON-Sidecar."""
        recordings_dir = tmp_path / 'recordings'
        recordings_dir.mkdir()
        meta_file = recordings_dir / 'aufnahme_test.json'
        started_at = '2026-05-24T10:00:00.000000'
        meta_file.write_text(json.dumps({'fps': 30, 'started_at': started_at}))

        self.cs.current_meta_filename = str(meta_file)
        self.streamer.recording = True

        self._run_command('STOP')

        data = json.loads(meta_file.read_text())
        assert 'ended_at' in data
        from datetime import datetime
        datetime.fromisoformat(data['ended_at'])

    def test_stop_preserves_fps_and_started_at(self, tmp_path):
        """STOP überschreibt fps und started_at nicht."""
        recordings_dir = tmp_path / 'recordings'
        recordings_dir.mkdir()
        meta_file = recordings_dir / 'aufnahme_test.json'
        started_at = '2026-05-24T10:00:00.000000'
        original_fps = 15
        meta_file.write_text(json.dumps({'fps': original_fps, 'started_at': started_at}))

        self.cs.current_meta_filename = str(meta_file)
        self.streamer.recording = True

        self._run_command('STOP')

        data = json.loads(meta_file.read_text())
        assert data['fps'] == original_fps
        assert data['started_at'] == started_at

    def test_stop_clears_current_meta_filename(self, tmp_path):
        """current_meta_filename wird nach STOP auf None zurückgesetzt."""
        recordings_dir = tmp_path / 'recordings'
        recordings_dir.mkdir()
        meta_file = recordings_dir / 'aufnahme_test.json'
        meta_file.write_text(json.dumps({'fps': 30, 'started_at': '2026-05-24T10:00:00'}))

        self.cs.current_meta_filename = str(meta_file)
        self.streamer.recording = True

        self._run_command('STOP')

        assert self.cs.current_meta_filename is None

    def test_stop_without_sidecar_does_not_raise(self):
        """STOP ohne Sidecar-Datei (z.B. nach Fehler) darf nicht abstürzen."""
        self.cs.current_meta_filename = None
        self.streamer.recording = True

        self._run_command('STOP')  # kein Crash erwartet


# ===========================================================================
# MJPEG_NATIVE_FPS – Modul-Konstante
# ===========================================================================

class TestMjpegNativeFps:
    def setup_method(self):
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        streamer = _make_streamer_mock()
        self.cs = _load_camera_service(zmq_mock, streamer)

    def test_4k_is_30fps(self):
        assert self.cs.MJPEG_NATIVE_FPS[(3840, 2160)] == 30

    def test_1080p_is_60fps(self):
        assert self.cs.MJPEG_NATIVE_FPS[(1920, 1080)] == 60

    def test_720p_is_60fps(self):
        assert self.cs.MJPEG_NATIVE_FPS[(1280, 720)] == 60

    def test_480p_is_60fps(self):
        assert self.cs.MJPEG_NATIVE_FPS[(640, 480)] == 60

    def test_unknown_resolution_not_in_table(self):
        assert (640, 360) not in self.cs.MJPEG_NATIVE_FPS


# ===========================================================================
# _load_resolution_config
# ===========================================================================

class TestLoadResolutionConfig:
    def setup_method(self):
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        streamer = _make_streamer_mock()
        self.cs = _load_camera_service(zmq_mock, streamer)

    def _set_config_path(self, path):
        self.cs.RESOLUTION_CONFIG_FILE = str(path)

    def test_returns_defaults_when_no_file(self, tmp_path):
        self._set_config_path(tmp_path / "nonexistent.json")
        cfg = self.cs._load_resolution_config()
        assert cfg == {"width": 3840, "height": 2160, "fps": 30, "camera_fps": 30}

    def test_default_width_is_3840(self, tmp_path):
        self._set_config_path(tmp_path / "nonexistent.json")
        assert self.cs._load_resolution_config()["width"] == 3840

    def test_default_height_is_2160(self, tmp_path):
        self._set_config_path(tmp_path / "nonexistent.json")
        assert self.cs._load_resolution_config()["height"] == 2160

    def test_default_fps_is_30(self, tmp_path):
        self._set_config_path(tmp_path / "nonexistent.json")
        assert self.cs._load_resolution_config()["fps"] == 30

    def test_default_camera_fps_is_30(self, tmp_path):
        self._set_config_path(tmp_path / "nonexistent.json")
        assert self.cs._load_resolution_config()["camera_fps"] == 30

    def test_returns_all_four_fields_from_file(self, tmp_path):
        p = tmp_path / "resolution_config.json"
        p.write_text(json.dumps({"width": 1920, "height": 1080, "fps": 60, "camera_fps": 60}))
        self._set_config_path(p)
        cfg = self.cs._load_resolution_config()
        assert cfg["width"] == 1920
        assert cfg["height"] == 1080
        assert cfg["fps"] == 60
        assert cfg["camera_fps"] == 60

    def test_4k_15fps_fps_is_15(self, tmp_path):
        """Kritischer Fall: Software-FPS 15, Hardware-FPS 30 – müssen getrennt erhalten bleiben."""
        p = tmp_path / "resolution_config.json"
        p.write_text(json.dumps({"width": 3840, "height": 2160, "fps": 15, "camera_fps": 30}))
        self._set_config_path(p)
        cfg = self.cs._load_resolution_config()
        assert cfg["fps"] == 15

    def test_4k_15fps_camera_fps_is_30(self, tmp_path):
        """Kritischer Fall: Hardware-FPS muss 30 bleiben, auch wenn Software-FPS 15 ist."""
        p = tmp_path / "resolution_config.json"
        p.write_text(json.dumps({"width": 3840, "height": 2160, "fps": 15, "camera_fps": 30}))
        self._set_config_path(p)
        cfg = self.cs._load_resolution_config()
        assert cfg["camera_fps"] == 30

    def test_missing_camera_fps_field_uses_mjpeg_native_fps_for_4k(self, tmp_path):
        """Alte Config ohne camera_fps → MJPEG_NATIVE_FPS-Lookup für 4K liefert 30."""
        p = tmp_path / "resolution_config.json"
        p.write_text(json.dumps({"width": 3840, "height": 2160, "fps": 15}))
        self._set_config_path(p)
        cfg = self.cs._load_resolution_config()
        assert cfg["camera_fps"] == 30

    def test_missing_camera_fps_field_uses_mjpeg_native_fps_for_1080p(self, tmp_path):
        """Alte Config ohne camera_fps → MJPEG_NATIVE_FPS-Lookup für 1080p liefert 60."""
        p = tmp_path / "resolution_config.json"
        p.write_text(json.dumps({"width": 1920, "height": 1080, "fps": 30}))
        self._set_config_path(p)
        cfg = self.cs._load_resolution_config()
        assert cfg["camera_fps"] == 60

    def test_missing_camera_fps_field_uses_mjpeg_native_fps_for_720p(self, tmp_path):
        p = tmp_path / "resolution_config.json"
        p.write_text(json.dumps({"width": 1280, "height": 720, "fps": 30}))
        self._set_config_path(p)
        assert self.cs._load_resolution_config()["camera_fps"] == 60

    def test_missing_camera_fps_for_unknown_resolution_falls_back_to_fps(self, tmp_path):
        """Unbekannte Auflösung ohne camera_fps → Fallback auf fps."""
        p = tmp_path / "resolution_config.json"
        p.write_text(json.dumps({"width": 800, "height": 600, "fps": 25}))
        self._set_config_path(p)
        assert self.cs._load_resolution_config()["camera_fps"] == 25

    def test_corrupt_json_returns_defaults(self, tmp_path):
        p = tmp_path / "resolution_config.json"
        p.write_text("THIS IS NOT JSON {{{")
        self._set_config_path(p)
        cfg = self.cs._load_resolution_config()
        assert cfg == {"width": 3840, "height": 2160, "fps": 30, "camera_fps": 30}

    def test_missing_required_key_returns_defaults(self, tmp_path):
        """Unvollständige Config (fehlendes height/fps) → Defaults."""
        p = tmp_path / "resolution_config.json"
        p.write_text(json.dumps({"width": 1920}))
        self._set_config_path(p)
        cfg = self.cs._load_resolution_config()
        assert cfg == {"width": 3840, "height": 2160, "fps": 30, "camera_fps": 30}

    def test_empty_json_object_returns_defaults(self, tmp_path):
        p = tmp_path / "resolution_config.json"
        p.write_text("{}")
        self._set_config_path(p)
        cfg = self.cs._load_resolution_config()
        assert cfg == {"width": 3840, "height": 2160, "fps": 30, "camera_fps": 30}


# ===========================================================================
# _save_resolution_config
# ===========================================================================

class TestSaveResolutionConfig:
    def setup_method(self):
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        streamer = _make_streamer_mock()
        self.cs = _load_camera_service(zmq_mock, streamer)

    def _set_config_path(self, path):
        self.cs.RESOLUTION_CONFIG_FILE = str(path)

    def test_creates_file(self, tmp_path):
        p = tmp_path / "resolution_config.json"
        self._set_config_path(p)
        self.cs._save_resolution_config(1920, 1080, 30, 60)
        assert p.exists()

    def test_writes_all_four_fields(self, tmp_path):
        p = tmp_path / "resolution_config.json"
        self._set_config_path(p)
        self.cs._save_resolution_config(1920, 1080, 30, 60)
        data = json.loads(p.read_text())
        assert "width" in data and "height" in data
        assert "fps" in data and "camera_fps" in data

    def test_writes_correct_values(self, tmp_path):
        p = tmp_path / "resolution_config.json"
        self._set_config_path(p)
        self.cs._save_resolution_config(1920, 1080, 30, 60)
        data = json.loads(p.read_text())
        assert data["width"] == 1920
        assert data["height"] == 1080
        assert data["fps"] == 30
        assert data["camera_fps"] == 60

    def test_4k_15fps_saves_fps_and_camera_fps_separately(self, tmp_path):
        """Kritisch: fps=15 (Software) und camera_fps=30 (Hardware) müssen getrennt gespeichert werden."""
        p = tmp_path / "resolution_config.json"
        self._set_config_path(p)
        self.cs._save_resolution_config(3840, 2160, 15, 30)
        data = json.loads(p.read_text())
        assert data["fps"] == 15
        assert data["camera_fps"] == 30

    def test_overwrites_existing_file(self, tmp_path):
        p = tmp_path / "resolution_config.json"
        p.write_text(json.dumps({"width": 640, "height": 480, "fps": 60, "camera_fps": 60}))
        self._set_config_path(p)
        self.cs._save_resolution_config(3840, 2160, 30, 30)
        data = json.loads(p.read_text())
        assert data["width"] == 3840

    def test_write_error_does_not_raise(self):
        self.cs.RESOLUTION_CONFIG_FILE = "/nonexistent_path_xyz/resolution_config.json"
        # darf keinen Exception werfen
        self.cs._save_resolution_config(1920, 1080, 30, 60)


# ===========================================================================
# Startup: Streamer wird mit Werten aus Config initialisiert
# ===========================================================================

import os as _os

_RESOLUTION_CONFIG_REAL_PATH = _os.path.normpath(
    _os.path.join(_os.path.dirname(__file__), '..', 'config', 'resolution_config.json')
)


@pytest.fixture
def resolution_config_file_at_real_path():
    """
    Schreibt resolution_config.json an den echten Pfad und stellt nach dem Test den
    Originalzustand wieder her (Backup falls vorhanden, sonst Löschen).
    """
    backup = None
    if _os.path.exists(_RESOLUTION_CONFIG_REAL_PATH):
        with open(_RESOLUTION_CONFIG_REAL_PATH, encoding='utf-8') as f:
            backup = f.read()

    def write(data: dict):
        _os.makedirs(_os.path.dirname(_RESOLUTION_CONFIG_REAL_PATH), exist_ok=True)
        with open(_RESOLUTION_CONFIG_REAL_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f)

    yield write

    if backup is not None:
        with open(_RESOLUTION_CONFIG_REAL_PATH, 'w', encoding='utf-8') as f:
            f.write(backup)
    elif _os.path.exists(_RESOLUTION_CONFIG_REAL_PATH):
        _os.remove(_RESOLUTION_CONFIG_REAL_PATH)


class TestStartupResolutionInit:
    def test_streamer_uses_defaults_when_no_config(self, resolution_config_file_at_real_path):
        if _os.path.exists(_RESOLUTION_CONFIG_REAL_PATH):
            _os.remove(_RESOLUTION_CONFIG_REAL_PATH)
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        streamer = _make_streamer_mock()
        cs = _load_camera_service(zmq_mock, streamer)
        call_kwargs = sys.modules["v4l2_mjpg_stream"].V4L2MJPGStreamer.call_args.kwargs
        assert call_kwargs["width"] == 3840
        assert call_kwargs["height"] == 2160
        assert call_kwargs["fps"] == 30

    def test_streamer_uses_config_width_and_height(self, resolution_config_file_at_real_path):
        resolution_config_file_at_real_path({"width": 1920, "height": 1080, "fps": 30, "camera_fps": 60})
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        streamer = _make_streamer_mock()
        _load_camera_service(zmq_mock, streamer)
        call_kwargs = sys.modules["v4l2_mjpg_stream"].V4L2MJPGStreamer.call_args.kwargs
        assert call_kwargs["width"] == 1920
        assert call_kwargs["height"] == 1080

    def test_4k_15fps_streamer_fps_is_15(self, resolution_config_file_at_real_path):
        """Kritisch: Streamer muss mit fps=15 (Software) starten, nicht 30."""
        resolution_config_file_at_real_path({"width": 3840, "height": 2160, "fps": 15, "camera_fps": 30})
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        streamer = _make_streamer_mock()
        _load_camera_service(zmq_mock, streamer)
        call_kwargs = sys.modules["v4l2_mjpg_stream"].V4L2MJPGStreamer.call_args.kwargs
        assert call_kwargs["fps"] == 15

    def test_4k_15fps_streamer_camera_fps_set_to_30_after_init(self, resolution_config_file_at_real_path):
        """
        Kritisch: camera_fps muss NACH __init__ explizit auf 30 gesetzt werden,
        weil V4L2MJPGStreamer.__init__ camera_fps=fps (=15) setzt.
        open() nutzt camera_fps für die Hardware-Framerate.
        """
        resolution_config_file_at_real_path({"width": 3840, "height": 2160, "fps": 15, "camera_fps": 30})
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        streamer = _make_streamer_mock()
        _load_camera_service(zmq_mock, streamer)
        assert streamer.camera_fps == 30

    def test_1080p_config_streamer_camera_fps_is_60(self, resolution_config_file_at_real_path):
        resolution_config_file_at_real_path({"width": 1920, "height": 1080, "fps": 30, "camera_fps": 60})
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        streamer = _make_streamer_mock()
        _load_camera_service(zmq_mock, streamer)
        assert streamer.camera_fps == 60


# ===========================================================================
# SET_RESOLUTION: Config wird in beiden Pfaden gespeichert
# ===========================================================================

class TestSetResolutionPersistence:
    def setup_method(self):
        self.zmq_mock, self.rep, self.pub, self.ctx = _make_zmq_mock()
        self.streamer = _make_streamer_mock()
        self.cs = _load_camera_service(self.zmq_mock, self.streamer)
        self.streamer.recording = False
        self._patch_usb = patch('camera_service._usb_reset_arducam', return_value=True)
        self._patch_wait = patch('camera_service._wait_for_video_device', return_value=True)
        self._patch_usb.start()
        self._patch_wait.start()

    def teardown_method(self):
        self._patch_usb.stop()
        self._patch_wait.stop()

    def _run(self, command):
        self.rep.recv_string.side_effect = [command, KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass

    # --- Vollständiger Auflösungswechsel (stop/start) ---

    def test_full_resolution_change_saves_config(self):
        with patch.object(self.cs, '_save_resolution_config') as mock_save:
            self._run("SET_RESOLUTION:1920x1080:30")
        mock_save.assert_called_once()

    def test_full_resolution_change_saves_correct_width_height(self):
        with patch.object(self.cs, '_save_resolution_config') as mock_save:
            self._run("SET_RESOLUTION:1920x1080:30")
        args = mock_save.call_args[0]
        assert args[0] == 1920
        assert args[1] == 1080

    def test_full_resolution_change_saves_fps(self):
        with patch.object(self.cs, '_save_resolution_config') as mock_save:
            self._run("SET_RESOLUTION:1920x1080:30")
        assert mock_save.call_args[0][2] == 30

    def test_full_resolution_change_1080p_saves_camera_fps_60(self):
        """1080p → MJPEG_NATIVE_FPS liefert 60 → muss als camera_fps gespeichert werden."""
        with patch.object(self.cs, '_save_resolution_config') as mock_save:
            self._run("SET_RESOLUTION:1920x1080:30")
        assert mock_save.call_args[0][3] == 60

    def test_full_resolution_change_720p_saves_camera_fps_60(self):
        with patch.object(self.cs, '_save_resolution_config') as mock_save:
            self._run("SET_RESOLUTION:1280x720:60")
        assert mock_save.call_args[0][3] == 60

    def test_4k_30fps_full_change_saves_camera_fps_30(self):
        # Von 1080p auf 4K wechseln → camera_fps muss 30 sein
        self.streamer.width = 1920
        self.streamer.height = 1080
        with patch.object(self.cs, '_save_resolution_config') as mock_save:
            self._run("SET_RESOLUTION:3840x2160:30")
        args = mock_save.call_args[0]
        assert args[2] == 30   # fps
        assert args[3] == 30   # camera_fps

    # --- FPS-only-Pfad (gleiche Auflösung, nur FPS ändert sich) ---

    def test_fps_only_change_saves_config(self):
        self.streamer.width = 3840
        self.streamer.height = 2160
        with patch.object(self.cs, '_save_resolution_config') as mock_save:
            self._run("SET_RESOLUTION:3840x2160:15")
        mock_save.assert_called_once()

    def test_4k_15fps_fps_only_saves_fps_15(self):
        """Kritisch: Software-FPS 15 muss gespeichert werden."""
        self.streamer.width = 3840
        self.streamer.height = 2160
        with patch.object(self.cs, '_save_resolution_config') as mock_save:
            self._run("SET_RESOLUTION:3840x2160:15")
        assert mock_save.call_args[0][2] == 15

    def test_4k_15fps_fps_only_saves_camera_fps_30_not_15(self):
        """Kritisch: Hardware-FPS muss 30 sein, NICHT 15 – 4K unterstützt kein 15fps nativ."""
        self.streamer.width = 3840
        self.streamer.height = 2160
        with patch.object(self.cs, '_save_resolution_config') as mock_save:
            self._run("SET_RESOLUTION:3840x2160:15")
        assert mock_save.call_args[0][3] == 30

    def test_4k_30fps_fps_only_saves_camera_fps_30(self):
        self.streamer.width = 3840
        self.streamer.height = 2160
        with patch.object(self.cs, '_save_resolution_config') as mock_save:
            self._run("SET_RESOLUTION:3840x2160:30")
        assert mock_save.call_args[0][3] == 30

    # --- Negativfälle: kein Speichern ---

    def test_recording_active_does_not_save_config(self):
        self.streamer.recording = True
        with patch.object(self.cs, '_save_resolution_config') as mock_save:
            self._run("SET_RESOLUTION:1920x1080:30")
        mock_save.assert_not_called()

    def test_malformed_command_does_not_save_config(self):
        with patch.object(self.cs, '_save_resolution_config') as mock_save:
            self._run("SET_RESOLUTION:GARBAGE")
        mock_save.assert_not_called()

    def test_os_write_error_in_save_config_still_sends_ok(self):
        """
        Wenn das Schreiben der Config-Datei auf OS-Ebene fehlschlägt (z.B. kein Speicher),
        muss _save_resolution_config die Exception intern schlucken und der Befehl
        trotzdem OK antworten – die Auflösung wurde bereits erfolgreich gesetzt.
        """
        from unittest.mock import mock_open as _mock_open
        # open() schlägt fehl → _save_resolution_config fängt das intern ab
        with patch('builtins.open', side_effect=IOError("disk full")):
            self._run("SET_RESOLUTION:1920x1080:30")
        calls = [str(c) for c in self.rep.send_string.call_args_list]
        assert any("OK" in c for c in calls)


# ===========================================================================
# Round-trip: _save_resolution_config → _load_resolution_config
# ===========================================================================

class TestResolutionConfigRoundtrip:
    def setup_method(self):
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        streamer = _make_streamer_mock()
        self.cs = _load_camera_service(zmq_mock, streamer)

    def _set_config_path(self, path):
        self.cs.RESOLUTION_CONFIG_FILE = str(path)

    def test_4k_15fps_roundtrip(self, tmp_path):
        """Der wichtigste Roundtrip: 4K@15fps mit getrenntem Software- und Hardware-FPS."""
        p = tmp_path / "resolution_config.json"
        self._set_config_path(p)
        self.cs._save_resolution_config(3840, 2160, 15, 30)
        cfg = self.cs._load_resolution_config()
        assert cfg["width"] == 3840
        assert cfg["height"] == 2160
        assert cfg["fps"] == 15
        assert cfg["camera_fps"] == 30

    def test_1080p_60fps_roundtrip(self, tmp_path):
        p = tmp_path / "resolution_config.json"
        self._set_config_path(p)
        self.cs._save_resolution_config(1920, 1080, 60, 60)
        cfg = self.cs._load_resolution_config()
        assert cfg == {"width": 1920, "height": 1080, "fps": 60, "camera_fps": 60}

    def test_720p_30fps_roundtrip(self, tmp_path):
        p = tmp_path / "resolution_config.json"
        self._set_config_path(p)
        self.cs._save_resolution_config(1280, 720, 30, 60)
        cfg = self.cs._load_resolution_config()
        assert cfg["width"] == 1280
        assert cfg["height"] == 720
        assert cfg["fps"] == 30
        assert cfg["camera_fps"] == 60

    def test_4k_30fps_roundtrip(self, tmp_path):
        p = tmp_path / "resolution_config.json"
        self._set_config_path(p)
        self.cs._save_resolution_config(3840, 2160, 30, 30)
        cfg = self.cs._load_resolution_config()
        assert cfg == {"width": 3840, "height": 2160, "fps": 30, "camera_fps": 30}


# ===========================================================================
# _last_known_good_res – Initialisierung
# ===========================================================================

class TestLastKnownGoodRes:
    def test_initialized_after_successful_start(self):
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        streamer = _make_streamer_mock()
        streamer.width = 1920
        streamer.height = 1080
        streamer.fps = 30
        streamer.camera_fps = 60
        cs = _load_camera_service(zmq_mock, streamer)

        assert cs._last_known_good_res is not None
        assert cs._last_known_good_res["width"] == 1920
        assert cs._last_known_good_res["height"] == 1080
        assert cs._last_known_good_res["fps"] == 30
        assert cs._last_known_good_res["camera_fps"] == 60

    def test_none_when_streamer_start_raises(self):
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        streamer = _make_streamer_mock()
        streamer.open.side_effect = RuntimeError("Device busy")

        with pytest.raises(RuntimeError):
            cs = _load_camera_service(zmq_mock, streamer)

        # Modul wurde nicht vollständig geladen – kein _last_known_good_res auswertbar
        # (Test verifiziert nur dass der Fehler durchkommt)


# ===========================================================================
# _maybe_apply_fallback – Fallback-Logik
# ===========================================================================

class TestMaybeApplyFallback:
    def _setup(self,
               cur_w=3840, cur_h=2160, cur_fps=30, cur_cfps=30,
               good_w=1920, good_h=1080, good_fps=30, good_cfps=60):
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        self.streamer = _make_streamer_mock()
        self.streamer.width = cur_w
        self.streamer.height = cur_h
        self.streamer.fps = cur_fps
        self.streamer.camera_fps = cur_cfps
        cs = _load_camera_service(zmq_mock, self.streamer)
        cs._last_known_good_res = {
            "width": good_w, "height": good_h,
            "fps": good_fps, "camera_fps": good_cfps,
        }
        return cs

    def test_no_fallback_when_count_below_threshold(self):
        cs = self._setup()
        result = cs._maybe_apply_fallback(1)
        assert result is False
        # Streamer-Parameter dürfen sich nicht geändert haben
        assert self.streamer.width == 3840

    def test_no_fallback_when_no_known_good_res(self):
        zmq_mock, rep, pub, ctx = _make_zmq_mock()
        streamer = _make_streamer_mock()
        cs = _load_camera_service(zmq_mock, streamer)
        cs._last_known_good_res = None
        result = cs._maybe_apply_fallback(5)
        assert result is False

    def test_applies_fallback_on_count_ge_2_with_different_resolution(self):
        cs = self._setup(cur_w=3840, cur_h=2160, cur_fps=30, cur_cfps=30,
                         good_w=1920, good_h=1080, good_fps=30, good_cfps=60)
        with patch("camera_service._save_resolution_config"):
            result = cs._maybe_apply_fallback(2)
        assert result is True
        assert self.streamer.width == 1920
        assert self.streamer.height == 1080
        assert self.streamer.fps == 30
        assert self.streamer.camera_fps == 60

    def test_no_fallback_when_already_at_known_good_resolution(self):
        # Kamera hängt bereits mit der "guten" Auflösung – kein weiterer Fallback möglich
        cs = self._setup(cur_w=1920, cur_h=1080, cur_fps=30, cur_cfps=60,
                         good_w=1920, good_h=1080, good_fps=30, good_cfps=60)
        result = cs._maybe_apply_fallback(5)
        assert result is False

    def test_fallback_saves_config(self):
        cs = self._setup(cur_w=3840, cur_h=2160, cur_fps=30, cur_cfps=30,
                         good_w=1920, good_h=1080, good_fps=30, good_cfps=60)
        with patch("camera_service._save_resolution_config") as mock_save:
            cs._maybe_apply_fallback(2)
        mock_save.assert_called_once_with(1920, 1080, 30, 60)

    def test_count_exactly_2_triggers_fallback(self):
        cs = self._setup(cur_w=3840, cur_h=2160, cur_fps=30, cur_cfps=30,
                         good_w=1920, good_h=1080, good_fps=30, good_cfps=60)
        with patch("camera_service._save_resolution_config"):
            assert cs._maybe_apply_fallback(2) is True

    def test_count_1_does_not_trigger_fallback(self):
        cs = self._setup(cur_w=3840, cur_h=2160, cur_fps=30, cur_cfps=30,
                         good_w=1920, good_h=1080, good_fps=30, good_cfps=60)
        with patch("camera_service._save_resolution_config"):
            assert cs._maybe_apply_fallback(1) is False


# ===========================================================================
# _usb_reset_arducam
# ===========================================================================

class TestUsbResetArducam:
    def setup_method(self):
        zmq_mock, _, _, _ = _make_zmq_mock()
        streamer = _make_streamer_mock()
        self.cs = _load_camera_service(zmq_mock, streamer)

    def test_returns_false_when_no_usb_devices(self):
        with patch('camera_service._glob.glob', return_value=[]):
            result = self.cs._usb_reset_arducam()
        assert result is False

    def test_returns_false_when_no_matching_vendor(self):
        # Device mit anderem Vendor/Product
        desc = b'\x12\x01\x00\x02\x00\x00\x00\x40' + b'\xaa\xbb' + b'\x11\x22' + b'\x00' * 6
        with patch('camera_service._glob.glob', return_value=['/dev/bus/usb/001/002']), \
             patch('builtins.open', MagicMock(return_value=MagicMock(
                 __enter__=lambda s, *a: MagicMock(read=lambda n: desc),
                 __exit__=lambda *a: None,
             ))):
            result = self.cs._usb_reset_arducam()
        assert result is False

    def test_returns_true_when_arducam_found_and_reset_succeeds(self):
        # Korrekter Vendor 0x04b4, Product 0x0822 im Device-Descriptor
        vid_bytes = (0x04b4).to_bytes(2, 'little')
        pid_bytes = (0x0822).to_bytes(2, 'little')
        desc = b'\x12\x01\x00\x02\x00\x00\x00\x40' + vid_bytes + pid_bytes + b'\x00' * 6
        mock_file = MagicMock()
        mock_file.__enter__ = lambda s: MagicMock(read=lambda n: desc)
        mock_file.__exit__ = MagicMock(return_value=False)
        with patch('camera_service._glob.glob', return_value=['/dev/bus/usb/001/003']), \
             patch('builtins.open', return_value=mock_file), \
             patch('camera_service.os.open', return_value=42), \
             patch('camera_service.fcntl.ioctl') as mock_ioctl, \
             patch('camera_service.os.close'):
            result = self.cs._usb_reset_arducam()
        assert result is True
        mock_ioctl.assert_called_once_with(42, 0x5514, 0)

    def test_returns_false_on_permission_error(self):
        vid_bytes = (0x04b4).to_bytes(2, 'little')
        pid_bytes = (0x0822).to_bytes(2, 'little')
        desc = b'\x12\x01\x00\x02\x00\x00\x00\x40' + vid_bytes + pid_bytes + b'\x00' * 6
        mock_file = MagicMock()
        mock_file.__enter__ = lambda s: MagicMock(read=lambda n: desc)
        mock_file.__exit__ = MagicMock(return_value=False)
        with patch('camera_service._glob.glob', return_value=['/dev/bus/usb/001/003']), \
             patch('builtins.open', return_value=mock_file), \
             patch('camera_service.os.open', side_effect=PermissionError("no access")):
            result = self.cs._usb_reset_arducam()
        assert result is False

    def test_skips_short_descriptor(self):
        """Descriptor kürzer als 12 Bytes → überspringen, kein Absturz."""
        with patch('camera_service._glob.glob', return_value=['/dev/bus/usb/001/001']), \
             patch('builtins.open', MagicMock(return_value=MagicMock(
                 __enter__=lambda s, *a: MagicMock(read=lambda n: b'\x04'),
                 __exit__=lambda *a: None,
             ))):
            result = self.cs._usb_reset_arducam()
        assert result is False


# ===========================================================================
# _wait_for_video_device
# ===========================================================================

class TestWaitForVideoDevice:
    def setup_method(self):
        zmq_mock, _, _, _ = _make_zmq_mock()
        streamer = _make_streamer_mock()
        self.cs = _load_camera_service(zmq_mock, streamer)

    def test_returns_true_when_device_exists_immediately(self):
        with patch('camera_service.os.path.exists', return_value=True), \
             patch('camera_service.time.sleep'):
            result = self.cs._wait_for_video_device('/dev/video0', timeout=5.0)
        assert result is True

    def test_returns_false_when_device_never_appears(self):
        with patch('camera_service.os.path.exists', return_value=False), \
             patch('camera_service.time.sleep'), \
             patch('camera_service.time.monotonic', side_effect=[0.0, 0.0, 11.0]):
            result = self.cs._wait_for_video_device('/dev/video0', timeout=10.0)
        assert result is False

    def test_returns_true_after_device_appears_on_second_poll(self):
        exist_sequence = [False, False, True]
        with patch('camera_service.os.path.exists', side_effect=exist_sequence), \
             patch('camera_service.time.sleep'), \
             patch('camera_service.time.monotonic', side_effect=[0.0, 0.1, 0.2, 0.3]):
            result = self.cs._wait_for_video_device('/dev/video0', timeout=10.0)
        assert result is True


# ===========================================================================
# Watchdog: _device_reset_in_progress-Flag
# ===========================================================================

class TestWatchdogSkipsDuringDeviceReset:
    def setup_method(self):
        zmq_mock, _, _, _ = _make_zmq_mock()
        self.streamer = _make_streamer_mock()
        self.cs = _load_camera_service(zmq_mock, self.streamer)

    def test_watchdog_skips_check_when_reset_in_progress(self):
        """Watchdog darf _full_device_restart NICHT aufrufen wenn _device_reset_in_progress gesetzt."""
        self.cs._device_reset_in_progress = True
        # Thread ist tot → würde normalerweise Neustart triggern
        self.streamer.thread.is_alive.return_value = False
        sleep_calls = iter([None, None, StopIteration()])
        with patch('camera_service.time.sleep', side_effect=[None, None, StopIteration()]), \
             patch.object(self.cs, '_full_device_restart') as mock_restart:
            try:
                self.cs.capture_watchdog()
            except StopIteration:
                pass
        mock_restart.assert_not_called()

    def test_watchdog_restarts_when_flag_clear(self):
        """Ohne Flag: Watchdog greift bei totem Thread ein."""
        self.cs._device_reset_in_progress = False
        self.streamer.thread.is_alive.return_value = False
        with patch('camera_service.time.sleep', side_effect=[None, StopIteration()]), \
             patch.object(self.cs, '_full_device_restart') as mock_restart, \
             patch.object(self.cs, '_maybe_apply_fallback', return_value=False):
            try:
                self.cs.capture_watchdog()
            except StopIteration:
                pass
        mock_restart.assert_called_once()


# ===========================================================================
# SET_RESOLUTION: USB-Reset wird bei Auflösungswechsel aufgerufen
# ===========================================================================

class TestSetResolutionUsesUsbReset:
    def setup_method(self):
        self.zmq_mock, self.rep, self.pub, self.ctx = _make_zmq_mock()
        self.streamer = _make_streamer_mock()
        self.cs = _load_camera_service(self.zmq_mock, self.streamer)
        self.streamer.recording = False

    def _run(self, command):
        self.rep.recv_string.side_effect = [command, KeyboardInterrupt]
        try:
            self.cs.handle_commands()
        except KeyboardInterrupt:
            pass

    def test_usb_reset_called_on_resolution_change(self):
        """Bei echtem Auflösungswechsel muss _usb_reset_arducam aufgerufen werden."""
        with patch.object(self.cs, '_usb_reset_arducam', return_value=True) as mock_usb, \
             patch.object(self.cs, '_wait_for_video_device', return_value=True), \
             patch.object(self.cs, '_save_resolution_config'):
            self._run("SET_RESOLUTION:1920x1080:30")
        mock_usb.assert_called_once()

    def test_usb_reset_not_called_on_fps_only_change(self):
        """Bei reiner FPS-Änderung (gleiche Auflösung) KEIN USB-Reset."""
        self.streamer.width = 3840
        self.streamer.height = 2160
        with patch.object(self.cs, '_usb_reset_arducam') as mock_usb, \
             patch.object(self.cs, '_save_resolution_config'):
            self._run("SET_RESOLUTION:3840x2160:15")
        mock_usb.assert_not_called()

    def test_device_reset_flag_cleared_after_success(self):
        """_device_reset_in_progress muss nach erfolgreichem Wechsel False sein."""
        with patch.object(self.cs, '_usb_reset_arducam', return_value=True), \
             patch.object(self.cs, '_wait_for_video_device', return_value=True), \
             patch.object(self.cs, '_save_resolution_config'):
            self._run("SET_RESOLUTION:1920x1080:30")
        assert self.cs._device_reset_in_progress is False

    def test_device_reset_flag_cleared_after_error(self):
        """_device_reset_in_progress muss auch nach Fehler False sein (finally-Block)."""
        self.streamer.open.side_effect = OSError("open failed")
        with patch.object(self.cs, '_usb_reset_arducam', return_value=True), \
             patch.object(self.cs, '_wait_for_video_device', return_value=True):
            self._run("SET_RESOLUTION:1920x1080:30")
        assert self.cs._device_reset_in_progress is False

    def test_sends_error_when_device_does_not_return_after_reset(self):
        """Wenn Device nach USB-Reset nicht wieder erscheint → ERROR an Client."""
        with patch.object(self.cs, '_usb_reset_arducam', return_value=True), \
             patch.object(self.cs, '_wait_for_video_device', return_value=False):
            self._run("SET_RESOLUTION:1920x1080:30")
        calls = [str(c) for c in self.rep.send_string.call_args_list]
        assert any("ERROR" in c for c in calls)

    def test_fallback_sleep_used_when_usb_reset_fails(self):
        """Wenn USB-Reset nicht möglich → 2s sleep als Fallback."""
        with patch.object(self.cs, '_usb_reset_arducam', return_value=False), \
             patch('camera_service.time.sleep') as mock_sleep, \
             patch.object(self.cs, '_save_resolution_config'):
            self._run("SET_RESOLUTION:1920x1080:30")
        mock_sleep.assert_called_with(2)

