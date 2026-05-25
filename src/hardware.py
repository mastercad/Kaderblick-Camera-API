import time
from threading import Lock

import lgpio  # type: ignore[import]

from config import SERVO_PIN, SERVO_FREQ, STEPPER_PINS, STEPPER_SEQUENCE

# ==============================
# GPIO-Initialisierung
# ==============================
h = lgpio.gpiochip_open(0)
lgpio.gpio_claim_output(h, SERVO_PIN)
for _pin in STEPPER_PINS:
    lgpio.gpio_claim_output(h, _pin)

# ==============================
# Zustand
# ==============================
current_servo_angle: int = 90
current_stepper_pos: int = 0

servo_lock = Lock()
stepper_lock = Lock()


# ==============================
# Servo
# ==============================

def angle_to_pulse(angle: int) -> float:
    """Wandelt Winkel (0–180°) in Pulslänge in µs um."""
    return 500 + (angle / 180) * 2000


def move_servo_absolute(angle: int) -> None:
    """Fährt den Servo auf einen absoluten Winkel (0–180°)."""
    global current_servo_angle
    with servo_lock:
        angle = max(0, min(180, angle))
        duty_cycle = (angle_to_pulse(angle) / 20000) * 100  # µs → % bei 20 ms Periode
        lgpio.tx_pwm(h, SERVO_PIN, SERVO_FREQ, duty_cycle)
        time.sleep(0.3)
        lgpio.tx_pwm(h, SERVO_PIN, SERVO_FREQ, 0)
        current_servo_angle = angle


def move_servo_relative(degrees: int) -> None:
    """Bewegt den Servo relativ zur aktuellen Position."""
    move_servo_absolute(current_servo_angle + degrees)


# ==============================
# Stepper
# ==============================

def move_stepper_relative(steps: int, delay: float = 0.002) -> None:
    """Bewegt den Stepper-Motor um eine relative Schrittanzahl."""
    global current_stepper_pos
    with stepper_lock:
        for _ in range(abs(steps)):
            idx = current_stepper_pos % 8
            for pin, val in zip(STEPPER_PINS, STEPPER_SEQUENCE[idx]):
                lgpio.gpio_write(h, pin, val)
            time.sleep(delay)
            current_stepper_pos += 1 if steps > 0 else -1
        for pin in STEPPER_PINS:
            lgpio.gpio_write(h, pin, 0)


def move_stepper_absolute(target: int, delay: float = 0.002) -> None:
    """Fährt den Stepper-Motor auf eine absolute Position."""
    move_stepper_relative(target - current_stepper_pos, delay)
