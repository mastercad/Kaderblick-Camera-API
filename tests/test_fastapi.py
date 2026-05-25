"""
Tests für fastapi_app – alle REST-Endpunkte

Hardware-Mocks (lgpio, v4l2, numpy, cv2) werden durch tests/conftest.py gesetzt.
zmq und subprocess werden in diesem Modul per patch gesteuert.

Import-Strategie:
    Da fastapi_app zmq und lgpio beim Import benutzt (Sockets öffnen, GPIO init),
    werden diese Module komplett durch MagicMocks ersetzt BEVOR das Modul
    importiert wird. conftest.py übernimmt lgpio, hier wird zmq gepatcht.
"""
import json
import sys
from unittest.mock import MagicMock, patch

import pytest

# -----------------------------------------------------------------------
# zmq auf Modul-Ebene mocken (bevor fastapi_app importiert wird)
# -----------------------------------------------------------------------
_zmq_mock = MagicMock()
_zmq_mock.Context.return_value = MagicMock()
_zmq_mock.REQ = 3
_zmq_mock.REP = 4
_zmq_mock.PUB = 1
_zmq_mock.SUB = 2
_zmq_mock.NOBLOCK = 1
_zmq_mock.SUBSCRIBE = 6
_zmq_mock.Again = type("Again", (Exception,), {})
sys.modules["zmq"] = _zmq_mock

# -----------------------------------------------------------------------
# psutil minimal mocken (os.statvfs auf Testrechner möglicherweise anders)
# -----------------------------------------------------------------------
# psutil ist auf dem Testrechner wahrscheinlich installiert – kein Mock nötig.

# -----------------------------------------------------------------------
# fastapi_app importieren und TestClient anlegen
# -----------------------------------------------------------------------
import fastapi_app  # noqa: E402
import hardware     # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(fastapi_app.app)


# ===========================================================================
# Hilfsfunktionen
# ===========================================================================

def _zmq_rep_returns(response: str):
    """Konfiguriert den req_socket-Mock so, dass poll=True und recv=response."""
    fastapi_app.req_socket.poll.return_value = 1
    fastapi_app.req_socket.recv_string.return_value = response


def _zmq_rep_timeout():
    """Konfiguriert den req_socket-Mock so, dass poll einen Timeout liefert."""
    fastapi_app.req_socket.poll.return_value = 0


def _make_status_json(**kwargs) -> str:
    """Erzeugt einen minimalen STATUS-JSON-String."""
    defaults = {
        "recording": False,
        "recording_flag": False,
        "capture_thread_alive": True,
        "frames_captured": 100,
        "frames_written": 80,
        "last_frame_age_s": 0.5,
        "capture_error": None,
        "audio_available": True,
        "audio_exit_code": None,
        "audio_error": None,
        "video_file_bytes": 1024,
        "width": 3840,
        "height": 2160,
        "fps": 30,
    }
    defaults.update(kwargs)
    return json.dumps(defaults)


# ===========================================================================
# GET / – Root / Info
# ===========================================================================

class TestRoot:
    def test_returns_200(self):
        r = client.get("/")
        assert r.status_code == 200

    def test_contains_version(self):
        r = client.get("/")
        assert r.json()["version"] == "1.0"

    def test_contains_hardware_section(self):
        r = client.get("/")
        assert "hardware" in r.json()

    def test_contains_zmq_section(self):
        r = client.get("/")
        assert "zmq" in r.json()

    def test_servo_pin_in_hardware(self):
        r = client.get("/")
        assert r.json()["hardware"]["servo"]["pin"] == 18

    def test_stepper_pins_in_hardware(self):
        r = client.get("/")
        assert r.json()["hardware"]["stepper"]["pins"] == [17, 27, 20, 21]


# ===========================================================================
# POST /start_record
# ===========================================================================

class TestStartRecord:
    def test_returns_200_on_success(self):
        _zmq_rep_returns("OK")
        r = client.post("/start_record")
        assert r.status_code == 200

    def test_forwards_camera_service_response(self):
        _zmq_rep_returns("RECORDING_STARTED")
        r = client.post("/start_record")
        assert r.json()["status"] == "RECORDING_STARTED"

    def test_sends_start_to_zmq(self):
        _zmq_rep_returns("OK")
        fastapi_app.req_socket.send_string.reset_mock()
        client.post("/start_record")
        fastapi_app.req_socket.send_string.assert_called_with("START")


