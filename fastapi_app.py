from fastapi import FastAPI, Response, Header, HTTPException
from starlette.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, conint
import lgpio
import zmq
import threading
import psutil
import time
import os
import signal
import sys
import subprocess
from threading import Lock

# --- Speicherplatz-Limit für Aufnahme (in GB) ---
DISK_SPACE_LIMIT_GB = 30  # Aufnahme wird gestoppt, wenn weniger als 30GB frei
disk_space_error = threading.Event()  # Wird gesetzt, wenn Limit erreicht

# =============================
# Kamera V4L2 Konfiguration
# =============================
CAMERA_DEVICE = "/dev/video0"  # V4L2 Device

# Kamera V4L2 Controls - Unterstützte Control-Namen
SUPPORTED_CAMERA_CONTROLS = [
    "contrast",
    "saturation",
    "gain",
    "sharpness",
    "auto_exposure",
    "exposure_time_absolute"
]

# Gecachte Camera Controls (werden beim Start geladen)
cached_camera_controls = {}

# =============================
# Hardware-Konfiguration
# =============================
SERVO_PIN = 18  # PWM GPIO für MG90S

# Stepper GPIOs (ULN2003 IN1-IN4)
STEPPER_PINS = [17, 27, 20, 21]

API_KEY = "mein_sicherer_key"
app = FastAPI(title="Kaderblick API", version="1.0")

# Servo config
SERVO_FREQ = 50  # 50Hz typical for hobby servos
SERVO_MIN_DUTY = 2.0   # corresponds ~0.5ms, may need tuning per servo
SERVO_MAX_DUTY = 12.0  # corresponds ~2.5ms, may need tuning per servo

# -------------------------
# State + Locks
# -------------------------
current_servo_angle = 90      # initial assumed angle
current_stepper_pos = 0       # integer step count (relative/absolute)
servo_lock = Lock()
stepper_lock = Lock()

# =============================
# Hilfsfunktionen Stepper
# =============================
# Halbschritt-Sequenz (8 Schritte)
STEPPER_SEQUENCE = [
    [1,0,0,0],
    [1,1,0,0],
    [0,1,0,0],
    [0,1,1,0],
    [0,0,1,0],
    [0,0,1,1],
    [0,0,0,1],
    [1,0,0,1],
]

h = lgpio.gpiochip_open(0)
lgpio.gpio_claim_output(h, SERVO_PIN)
for pin in STEPPER_PINS:
    lgpio.gpio_claim_output(h, pin)

# ZMQ Setup
context = zmq.Context()

# ZMQ REQ socket and lock for thread-safe access
req_socket = context.socket(zmq.REQ)
req_socket.connect("tcp://127.0.0.1:5556")
req_lock = Lock()

sub_socket = context.socket(zmq.SUB)
sub_socket.connect("tcp://127.0.0.1:5555")
sub_socket.setsockopt_string(zmq.SUBSCRIBE, "")
sub_socket.RCVTIMEO = 100 # Millisekunden, damit recv nicht ewig blockiert


latest_frame = None
stop_event = threading.Event()


# --- Hintergrund-Thread: Überwacht freien Speicherplatz und stoppt Aufnahme bei Limit ---
def disk_space_monitor():
    global disk_space_error
    while not stop_event.is_set():
        try:
            output_dir = os.path.join(os.path.dirname(__file__), "recordings")
            statvfs = os.statvfs(output_dir if os.path.exists(output_dir) else "/")
            free_gb = (statvfs.f_bavail * statvfs.f_frsize) / (1024**3)
            if free_gb < DISK_SPACE_LIMIT_GB:
                disk_space_error.set()
                # Versuche Aufnahme zu stoppen, falls aktiv
                try:
                    with req_lock:
                        req_socket.send_string("STOP")
                        # Warte auf Antwort, aber ignoriere Fehler
                        if req_socket.poll(1000):
                            req_socket.recv_string()
                except Exception:
                    pass
            else:
                disk_space_error.clear()
        except Exception:
            pass
        time.sleep(5)  # alle 5 Sekunden prüfen

