import json
import os
import subprocess

import psutil
import zmq
from fastapi import FastAPI, HTTPException
from starlette.responses import JSONResponse, StreamingResponse

import hardware
import stream as _stream
from camera_controls import cached_camera_controls, read_camera_controls_from_device
from config import (
    CAMERA_DEVICE,
    DISK_SPACE_LIMIT_GB,
    SERVO_FREQ,
    SERVO_PIN,
    STEPPER_PINS,
    SUPPORTED_CAMERA_CONTROLS,
)
from hardware import (
    angle_to_pulse,
    move_servo_absolute,
    move_servo_relative,
    move_stepper_absolute,
    move_stepper_relative,
)
from models import (
    CameraControlRequest,
    CameraControlResetRequest,
    CameraResolutionRequest,
    ServoAbsoluteRequest,
    ServoRelativeRequest,
    StepperAbsoluteRequest,
    StepperRelativeRequest,
)
from stream import disk_space_error, new_frame_event, req_lock, req_socket, stop_event

# Einmaliger Warmup – cpu_percent(interval=None) liefert sonst 0.0 beim ersten Aufruf
psutil.cpu_percent(interval=None)

app = FastAPI(title="Kaderblick API", version="1.0")


# ==============================
# Root
# ==============================

@app.get("/")
def root():
    return {
        "app": "Kaderblick API (Raspberry Pi 5 + Arducam B0589 + Servo/Stepper Control)",
        "version": "1.0",
        "endpoints": {
            "GET /": "This info",
            "GET /preview": "Stream live MJPEG preview from camera service",
            "POST /start_record": "Start recording video",
            "POST /stop_record": "Stop recording video",
            "POST /servo": "Move servo relative (degrees +/-)",
            "POST /servo/absolute": "Move servo to absolute angle (0-180°)",
            "GET /servo": "Get current servo angle",
            "POST /stepper": "Move stepper motor (relative steps)",
            "POST /stepper/absolute": "Move stepper motor (absolute position)",
            "GET /stepper": "Get current stepper position",
            "GET /camera-position-status": "Get servo angle and stepper position",
            "GET /system/info": "System info (CPU, RAM, disk, output files)",
            "POST /system/shutdown": "Shutdown the system",
            "POST /system/reboot": "Reboot the system",
            "GET /docs": "Interactive API documentation (Swagger UI)",
            "GET /redoc": "Alternative API documentation (ReDoc)",
        },
        "architecture": {
            "camera_source": "Camera service via ZMQ (tcp://127.0.0.1:5555 + tcp://127.0.0.1:5556)",
            "stream": "ZMQ SUB socket for MJPEG frames",
            "control": "ZMQ REQ socket for recording commands",
            "hardware": "GPIO control via lgpio (Servo on GPIO 18, Stepper on GPIOs 17,27,20,21)",
        },
        "hardware": {
            "servo": {
                "pin": SERVO_PIN,
                "current_angle": hardware.current_servo_angle,
                "range": "0-180°",
                "frequency": f"{SERVO_FREQ} Hz",
            },
            "stepper": {
                "pins": STEPPER_PINS,
                "current_position": hardware.current_stepper_pos,
                "sequence": "Half-step (8 steps)",
            },
        },
        "zmq": {
            "subscriber": "tcp://127.0.0.1:5555 (frame stream)",
            "request": "tcp://127.0.0.1:5556 (recording control)",
        },
    }


# ==============================
# Aufnahme
# ==============================

@app.post("/start_record")
def start_record():
    with req_lock:
        req_socket.send_string("START")
        status = req_socket.recv_string()
    return {"status": status}


@app.post("/stop_record")
def stop_record():
    with req_lock:
        req_socket.send_string("STOP")
        status = req_socket.recv_string()
    return {"status": status}


@app.get("/preview")
def preview():
    def generate():
        last_sent = None
        try:
            while not stop_event.is_set():
                new_frame_event.wait(timeout=0.5)
                new_frame_event.clear()
                frame = _stream.latest_frame
                if frame is not None and frame is not last_sent:
                    last_sent = frame
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + frame
                        + b"\r\n"
                    )
        except GeneratorExit:
            pass

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")


# ==============================
# Servo
# ==============================

@app.get("/servo")
def get_servo():
    return {"angle": hardware.current_servo_angle}