# ===========================================================================
# POST /stop_record
# ===========================================================================

class TestStopRecord:
    def test_returns_200_on_success(self):
        _zmq_rep_returns("OK")
        r = client.post("/stop_record")
        assert r.status_code == 200

    def test_forwards_camera_service_response(self):
        _zmq_rep_returns("STOPPED")
        r = client.post("/stop_record")
        assert r.json()["status"] == "STOPPED"

    def test_sends_stop_to_zmq(self):
        _zmq_rep_returns("OK")
        fastapi_app.req_socket.send_string.reset_mock()
        client.post("/stop_record")
        fastapi_app.req_socket.send_string.assert_called_with("STOP")


# ===========================================================================
# GET /servo
# ===========================================================================

class TestGetServo:
    def test_returns_current_angle(self):
        hardware.current_servo_angle = 90
        r = client.get("/servo")
        assert r.status_code == 200
        assert r.json()["angle"] == 90


# ===========================================================================
# POST /servo/absolute
# ===========================================================================

class TestServoAbsolute:
    def test_valid_angle_90(self):
        with patch.object(fastapi_app, "move_servo_absolute") as m:
            r = client.post("/servo/absolute", json={"angle": 90})
        assert r.status_code == 200
        m.assert_called_once_with(90)

    def test_valid_angle_0(self):
        with patch.object(fastapi_app, "move_servo_absolute"):
            r = client.post("/servo/absolute", json={"angle": 0})
        assert r.status_code == 200

    def test_valid_angle_180(self):
        with patch.object(fastapi_app, "move_servo_absolute"):
            r = client.post("/servo/absolute", json={"angle": 180})
        assert r.status_code == 200

    def test_invalid_angle_181(self):
        r = client.post("/servo/absolute", json={"angle": 181})
        assert r.status_code in (400, 422)  # Pydantic v1/v2 differ

    def test_invalid_angle_minus_1(self):
        r = client.post("/servo/absolute", json={"angle": -1})
        assert r.status_code in (400, 422)  # Pydantic v1/v2 differ


# ===========================================================================
# POST /servo (relativ)
# ===========================================================================

class TestServoRelative:
    def test_positive_degrees(self):
        with patch.object(fastapi_app, "move_servo_relative") as m:
            r = client.post("/servo", json={"degrees": 10})
        assert r.status_code == 200
        m.assert_called_once_with(10)

    def test_negative_degrees(self):
        with patch.object(fastapi_app, "move_servo_relative") as m:
            r = client.post("/servo", json={"degrees": -5})
        assert r.status_code == 200
        m.assert_called_once_with(-5)

    def test_zero_degrees(self):
        with patch.object(fastapi_app, "move_servo_relative") as m:
            r = client.post("/servo", json={"degrees": 0})
        assert r.status_code == 200


# ===========================================================================
# GET /stepper
# ===========================================================================

class TestGetStepper:
    def test_returns_current_position(self):
        hardware.current_stepper_pos = 42
        r = client.get("/stepper")
        assert r.status_code == 200
        assert r.json()["current_position"] == 42


# ===========================================================================
# POST /stepper (relativ)
# ===========================================================================

class TestStepperRelative:
    def test_steps_sent(self):
        with patch.object(fastapi_app, "move_stepper_relative") as m:
            r = client.post("/stepper", json={"steps": 100})
        assert r.status_code == 200
        m.assert_called_once_with(100, 0.002)

    def test_custom_delay(self):
        with patch.object(fastapi_app, "move_stepper_relative") as m:
            r = client.post("/stepper", json={"steps": 50, "delay": 0.005})
        m.assert_called_once_with(50, 0.005)


# ===========================================================================
# POST /stepper/absolute
# ===========================================================================

class TestStepperAbsolute:
    def test_absolute_position(self):
        with patch.object(fastapi_app, "move_stepper_absolute") as m:
            r = client.post("/stepper/absolute", json={"position": 200})
        assert r.status_code == 200
        m.assert_called_once_with(200, 0.002)


# ===========================================================================
# GET /camera-position-status
# ===========================================================================

class TestCameraPositionStatus:
    def test_returns_angle_and_position(self):
        hardware.current_servo_angle = 45
        hardware.current_stepper_pos = 77
        r = client.get("/camera-position-status")
        assert r.status_code == 200
        data = r.json()
        assert data["y-angle"] == 45
        assert data["x-position"] == 77