threading.Thread(target=disk_space_monitor, daemon=True).start()


def frame_listener():
    global latest_frame
    while not stop_event.is_set():
        try:
            latest_frame = sub_socket.recv(flags=zmq.NOBLOCK)
        except zmq.Again:
            time.sleep(0.01)

listener_thread = threading.Thread(target=frame_listener, daemon=True)
listener_thread.start()


def verify_api_key(x_api_key: str):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


def read_camera_controls_from_device(device: str = CAMERA_DEVICE) -> dict:
    """
    Liest alle verfügbaren V4L2 Kamera-Controls direkt vom Device
    mit ihren aktuellen Werten, Limits und Standardwerten.
    
    Args:
        device: V4L2 Device-Pfad (z.B. /dev/video0)
    
    Returns:
        Dictionary mit Control-Informationen
    """
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--device", device, "--list-ctrls"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"v4l2-ctl Fehler: {result.stderr}")
        
        # Parse ALLE Controls
        controls = {}
        for line in result.stdout.split('\n'):
            if ':' not in line:
                continue
            
            # Beispiel: "contrast 0x00980901 (int)    : min=0 max=4 step=1 default=2 value=2"
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            
            control_name = parts[0]
            control_info: dict = {
                "name": control_name,
                "supported": control_name in SUPPORTED_CAMERA_CONTROLS
            }
            
            # Parse min, max, step, default, value
            for part in parts:
                if '=' in part:
                    key, val = part.split('=')
                    try:
                        control_info[key] = int(val)  # type: ignore
                    except ValueError:
                        control_info[key] = val  # type: ignore
            
            controls[control_name] = control_info
        
        return controls
    
    except subprocess.TimeoutExpired:
        raise RuntimeError("v4l2-ctl Timeout")
    except Exception as e:
        raise RuntimeError(f"Fehler beim Abrufen der Controls: {str(e)}")


# =============================
# Request-Models
# =============================
class ServoAbsoluteRequest(BaseModel):
    angle: int  # 0–180°
    
    def __init__(self, **data):
        super().__init__(**data)
        if not 0 <= self.angle <= 180:
            raise ValueError("Angle must be between 0 and 180")

class ServoRelativeRequest(BaseModel):
    degrees: int  # relative movement in degrees (+/-)

class StepperRelativeRequest(BaseModel):
    steps: int
    delay: float = 0.002

class StepperAbsoluteRequest(BaseModel):
    position: int  # absolute Position
    delay: float = 0.002

class CameraControlRequest(BaseModel):
    control: str  # Name des Controls (contrast, saturation, gain, sharpness, auto_exposure, exposure_time_absolute)
    value: int    # Neuer Wert

class CameraControlResetRequest(BaseModel):
    control: str | None = None  # Optional: spezifischer Control, sonst alle


# Lade Camera Controls beim Start
try:
    cached_camera_controls = read_camera_controls_from_device(CAMERA_DEVICE)
    print(f"✓ Camera Controls von {CAMERA_DEVICE} geladen: {list(cached_camera_controls.keys())}")
except Exception as e:
    print(f"⚠ Warnung: Camera Controls konnten nicht geladen werden: {e}")
    print(f"  Die Kamera-Endpunkte werden möglicherweise nicht funktionieren.")


# =============================
# Servo Funktionen
# =============================
def angle_to_pulse(angle):
    return 500 + (angle/180)*2000  # µs


def move_servo_absolute(angle):
    """Move servo to absolute angle (0-180°)"""
    global current_servo_angle
    with servo_lock:
        # Clamp angle to valid range
        angle = max(0, min(180, angle))
        pulse = angle_to_pulse(angle)
        # lgpio verwendet tx_pwm mit Frequenz und Duty Cycle (0-100)
        duty_cycle = (pulse / 20000) * 100  # pulse in µs, 20ms period = 20000µs
        lgpio.tx_pwm(h, SERVO_PIN, SERVO_FREQ, duty_cycle)
        time.sleep(0.3)
        lgpio.tx_pwm(h, SERVO_PIN, SERVO_FREQ, 0)  # Stop PWM
        current_servo_angle = angle