@app.post("/servo")
def api_servo_relative(req: ServoRelativeRequest):
    move_servo_relative(req.degrees)
    return {"angle": hardware.current_servo_angle}


@app.post("/servo/absolute")
def api_servo_absolute(req: ServoAbsoluteRequest):
    if not (0 <= req.angle <= 180):
        raise HTTPException(status_code=400, detail="Angle must be 0-180")
    move_servo_absolute(req.angle)
    return {"angle": hardware.current_servo_angle}


# ==============================
# Stepper
# ==============================

@app.get("/stepper")
def get_stepper():
    return {"current_position": hardware.current_stepper_pos}


@app.post("/stepper")
def api_stepper(req: StepperRelativeRequest):
    move_stepper_relative(req.steps, req.delay)
    return {"current_position": hardware.current_stepper_pos}


@app.post("/stepper/absolute")
def api_stepper_absolute(req: StepperAbsoluteRequest):
    move_stepper_absolute(req.position, req.delay)
    return {"current_position": hardware.current_stepper_pos}


@app.get("/camera-position-status")
def get_camera_position_status():
    return {
        "y-angle": hardware.current_servo_angle,
        "x-position": hardware.current_stepper_pos,
    }


# ==============================
# Kamera-Controls
# ==============================

@app.get("/camera/controls")
def get_camera_controls():
    if not cached_camera_controls:
        raise HTTPException(
            status_code=503,
            detail="Camera Controls noch nicht geladen. Kamera möglicherweise nicht verfügbar.",
        )
    return {"controls": cached_camera_controls, "device": CAMERA_DEVICE}