# ===========================================================================
# GET /camera/controls
# ===========================================================================

class TestGetCameraControls:
    def test_returns_controls_when_cached(self):
        fastapi_app.cached_camera_controls = {
            "contrast": {"name": "contrast", "min": 0, "max": 4, "default": 2, "value": 2, "supported": True}
        }
        r = client.get("/camera/controls")
        assert r.status_code == 200
        assert "contrast" in r.json()["controls"]

    def test_503_when_cache_empty(self):
        fastapi_app.cached_camera_controls = {}
        r = client.get("/camera/controls")
        assert r.status_code == 503

    def test_device_in_response(self):
        fastapi_app.cached_camera_controls = {
            "contrast": {"name": "contrast", "min": 0, "max": 4, "default": 2, "value": 2, "supported": True}
        }
        r = client.get("/camera/controls")
        assert r.json()["device"] == "/dev/video0"


# ===========================================================================
# POST /camera/controls
# ===========================================================================

class TestSetCameraControl:
    def setup_method(self):
        fastapi_app.cached_camera_controls = {
            "contrast": {"name": "contrast", "min": 0, "max": 4, "default": 2, "value": 2, "supported": True},
            "saturation": {"name": "saturation", "min": 0, "max": 255, "default": 64, "value": 64, "supported": True},
        }

    def test_unknown_control_returns_400(self):
        r = client.post("/camera/controls", json={"control": "unknown_ctrl", "value": 1})
        assert r.status_code == 400

    def test_control_not_in_cache_returns_404(self):
        # gain ist supported aber nicht im Cache
        r = client.post("/camera/controls", json={"control": "gain", "value": 50})
        assert r.status_code == 404

    def test_value_below_min_returns_400(self):
        r = client.post("/camera/controls", json={"control": "contrast", "value": -1})
        assert r.status_code == 400

    def test_value_above_max_returns_400(self):
        r = client.post("/camera/controls", json={"control": "contrast", "value": 99})
        assert r.status_code == 400

    def test_v4l2ctl_failure_returns_500(self):
        result = MagicMock()
        result.returncode = 1
        result.stderr = "error"
        with patch("subprocess.run", return_value=result):
            r = client.post("/camera/controls", json={"control": "contrast", "value": 2})
        assert r.status_code == 500

    def test_success_returns_control_and_value(self):
        set_result = MagicMock(returncode=0, stderr="", stdout="")
        get_result = MagicMock(returncode=0, stderr="", stdout="contrast: 2")
        with patch("subprocess.run", side_effect=[set_result, get_result]):
            r = client.post("/camera/controls", json={"control": "contrast", "value": 2})
        assert r.status_code == 200
        data = r.json()
        assert data["control"] == "contrast"
        assert data["value"] == 2
        assert data["status"] == "success"

    def test_empty_cache_returns_503(self):
        fastapi_app.cached_camera_controls = {}
        r = client.post("/camera/controls", json={"control": "contrast", "value": 2})
        assert r.status_code == 503


# ===========================================================================
# POST /camera/controls/reset
# ===========================================================================

class TestResetCameraControls:
    def setup_method(self):
        fastapi_app.cached_camera_controls = {
            "contrast": {"name": "contrast", "min": 0, "max": 4, "default": 2, "value": 3, "supported": True},
        }

    def test_reset_all_success(self):
        result = MagicMock(returncode=0, stderr="")
        with patch("subprocess.run", return_value=result):
            r = client.post("/camera/controls/reset", json={})
        assert r.status_code == 200
        assert r.json()["reset_count"] >= 1

    def test_reset_single_control_success(self):
        result = MagicMock(returncode=0, stderr="")
        with patch("subprocess.run", return_value=result):
            r = client.post("/camera/controls/reset", json={"control": "contrast"})
        assert r.status_code == 200

    def test_reset_unknown_control_400(self):
        r = client.post("/camera/controls/reset", json={"control": "nonexistent"})
        assert r.status_code == 400

    def test_reset_with_empty_cache_503(self):
        fastapi_app.cached_camera_controls = {}
        r = client.post("/camera/controls/reset")
        assert r.status_code == 503


# ===========================================================================
# GET /camera/resolution
# ===========================================================================