def move_servo_relative(degrees):
    """Move servo relative to current position"""
    global current_servo_angle
    target = current_servo_angle + degrees
    move_servo_absolute(target)


def move_stepper_relative(steps, delay=0.002):
    global current_stepper_pos
    with stepper_lock:
        for _ in range(abs(steps)):
            idx = current_stepper_pos % 8
            for pin, val in zip(STEPPER_PINS, STEPPER_SEQUENCE[idx]):
                lgpio.gpio_write(h, pin, val)
            time.sleep(delay)
            current_stepper_pos += 1 if steps > 0 else -1
        # Turn off coils
        for pin in STEPPER_PINS:
            lgpio.gpio_write(h, pin, 0)


def move_stepper_absolute(target, delay=0.002):
    global current_stepper_pos
    delta = target - current_stepper_pos
    move_stepper_relative(delta, delay)


@app.get("/")
def root():
    """API info and endpoints."""
    return {
        "app": "Kaderblick API (Raspberry Pi 5 + Arducam B0589 + Servo/Stepper Control)",
        "version": "1.0",
        "endpoints": {
            "GET /": "This info",
            "GET /preview": "Stream live MJPEG preview from camera service",
            "GET /start_record": "Start recording video",
            "GET /stop_record": "Stop recording video",
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
            "GET /redoc": "Alternative API documentation (ReDoc)"
        },
        "architecture": {
            "camera_source": "Camera service via ZMQ (tcp://127.0.0.1:5555 + tcp://127.0.0.1:5556)",
            "stream": "ZMQ SUB socket for MJPEG frames",
            "control": "ZMQ REQ socket for recording commands",
            "hardware": "GPIO control via lgpio (Servo on GPIO 18, Stepper on GPIOs 17,27,20,21)"
        },
        "hardware": {
            "servo": {
                "pin": SERVO_PIN,
                "current_angle": current_servo_angle,
                "range": "0-180°",
                "frequency": f"{SERVO_FREQ} Hz"
            },
            "stepper": {
                "pins": STEPPER_PINS,
                "current_position": current_stepper_pos,
                "sequence": "Half-step (8 steps)"
            }
        },
        "zmq": {
            "subscriber": "tcp://127.0.0.1:5555 (frame stream)",
            "request": "tcp://127.0.0.1:5556 (recording control)"
        }
    }


@app.post("/start_record")
def start_record():
#def start_record(x_api_key: str = Header(...)):
#    verify_api_key(x_api_key)
    with req_lock:
        req_socket.send_string("START")
        status = req_socket.recv_string()
    return {"status": status}


@app.post("/stop_record")
def stop_record():
#def stop_record(x_api_key: str = Header(...)):
#    verify_api_key(x_api_key)
    with req_lock:
        req_socket.send_string("STOP")
        status = req_socket.recv_string()
    return {"status": status}


@app.get("/preview")
#def preview(x_api_key: str = Header(...)):
def preview():
#    verify_api_key(x_api_key)
    def generate():
        try:
            while not stop_event.is_set():
                if latest_frame:
                    yield (b"--frame\r\n"
                           b"Content-Type: image/jpeg\r\n\r\n" +
                           latest_frame + b"\r\n")
                time.sleep(0.05)
        except GeneratorExit:
            # Client hat Verbindung getrennt
            pass
    return StreamingResponse(generate(), media_type='multipart/x-mixed-replace; boundary=frame')


@app.post("/servo")
def api_servo_relative(req: ServoRelativeRequest):
    """Move servo relative to current position (similar to stepper relative)"""
    move_servo_relative(req.degrees)
    return {"angle": current_servo_angle}


