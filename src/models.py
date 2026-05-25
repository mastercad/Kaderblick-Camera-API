from pydantic import BaseModel


class ServoAbsoluteRequest(BaseModel):
    angle: int  # 0–180°

    def __init__(self, **data):
        super().__init__(**data)
        if not 0 <= self.angle <= 180:
            raise ValueError("Angle must be between 0 and 180")


class ServoRelativeRequest(BaseModel):
    degrees: int  # relative Bewegung in Grad (+/-)


class StepperRelativeRequest(BaseModel):
    steps: int
    delay: float = 0.002


class StepperAbsoluteRequest(BaseModel):
    position: int  # absolute Zielposition
    delay: float = 0.002


class CameraControlRequest(BaseModel):
    control: str  # V4L2-Control-Name (z. B. contrast, gain, …)
    value: int


class CameraControlResetRequest(BaseModel):
    control: str | None = None  # None → alle unterstützten Controls


class CameraResolutionRequest(BaseModel):
    width: int
    height: int
    fps: int