class TestGetCameraResolution:
    def test_returns_resolution_from_zmq(self):
        _zmq_rep_returns(_make_status_json(width=1920, height=1080, fps=15))
        r = client.get("/camera/resolution")
        assert r.status_code == 200
        data = r.json()
        assert data["width"] == 1920
        assert data["height"] == 1080
        assert data["fps"] == 15

    def test_503_on_zmq_timeout(self):
        _zmq_rep_timeout()
        r = client.get("/camera/resolution")
        assert r.status_code == 503


# ===========================================================================
# POST /camera/resolution
# ===========================================================================

class TestSetCameraResolution:
    def test_valid_resolution_success(self):
        _zmq_rep_returns("OK:3840x2160@30")
        r = client.post("/camera/resolution", json={"width": 3840, "height": 2160, "fps": 30})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["width"] == 3840

    def test_zero_fps_returns_400(self):
        r = client.post("/camera/resolution", json={"width": 1920, "height": 1080, "fps": 0})
        assert r.status_code == 400

    def test_negative_width_returns_400(self):
        r = client.post("/camera/resolution", json={"width": -1, "height": 1080, "fps": 30})
        assert r.status_code == 400

    def test_error_response_from_service_returns_500(self):
        _zmq_rep_returns("ERROR: Aufnahme läuft")
        r = client.post("/camera/resolution", json={"width": 1920, "height": 1080, "fps": 30})
        assert r.status_code == 500

    def test_zmq_timeout_returns_504(self):
        _zmq_rep_timeout()
        r = client.post("/camera/resolution", json={"width": 1920, "height": 1080, "fps": 30})
        assert r.status_code == 504


# ===========================================================================
# GET /status
# ===========================================================================

class TestGetStatus:
    def test_returns_200(self):
        _zmq_rep_returns(_make_status_json())
        r = client.get("/status")
        assert r.status_code == 200

    def test_camera_service_running_when_zmq_responds(self):
        _zmq_rep_returns(_make_status_json())
        r = client.get("/status")
        assert r.json()["camera_service"]["running"] is True

    def test_camera_service_not_running_when_zmq_timeout(self):
        _zmq_rep_timeout()
        r = client.get("/status")
        assert r.json()["camera_service"]["running"] is False

    def test_recording_section_present(self):
        _zmq_rep_returns(_make_status_json(recording=True))
        r = client.get("/status")
        assert "recording" in r.json()

    def test_disk_space_section_present(self):
        _zmq_rep_returns(_make_status_json())
        r = client.get("/status")
        assert "disk_space" in r.json()

    def test_hardware_section_contains_servo(self):
        _zmq_rep_returns(_make_status_json())
        r = client.get("/status")
        assert "servo_angle" in r.json()["hardware"]


# ===========================================================================
# GET /system/info
# ===========================================================================

class TestSystemInfo:
    def test_returns_200(self):
        r = client.get("/system/info")
        assert r.status_code == 200

    def test_contains_cpu_percent(self):
        r = client.get("/system/info")
        assert "cpu_percent" in r.json()

    def test_contains_ram_percent(self):
        r = client.get("/system/info")
        assert "ram_percent" in r.json()

    def test_contains_disks(self):
        r = client.get("/system/info")
        assert "disks" in r.json()

    def test_contains_output_files(self):
        r = client.get("/system/info")
        assert "output_files" in r.json()

    def test_disk_space_error_shown_when_set(self):
        with patch.object(fastapi_app.disk_space_error, "is_set", return_value=True):
            r = client.get("/system/info")
        assert "disk_space_error" in r.json()

    def test_no_disk_space_error_when_not_set(self):
        with patch.object(fastapi_app.disk_space_error, "is_set", return_value=False):
            r = client.get("/system/info")
        assert "disk_space_error" not in r.json()


# ===========================================================================
# POST /system/shutdown
# ===========================================================================

class TestSystemShutdown:
    def test_returns_200_and_status(self):
        with patch("subprocess.Popen") as m:
            r = client.post("/system/shutdown")
        assert r.status_code == 200
        assert "shutdown" in r.json()["status"]
        m.assert_called_once_with(["sudo", "shutdown", "-h", "now"])

    def test_error_returns_500(self):
        with patch("subprocess.Popen", side_effect=OSError("not found")):
            r = client.post("/system/shutdown")
        assert r.status_code == 500


# ===========================================================================
# POST /system/reboot
# ===========================================================================

