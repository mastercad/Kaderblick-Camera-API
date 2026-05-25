"""
Tests für find_usb_audio.find_usb_audio_device()

Testet: Parsing des arecord-Outputs, Gerät gefunden/nicht gefunden,
Fehlerbehandlung, case-insensitive Suche, verschiedene Card/Device-Nummern.
"""
import subprocess
from unittest.mock import patch

import pytest

from find_usb_audio import find_usb_audio_device


# ---------------------------------------------------------------------------
# Hilfskonstanten – typische arecord -l Ausgaben
# ---------------------------------------------------------------------------

ARECORD_HUAWEI = (
    "**** List of CAPTURE Hardware Devices ****\n"
    "card 1: Device [Huawei USB-C Earphones], device 0: USB Audio [USB Audio]\n"
    "  Subdevices: 1/1\n"
    "  Subdevice #0: subdevice #0\n"
)

ARECORD_EARPODS = (
    "**** List of CAPTURE Hardware Devices ****\n"
    "card 0: PCH [HDA Intel PCH], device 0: ALC898 Analog [ALC898 Analog]\n"
    "  Subdevices: 1/1\n"
    "card 2: EarPods [Apple EarPods], device 0: USB Audio [USB Audio]\n"
    "  Subdevices: 1/1\n"
)

ARECORD_EMPTY = "**** List of CAPTURE Hardware Devices ****\n"

ARECORD_NO_MATCH = (
    "**** List of CAPTURE Hardware Devices ****\n"
    "card 0: PCH [HDA Intel PCH], device 0: ALC898 Analog [ALC898 Analog]\n"
    "  Subdevices: 1/1\n"
)


# ---------------------------------------------------------------------------
# Gerät gefunden
# ---------------------------------------------------------------------------

def test_finds_huawei_device():
    with patch("subprocess.check_output", return_value=ARECORD_HUAWEI):
        assert find_usb_audio_device() == "hw:1,0"


def test_finds_earpods_device():
    with patch("subprocess.check_output", return_value=ARECORD_EARPODS):
        assert find_usb_audio_device() == "hw:2,0"


def test_different_card_and_device_numbers():
    output = (
        "**** List of CAPTURE Hardware Devices ****\n"
        "card 5: Foo [Huawei something], device 3: USB Audio [USB Audio]\n"
    )
    with patch("subprocess.check_output", return_value=output):
        assert find_usb_audio_device() == "hw:5,3"


def test_earpods_card_zero_device_zero():
    output = (
        "**** List of CAPTURE Hardware Devices ****\n"
        "card 0: Bar [EarPods something], device 0: USB Audio [USB Audio]\n"
    )
    with patch("subprocess.check_output", return_value=output):
        assert find_usb_audio_device() == "hw:0,0"


# ---------------------------------------------------------------------------
# Case-insensitive Suche
# ---------------------------------------------------------------------------

def test_case_insensitive_huawei_upper():
    output = "card 3: X [HUAWEI USB], device 1: USB Audio [USB Audio]\n"
    with patch("subprocess.check_output", return_value=output):
        assert find_usb_audio_device() == "hw:3,1"


def test_case_insensitive_earpods_upper():
    output = "card 1: Y [EARPODS USB], device 0: USB Audio [USB Audio]\n"
    with patch("subprocess.check_output", return_value=output):
        assert find_usb_audio_device() == "hw:1,0"


def test_case_insensitive_mixed():
    output = "card 2: Z [HuAwEi something], device 2: USB Audio [USB Audio]\n"
    with patch("subprocess.check_output", return_value=output):
        assert find_usb_audio_device() == "hw:2,2"


# ---------------------------------------------------------------------------
# Gerät nicht gefunden
# ---------------------------------------------------------------------------

def test_returns_none_when_list_empty():
    with patch("subprocess.check_output", return_value=ARECORD_EMPTY):
        assert find_usb_audio_device() is None


def test_returns_none_when_no_matching_device():
    with patch("subprocess.check_output", return_value=ARECORD_NO_MATCH):
        assert find_usb_audio_device() is None


# ---------------------------------------------------------------------------
# Fehlerbehandlung
# ---------------------------------------------------------------------------

def test_returns_none_on_file_not_found():
    with patch("subprocess.check_output", side_effect=FileNotFoundError("arecord not found")):
        assert find_usb_audio_device() is None


def test_returns_none_on_called_process_error():
    with patch(
        "subprocess.check_output",
        side_effect=subprocess.CalledProcessError(1, "arecord"),
    ):
        assert find_usb_audio_device() is None


def test_returns_none_on_generic_exception():
    with patch("subprocess.check_output", side_effect=RuntimeError("unexpected")):
        assert find_usb_audio_device() is None


# ---------------------------------------------------------------------------
# Erster Treffer gewinnt
# ---------------------------------------------------------------------------

def test_returns_first_match_when_multiple_found():
    output = (
        "**** List of CAPTURE Hardware Devices ****\n"
        "card 1: A [Huawei USB], device 0: USB Audio [USB Audio]\n"
        "card 3: B [EarPods USB], device 0: USB Audio [USB Audio]\n"
    )
    with patch("subprocess.check_output", return_value=output):
        # Huawei kommt zuerst → hw:1,0
        assert find_usb_audio_device() == "hw:1,0"