@app.post("/servo/absolute")
def api_servo_absolute(req: ServoAbsoluteRequest):
    """Move servo to absolute angle (0-180°)"""
    if not (0 <= req.angle <= 180):
        raise HTTPException(status_code=400, detail="Angle must be 0-180")
    move_servo_absolute(req.angle)
    return {"angle": current_servo_angle}


@app.post("/stepper")
def api_stepper(req: StepperRelativeRequest):
    move_stepper_relative(req.steps, req.delay)
    return {"current_position": current_stepper_pos}


@app.post("/stepper/absolute")
def api_stepper_absolute(req: StepperAbsoluteRequest):
    move_stepper_absolute(req.position, req.delay)
    return {"current_position": current_stepper_pos}


@app.get("/servo")
def get_servo():
    return {"angle": current_servo_angle}


@app.get("/stepper")
def get_stepper():
    return {"current_position": current_stepper_pos}


@app.get("/camera-position-status")
def get_camera_position_status():
    return {"y-angle": current_servo_angle, "x-position": current_stepper_pos}


@app.get("/camera/controls")
def get_camera_controls():
    """
    Gibt die beim Start gecachten Kamera-Controls zurück.
    Die Werte werden beim Start der Anwendung einmalig von der Kamera gelesen.
    """
    if not cached_camera_controls:
        raise HTTPException(
            status_code=503,
            detail="Camera Controls noch nicht geladen. Kamera möglicherweise nicht verfügbar."
        )
    return {"controls": cached_camera_controls, "device": CAMERA_DEVICE}