class TestSystemReboot:
    def test_returns_200_and_status(self):
        with patch("subprocess.Popen") as m:
            r = client.post("/system/reboot")
        assert r.status_code == 200
        assert "reboot" in r.json()["status"]
        m.assert_called_once_with(["sudo", "reboot"])

    def test_error_returns_500(self):
        with patch("subprocess.Popen", side_effect=OSError("not found")):
            r = client.post("/system/reboot")
        assert r.status_code == 500


# ===========================================================================
# Hilfsfunktionen – angle_to_pulse
# ===========================================================================

class TestAngleToPulse:
    def test_0_degrees_gives_500us(self):
        assert abs(fastapi_app.angle_to_pulse(0) - 500.0) < 0.01

    def test_90_degrees_gives_1500us(self):
        assert abs(fastapi_app.angle_to_pulse(90) - 1500.0) < 0.01

    def test_180_degrees_gives_2500us(self):
        assert abs(fastapi_app.angle_to_pulse(180) - 2500.0) < 0.01


# ===========================================================================
# read_camera_controls_from_device
# ===========================================================================

SAMPLE_V4L2_OUTPUT = (
    "                     contrast 0x00980901 (int)    : min=0 max=4 step=1 default=2 value=2\n"
    "                    saturation 0x00980902 (int)    : min=0 max=255 step=1 default=64 value=64\n"
    "                 auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3\n"
    "\t\t\t\t1: Manual Mode\n"
    "\t\t\t\t3: Aperture Priority Mode\n"
)


class TestReadCameraControls:
    def test_parses_contrast(self):
        r = MagicMock(returncode=0, stdout=SAMPLE_V4L2_OUTPUT, stderr="")
        with patch("subprocess.run", return_value=r):
            controls = fastapi_app.read_camera_controls_from_device("/dev/video0")
        assert "contrast" in controls
        assert controls["contrast"]["min"] == 0
        assert controls["contrast"]["max"] == 4
        assert controls["contrast"]["value"] == 2

    def test_parses_saturation(self):
        r = MagicMock(returncode=0, stdout=SAMPLE_V4L2_OUTPUT, stderr="")
        with patch("subprocess.run", return_value=r):
            controls = fastapi_app.read_camera_controls_from_device("/dev/video0")
        assert controls["saturation"]["default"] == 64

    def test_supported_flag_set_correctly(self):
        r = MagicMock(returncode=0, stdout=SAMPLE_V4L2_OUTPUT, stderr="")
        with patch("subprocess.run", return_value=r):
            controls = fastapi_app.read_camera_controls_from_device("/dev/video0")
        assert controls["contrast"]["supported"] is True
        assert controls["auto_exposure"]["supported"] is True

    def test_contrast_type_is_int(self):
        r = MagicMock(returncode=0, stdout=SAMPLE_V4L2_OUTPUT, stderr="")
        with patch("subprocess.run", return_value=r):
            controls = fastapi_app.read_camera_controls_from_device("/dev/video0")
        assert controls["contrast"]["type"] == "int"

    def test_auto_exposure_type_is_menu(self):
        r = MagicMock(returncode=0, stdout=SAMPLE_V4L2_OUTPUT, stderr="")
        with patch("subprocess.run", return_value=r):
            controls = fastapi_app.read_camera_controls_from_device("/dev/video0")
        assert controls["auto_exposure"]["type"] == "menu"

    def test_auto_exposure_menu_entries_parsed(self):
        r = MagicMock(returncode=0, stdout=SAMPLE_V4L2_OUTPUT, stderr="")
        with patch("subprocess.run", return_value=r):
            controls = fastapi_app.read_camera_controls_from_device("/dev/video0")
        entries = controls["auto_exposure"]["menu_entries"]
        assert entries == {"1": "Manual Mode", "3": "Aperture Priority Mode"}

    def test_v4l2ctl_nonzero_raises(self):
        r = MagicMock(returncode=1, stdout="", stderr="no device")
        with patch("subprocess.run", return_value=r):
            with pytest.raises(RuntimeError):
                fastapi_app.read_camera_controls_from_device("/dev/video0")

    def test_timeout_raises(self):
        import subprocess as sp
        with patch("subprocess.run", side_effect=sp.TimeoutExpired("v4l2-ctl", 5)):
            with pytest.raises(RuntimeError, match="Timeout"):
                fastapi_app.read_camera_controls_from_device("/dev/video0")