@app.post("/camera/controls")
def set_camera_control(req: CameraControlRequest):
    if req.control not in SUPPORTED_CAMERA_CONTROLS:
        raise HTTPException(
            status_code=400,
            detail=f"Unbekanntes Control '{req.control}'. Unterstützte Controls: {SUPPORTED_CAMERA_CONTROLS}",
        )
    if not cached_camera_controls:
        raise HTTPException(
            status_code=503,
            detail="Camera Controls noch nicht geladen. Kamera möglicherweise nicht verfügbar.",
        )
    if req.control not in cached_camera_controls:
        raise HTTPException(
            status_code=404,
            detail=f"Control '{req.control}' wurde von der Kamera nicht gefunden",
        )

    limits = cached_camera_controls[req.control]
    if limits.get("type") == "menu":
        menu_entries = limits.get("menu_entries", {})
        if menu_entries and str(req.value) not in menu_entries:
            valid = ", ".join(f"{k} ({v})" for k, v in sorted(menu_entries.items(), key=lambda x: int(x[0])))
            raise HTTPException(
                status_code=400,
                detail=f"Ungültiger Menü-Wert {req.value} für {req.control}. Gültige Einträge: {valid}",
            )
    elif "min" in limits and "max" in limits:
        if not (limits["min"] <= req.value <= limits["max"]):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Wert {req.value} außerhalb des erlaubten Bereichs "
                    f"[{limits['min']}-{limits['max']}] für {req.control}"
                ),
            )

    try:
        result = subprocess.run(
            ["v4l2-ctl", "--device", CAMERA_DEVICE, "--set-ctrl", f"{req.control}={req.value}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"v4l2-ctl Fehler: {result.stderr}")

        verify = subprocess.run(
            ["v4l2-ctl", "--device", CAMERA_DEVICE, "--get-ctrl", req.control],
            capture_output=True,
            text=True,
            timeout=5,
        )
        confirmed = req.value
        if verify.returncode == 0 and ":" in verify.stdout:
            try:
                confirmed = int(verify.stdout.strip().split(":")[1].strip())
            except ValueError:
                pass

        cached_camera_controls[req.control]["value"] = confirmed

        # Flags abhängiger Controls neu einlesen: der Kernel setzt z.B. flags=inactive
        # auf exposure_time_absolute dynamisch je nach auto_exposure-Wert. Der Cache
        # muss aktualisiert werden damit GET /camera/controls aktuelle Flags liefert.
        try:
            fresh = read_camera_controls_from_device()
            cached_camera_controls.clear()
            cached_camera_controls.update(fresh)
        except Exception:
            pass

        return {"control": req.control, "value": confirmed, "status": "success"}

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="v4l2-ctl Timeout")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Setzen des Controls: {e}")


@app.post("/camera/controls/reset")
def reset_camera_controls(req: CameraControlResetRequest | None = None):
    if not cached_camera_controls:
        raise HTTPException(
            status_code=503,
            detail="Camera Controls noch nicht geladen. Kamera möglicherweise nicht verfügbar.",
        )

    if req and req.control:
        if req.control not in SUPPORTED_CAMERA_CONTROLS:
            raise HTTPException(
                status_code=400,
                detail=f"Unbekanntes Control '{req.control}'. Unterstützte Controls: {SUPPORTED_CAMERA_CONTROLS}",
            )
        if req.control not in cached_camera_controls:
            raise HTTPException(
                status_code=404,
                detail=f"Control '{req.control}' wurde von der Kamera nicht gefunden",
            )
        controls_to_reset = [req.control]
    else:
        controls_to_reset = SUPPORTED_CAMERA_CONTROLS

    reset_results: dict = {}
    errors: list = []

    for name in controls_to_reset:
        if name not in cached_camera_controls:
            errors.append(f"{name}: Nicht in gecachten Controls gefunden")
            continue
        info = cached_camera_controls[name]
        if "default" not in info:
            errors.append(f"{name}: Kein Default-Wert verfügbar")
            continue
        default = info["default"]
        try:
            result = subprocess.run(
                ["v4l2-ctl", "--device", CAMERA_DEVICE, "--set-ctrl", f"{name}={default}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                errors.append(f"{name}: {result.stderr.strip()}")
            else:
                cached_camera_controls[name]["value"] = default
                reset_results[name] = {"default_value": default, "status": "success"}
        except subprocess.TimeoutExpired:
            errors.append(f"{name}: Timeout")
        except Exception as e:
            errors.append(f"{name}: {e}")

    response: dict = {"reset_count": len(reset_results), "results": reset_results}
    if errors:
        response["errors"] = errors
    return response


# ==============================
# Kamera-Auflösung
# ==============================

@app.get("/camera/resolution")
def get_camera_resolution():
    try:
        with req_lock:
            req_socket.send_string("STATUS", flags=zmq.NOBLOCK)
            if req_socket.poll(1000):
                st = json.loads(req_socket.recv_string())
                return {
                    "width": st.get("width", 3840),
                    "height": st.get("height", 2160),
                    "fps": st.get("fps", 30),
                }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    raise HTTPException(status_code=503, detail="Camera Service antwortet nicht")


@app.post("/camera/resolution")
def set_camera_resolution(req: CameraResolutionRequest):
    if req.fps <= 0 or req.width <= 0 or req.height <= 0:
        raise HTTPException(status_code=400, detail="Ungültige Werte für Auflösung oder FPS")
    try:
        with req_lock:
            req_socket.send_string(f"SET_RESOLUTION:{req.width}x{req.height}:{req.fps}")
            if req_socket.poll(15000):
                response = req_socket.recv_string()
                if response.startswith("OK:"):
                    return {"status": "success", "width": req.width, "height": req.height, "fps": req.fps}
                raise HTTPException(status_code=500, detail=response)
            raise HTTPException(status_code=504, detail="Timeout beim Neustart des Streamers")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==============================
# Status
# ==============================

@app.get("/status")
def get_status():
    camera_service_running = False
    recording_active = False
    session_dir = None
    audio_available = False
    camera_details: dict = {}

    try:
        with req_lock:
            req_socket.send_string("STATUS", flags=zmq.NOBLOCK)
            if req_socket.poll(1000):
                camera_status = json.loads(req_socket.recv_string())
                camera_service_running = True
                recording_active = camera_status.get("recording", False)
                session_dir = camera_status.get("session_dir")
                audio_available = camera_status.get("audio_available", False)
                camera_details = {
                    "capture_thread_alive": camera_status.get("capture_thread_alive"),
                    "frames_captured": camera_status.get("frames_captured"),
                    "frames_written": camera_status.get("frames_written"),
                    "last_frame_age_s": camera_status.get("last_frame_age_s"),
                    "capture_error": camera_status.get("capture_error"),
                    "audio_exit_code": camera_status.get("audio_exit_code"),
                    "audio_error": camera_status.get("audio_error"),
                    "video_file_bytes": camera_status.get("video_file_bytes"),
                    "width": camera_status.get("width", 3840),
                    "height": camera_status.get("height", 2160),
                    "fps": camera_status.get("fps", 30),
                }
    except (zmq.ZMQError, Exception):
        camera_service_running = False

    stream_available = _stream.latest_frame is not None

    status: dict = {
        "camera_service": {
            "running": camera_service_running,
            "stream_available": stream_available,
            "audio_available": audio_available,
            **camera_details,
        },
        "recording": {"active": recording_active, "session_dir": session_dir},
        "preview": "available" if stream_available else "unavailable",
        "zmq": {
            "stream_endpoint": "tcp://127.0.0.1:5555",
            "control_endpoint": "tcp://127.0.0.1:5556",
        },
    }

    output_dir = os.path.join(os.path.dirname(__file__), "..", "recordings")
    status["output_dir"] = output_dir

    try:
        st = os.statvfs(output_dir if os.path.exists(output_dir) else "/")
        free_gb = (st.f_bavail * st.f_frsize) / (1024 ** 3)
        total_gb = (st.f_blocks * st.f_frsize) / (1024 ** 3)
        used_gb = total_gb - free_gb
        status["disk_space"] = {
            "free_gb": round(free_gb, 2),
            "used_gb": round(used_gb, 2),
            "total_gb": round(total_gb, 2),
            "used_percent": round((used_gb / total_gb * 100), 1) if total_gb > 0 else 0,
        }
    except Exception as e:
        status["disk_space"] = {"error": str(e)}

    status["hardware"] = {
        "servo_angle": hardware.current_servo_angle,
        "stepper_position": hardware.current_stepper_pos,
    }

    return status


# ==============================
# System
# ==============================

@app.get("/system/info")
def system_info():
    info: dict = {}

    temps = psutil.sensors_temperatures()
    cpu_thermal = temps.get("cpu_thermal", [])
    info["temperature_celsius"] = cpu_thermal[0].current if cpu_thermal else None

    freq = psutil.cpu_freq()
    info["cpu_freq_min_mhz"] = freq.min if freq else None
    info["cpu_freq_max_mhz"] = freq.max if freq else None
    info["cpu_freq_current_mhz"] = freq.current if freq else None
    info["cpu_percent"] = psutil.cpu_percent(interval=None)
    info["cpu_count"] = psutil.cpu_count()
    info["cpu_count_logical"] = psutil.cpu_count(logical=True)
    info["cpu_count_physical"] = psutil.cpu_count(logical=False)

    mem = psutil.virtual_memory()
    info["ram_percent"] = mem.percent
    info["ram_total"] = f"{mem.total / 1024 / 1024:.1f} MB"
    info["ram_used"] = f"{mem.used / 1024 / 1024:.1f} MB"
    info["ram_available"] = f"{mem.available / 1024 / 1024:.1f} MB"

    disks = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "percent": usage.percent,
                "total": f"{usage.total / 1024 / 1024 / 1024:.2f} GB",
                "used": f"{usage.used / 1024 / 1024 / 1024:.2f} GB",
                "free": f"{usage.free / 1024 / 1024 / 1024:.2f} GB",
            })
        except Exception:
            continue
    info["disks"] = disks

    output_dir = os.path.join(os.path.dirname(__file__), "..", "recordings")
    files = []
    if os.path.isdir(output_dir):
        for fname in os.listdir(output_dir):
            fpath = os.path.join(output_dir, fname)
            if os.path.isfile(fpath):
                size = float(os.path.getsize(fpath))
                unit = "B"
                for unit in ["B", "KB", "MB", "GB", "TB"]:
                    if size < 1024.0:
                        break
                    size /= 1024.0
                files.append({"name": fname, "size": f"{size:.2f} {unit}"})
    info["output_files"] = files

    if disk_space_error.is_set():
        info["disk_space_error"] = (
            f"Wenig Speicherplatz: Aufnahme wurde gestoppt, weil weniger als "
            f"{DISK_SPACE_LIMIT_GB} GB frei sind. Bitte Speicherplatz freigeben!"
        )

    return info


@app.post("/system/shutdown")
def system_shutdown():
    try:
        subprocess.Popen(["sudo", "shutdown", "-h", "now"])
        return JSONResponse({"status": "shutdown initiated"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/system/reboot")
def system_reboot():
    try:
        subprocess.Popen(["sudo", "reboot"])
        return JSONResponse({"status": "reboot initiated"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
