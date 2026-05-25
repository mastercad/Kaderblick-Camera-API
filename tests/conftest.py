"""
Globale pytest-Konfiguration.

Mockt Hardware-Module die auf dem Entwicklungsrechner nicht verfügbar sind,
BEVOR die Application-Module importiert werden.
"""
import os
import sys
from unittest.mock import MagicMock

# src/ zum Suchpfad hinzufügen damit alle App-Module importierbar sind
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# -----------------------------------------------------------------------
# lgpio – GPIO-Bibliothek (nur auf Raspberry Pi verfügbar)
# -----------------------------------------------------------------------
_lgpio_mock = MagicMock()
_lgpio_mock.gpiochip_open.return_value = 99  # fake chip handle
sys.modules["lgpio"] = _lgpio_mock

# -----------------------------------------------------------------------
# v4l2 – C-Extension (nur auf Linux mit v4l2-python3 verfügbar)
# -----------------------------------------------------------------------
_v4l2_mock = MagicMock()
# Häufig genutzte Konstanten, damit Code wie `v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE`
# einen reproduzierbaren Wert hat (statt einem neuen MagicMock bei jedem Zugriff).
_v4l2_mock.V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
_v4l2_mock.V4L2_MEMORY_MMAP = 2
_v4l2_mock.V4L2_PIX_FMT_MJPEG = 1196444237
_v4l2_mock.V4L2_FIELD_NONE = 1
_v4l2_mock.VIDIOC_S_FMT = 0xC0D05605
_v4l2_mock.VIDIOC_REQBUFS = 0xC0145608
_v4l2_mock.VIDIOC_QUERYBUF = 0xC0445609
_v4l2_mock.VIDIOC_QBUF = 0x40045615
_v4l2_mock.VIDIOC_DQBUF = 0xC0445611
_v4l2_mock.VIDIOC_STREAMON = 0x40045612
_v4l2_mock.VIDIOC_STREAMOFF = 0x40045613
sys.modules["v4l2"] = _v4l2_mock

# -----------------------------------------------------------------------
# numpy / cv2 – ggf. nicht im venv installiert
# -----------------------------------------------------------------------
try:
    import numpy  # noqa: F401
except ImportError:
    sys.modules["numpy"] = MagicMock()

try:
    import cv2  # noqa: F401
except ImportError:
    _cv2_mock = MagicMock()
    _cv2_mock.VideoWriter_fourcc.return_value = 0x47504A4D
    sys.modules["cv2"] = _cv2_mock