# ===========================================================================
# POST /camera/controls – Menu-Control-Validierung
# ===========================================================================

class TestMenuControlValidation:
    def setup_method(self):
        fastapi_app.cached_camera_controls = {
            "auto_exposure": {
                "name": "auto_exposure",
                "type": "menu",
                "min": 0,
                "max": 3,
                "default": 3,
                "value": 3,
                "supported": True,
                "menu_entries": {"1": "Manual Mode", "3": "Aperture Priority Mode"},
            },
        }

    def test_valid_menu_value_accepted(self):
        set_r = MagicMock(returncode=0, stderr="", stdout="")
        get_r = MagicMock(returncode=0, stderr="", stdout="auto_exposure: 1")
        with patch("subprocess.run", side_effect=[set_r, get_r]):
            r = client.post("/camera/controls", json={"control": "auto_exposure", "value": 1})
        assert r.status_code == 200

    def test_invalid_menu_value_rejected(self):
        r = client.post("/camera/controls", json={"control": "auto_exposure", "value": 0})
        assert r.status_code == 400
        assert "Gültige Einträge" in r.json()["detail"]

    def test_invalid_menu_value_error_lists_valid_entries(self):
        r = client.post("/camera/controls", json={"control": "auto_exposure", "value": 2})
        assert "Manual Mode" in r.json()["detail"]
        assert "Aperture Priority Mode" in r.json()["detail"]


# ===========================================================================
# POST /camera/controls – Cache-Update nach erfolgreichem Set
# ===========================================================================

class TestSetCameraControlCacheUpdate:
    def setup_method(self):
        fastapi_app.cached_camera_controls = {
            "contrast": {"name": "contrast", "min": 0, "max": 4, "default": 2, "value": 2, "supported": True},
        }

    def test_cache_value_updated_after_successful_set(self):
        set_r = MagicMock(returncode=0, stderr="", stdout="")
        get_r = MagicMock(returncode=0, stderr="", stdout="contrast: 3")
        with patch("subprocess.run", side_effect=[set_r, get_r]):
            r = client.post("/camera/controls", json={"control": "contrast", "value": 3})
        assert r.status_code == 200
        assert fastapi_app.cached_camera_controls["contrast"]["value"] == 3

    def test_cache_value_unchanged_after_v4l2_failure(self):
        fail_r = MagicMock(returncode=1, stderr="error", stdout="")
        with patch("subprocess.run", return_value=fail_r):
            r = client.post("/camera/controls", json={"control": "contrast", "value": 3})
        assert r.status_code == 500
        assert fastapi_app.cached_camera_controls["contrast"]["value"] == 2  # unverändert

    def test_get_controls_reflects_new_value_after_set(self):
        set_r = MagicMock(returncode=0, stderr="", stdout="")
        get_r = MagicMock(returncode=0, stderr="", stdout="contrast: 4")
        with patch("subprocess.run", side_effect=[set_r, get_r]):
            client.post("/camera/controls", json={"control": "contrast", "value": 4})
        r = client.get("/camera/controls")
        assert r.json()["controls"]["contrast"]["value"] == 4

    def test_cache_uses_verified_hardware_value_not_request_value(self):
        """Hardware klemmt den Wert – Cache soll den tatsächlichen Wert speichern."""
        set_r = MagicMock(returncode=0, stderr="", stdout="")
        get_r = MagicMock(returncode=0, stderr="", stdout="contrast: 2")  # Hardware: 3 → 2
        with patch("subprocess.run", side_effect=[set_r, get_r]):
            r = client.post("/camera/controls", json={"control": "contrast", "value": 3})
        assert r.json()["value"] == 2
        assert fastapi_app.cached_camera_controls["contrast"]["value"] == 2

    def test_cache_falls_back_to_request_value_when_verify_parse_fails(self):
        """Falls der verify-Abruf keinen ':' liefert, wird req.value als Fallback gespeichert."""
        set_r = MagicMock(returncode=0, stderr="", stdout="")
        get_r = MagicMock(returncode=0, stderr="", stdout="")  # kein Kolon → Parse schlägt fehl
        with patch("subprocess.run", side_effect=[set_r, get_r]):
            r = client.post("/camera/controls", json={"control": "contrast", "value": 3})
        assert r.status_code == 200
        assert fastapi_app.cached_camera_controls["contrast"]["value"] == 3