@app.post("/camera/controls/reset")
def reset_camera_controls(req: CameraControlResetRequest | None = None):
    """
    Setzt einen oder alle unterstützte Kamera-Controls auf ihre Default-Werte zurück.
    
    Ohne Body oder mit {"control": null}: Setzt ALLE unterstützten Controls zurück
    Mit {"control": "contrast"}: Setzt nur diesen spezifischen Control zurück
    """
    if not cached_camera_controls:
        raise HTTPException(
            status_code=503,
            detail="Camera Controls noch nicht geladen. Kamera möglicherweise nicht verfügbar."
        )
    
    # Bestimme welche Controls zurückgesetzt werden sollen
    if req and req.control:
        # Einzelner Control
        controls_to_reset = [req.control]
        
        # Validierung
        if req.control not in SUPPORTED_CAMERA_CONTROLS:
            raise HTTPException(
                status_code=400,
                detail=f"Unbekanntes Control '{req.control}'. Unterstützte Controls: {SUPPORTED_CAMERA_CONTROLS}"
            )
        
        if req.control not in cached_camera_controls:
            raise HTTPException(
                status_code=404,
                detail=f"Control '{req.control}' wurde von der Kamera nicht gefunden"
            )
    else:
        # Alle unterstützten Controls
        controls_to_reset = SUPPORTED_CAMERA_CONTROLS
    
    # Reset durchführen
    reset_results = {}
    errors = []
    
    for control_name in controls_to_reset:
        if control_name not in cached_camera_controls:
            errors.append(f"{control_name}: Nicht in gecachten Controls gefunden")
            continue
        
        control_info = cached_camera_controls[control_name]
        
        if "default" not in control_info:
            errors.append(f"{control_name}: Kein Default-Wert verfügbar")
            continue
        
        default_value = control_info["default"]
        
        try:
            # Setze auf Default-Wert
            result = subprocess.run(
                ["v4l2-ctl", "--device", CAMERA_DEVICE, "--set-ctrl", f"{control_name}={default_value}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                errors.append(f"{control_name}: {result.stderr.strip()}")
            else:
                reset_results[control_name] = {
                    "default_value": default_value,
                    "status": "success"
                }
        
        except subprocess.TimeoutExpired:
            errors.append(f"{control_name}: Timeout")
        except Exception as e:
            errors.append(f"{control_name}: {str(e)}")
    
    response = {
        "reset_count": len(reset_results),
        "results": reset_results
    }
    
    if errors:
        response["errors"] = errors
    
    return response


@app.post("/camera/controls")
def set_camera_control(req: CameraControlRequest):
    """
    Setzt einen V4L2 Kamera-Control auf einen neuen Wert.
    Die Validierung erfolgt gegen die gecachten Limits der Kamera.
    """
    # Validiere Control-Name gegen unterstützte Liste
    if req.control not in SUPPORTED_CAMERA_CONTROLS:
        raise HTTPException(
            status_code=400,
            detail=f"Unbekanntes Control '{req.control}'. Unterstützte Controls: {SUPPORTED_CAMERA_CONTROLS}"
        )
    
    # Validiere gegen gecachte Limits
    if not cached_camera_controls:
        raise HTTPException(
            status_code=503,
            detail="Camera Controls noch nicht geladen. Kamera möglicherweise nicht verfügbar."
        )
    
    if req.control not in cached_camera_controls:
        raise HTTPException(
            status_code=404,
            detail=f"Control '{req.control}' wurde von der Kamera nicht gefunden"
        )
    
    limits = cached_camera_controls[req.control]
    
    # Validiere Wert-Bereich gegen tatsächliche Kamera-Limits
    if "min" in limits and "max" in limits:
        if not (limits["min"] <= req.value <= limits["max"]):
            raise HTTPException(
                status_code=400,
                detail=f"Wert {req.value} außerhalb des erlaubten Bereichs [{limits['min']}-{limits['max']}] für {req.control}"
            )
    
    # Setze den Wert
    try:
        # Führe v4l2-ctl Kommando aus
        result = subprocess.run(
            ["v4l2-ctl", "--device", CAMERA_DEVICE, "--set-ctrl", f"{req.control}={req.value}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"v4l2-ctl Fehler: {result.stderr}")
        
        # Hole den neuen Wert zur Bestätigung
        verify_result = subprocess.run(
            ["v4l2-ctl", "--device", CAMERA_DEVICE, "--get-ctrl", req.control],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        current_value = None
        if verify_result.returncode == 0:
            # Parse "contrast: 3" -> 3
            output = verify_result.stdout.strip()
            if ':' in output:
                current_value = int(output.split(':')[1].strip())
        
        return {
            "control": req.control,
            "value": current_value if current_value is not None else req.value,
            "status": "success"
        }
    
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="v4l2-ctl Timeout")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Setzen des Controls: {str(e)}")


@app.get("/status")
def get_status():
    """
    Get comprehensive system status: camera service, recording state, 
    stream availability, disk space, and output directory.
    """
    status = {}
    
    # Check if camera service is responding and get recording state
    camera_service_running = False
    recording_active = False
    session_dir = None
    audio_available = False
    
    try:
        with req_lock:
            req_socket.send_string("STATUS", flags=zmq.NOBLOCK)
            # Wait for response with timeout
            if req_socket.poll(1000):  # 1 second timeout
                response = req_socket.recv_string()
                import json
                camera_status = json.loads(response)
                camera_service_running = True
                recording_active = camera_status.get("recording", False)
                session_dir = camera_status.get("session_dir")
                audio_available = camera_status.get("audio_available", False)
    except (zmq.ZMQError, Exception) as e:
        # Camera service not responding or error occurred
        camera_service_running = False
    
    # Stream availability (check if we're receiving frames)
    stream_available = latest_frame is not None
    
    status["camera_service"] = {
        "running": camera_service_running,
        "stream_available": stream_available,
        "audio_available": audio_available
    }
    
    status["recording"] = {
        "active": recording_active,
        "session_dir": session_dir
    }
    
    status["preview"] = "available" if stream_available else "unavailable"
    
    status["zmq"] = {
        "stream_endpoint": "tcp://127.0.0.1:5555",
        "control_endpoint": "tcp://127.0.0.1:5556"
    }
    
    # Output directory and disk space
    output_dir = os.path.join(os.path.dirname(__file__), "recordings")
    status["output_dir"] = output_dir
    
    # Get disk usage for output directory
    try:
        statvfs = os.statvfs(output_dir if os.path.exists(output_dir) else "/")
        free_gb = (statvfs.f_bavail * statvfs.f_frsize) / (1024**3)
        total_gb = (statvfs.f_blocks * statvfs.f_frsize) / (1024**3)
        used_gb = total_gb - free_gb
        status["disk_space"] = {
            "free_gb": round(free_gb, 2),
            "used_gb": round(used_gb, 2),
            "total_gb": round(total_gb, 2),
            "used_percent": round((used_gb / total_gb * 100), 1) if total_gb > 0 else 0
        }
    except Exception as e:
        status["disk_space"] = {"error": str(e)}
    
    # Hardware status
    status["hardware"] = {
        "servo_angle": current_servo_angle,
        "stepper_position": current_stepper_pos
    }
    
    return status


# Systeminfo-Endpunkt
@app.get("/system/info")
def system_info():
    info = {}
    # CPU-Auslastung
    temps = psutil.sensors_temperatures()
    cpu_thermal = temps.get('cpu_thermal', [])
    info["temperature_celsius"] = cpu_thermal[0].current if cpu_thermal else None
    info["cpu_freq_min_mhz"] = psutil.cpu_freq().min if psutil.cpu_freq() else None
    info["cpu_freq_max_mhz"] = psutil.cpu_freq().max if psutil.cpu_freq() else None
    info["cpu_freq_current_mhz"] = psutil.cpu_freq().current if psutil.cpu_freq() else None
    info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
    info["cpu_count"] = psutil.cpu_count()
    info["cpu_count_logical"] = psutil.cpu_count(logical=True)
    info["cpu_count_physical"] = psutil.cpu_count(logical=False)
    # RAM
    mem = psutil.virtual_memory()
    info["ram_percent"] = mem.percent
    info["ram_total"] = f"{mem.total/1024/1024:.1f} MB"
    info["ram_used"] = f"{mem.used/1024/1024:.1f} MB"
    info["ram_available"] = f"{mem.available/1024/1024:.1f} MB"
    # Festplatten
    disks = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "percent": usage.percent,
                "total": f"{usage.total/1024/1024/1024:.2f} GB",
                "used": f"{usage.used/1024/1024/1024:.2f} GB",
                "free": f"{usage.free/1024/1024/1024:.2f} GB"
            })
        except Exception:
            continue
    info["disks"] = disks
    # Output-Verzeichnis
    output_dir = os.path.join(os.path.dirname(__file__), "recordings")
    files = []
    if os.path.isdir(output_dir):
        for fname in os.listdir(output_dir):
            fpath = os.path.join(output_dir, fname)
            if os.path.isfile(fpath):
                size = os.path.getsize(fpath)
                unit = "B"
                # Menschenlesbare Größe
                for unit in ['B','KB','MB','GB','TB']:
                    if size < 1024.0:
                        break
                    size /= 1024.0
                files.append({
                    "name": fname,
                    "size": f"{size:.2f} {unit}"
                })
    info["output_files"] = files
    # Fehler, wenn Speicherplatz-Limit erreicht
    if disk_space_error.is_set():
        info["disk_space_error"] = f"Wenig Speicherplatz: Aufnahme wurde gestoppt, weil weniger als {DISK_SPACE_LIMIT_GB} GB frei sind. Bitte Speicherplatz freigeben!"
    return info


# System-Shutdown-Endpunkt
@app.post("/system/shutdown")
def system_shutdown():
    try:
        subprocess.Popen(["sudo", "shutdown", "-h", "now"])
        return JSONResponse({"status": "shutdown initiated"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# System-Reboot-Endpunkt
@app.post("/system/reboot")
def system_reboot():
    try:
        subprocess.Popen(["sudo", "reboot"])
        return JSONResponse({"status": "reboot initiated"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
