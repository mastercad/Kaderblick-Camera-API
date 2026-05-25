# ==============================
# Kamera
# ==============================
CAMERA_DEVICE = "/dev/video0"
SUPPORTED_CAMERA_CONTROLS = [
    "contrast",
    "saturation",
    "gain",
    "sharpness",
    "auto_exposure",
    "exposure_time_absolute",
]

# ==============================
# Servo
# ==============================
SERVO_PIN = 18       # PWM GPIO für MG90S
SERVO_FREQ = 50      # 50 Hz – typisch für Hobby-Servos

# ==============================
# Stepper (ULN2003 IN1–IN4)
# ==============================
STEPPER_PINS = [17, 27, 20, 21]
# Halbschritt-Sequenz (8 Schritte)
STEPPER_SEQUENCE = [
    [1, 0, 0, 0],
    [1, 1, 0, 0],
    [0, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 0],
    [0, 0, 1, 1],
    [0, 0, 0, 1],
    [1, 0, 0, 1],
]

# ==============================
# Aufnahme / Speicherplatz
# ==============================
DISK_SPACE_LIMIT_GB = 30   # Aufnahme stoppen wenn weniger als 30 GB frei

# ==============================
# Authentifizierung
# ==============================
API_KEY = "mein_sicherer_key"
