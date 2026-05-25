import subprocess

from config import CAMERA_DEVICE, SUPPORTED_CAMERA_CONTROLS

# Gecachte V4L2-Controls – wird beim Modulimport befüllt und von Routen gelesen/mutiert.
cached_camera_controls: dict = {}


def read_camera_controls_from_device(device: str = CAMERA_DEVICE) -> dict:
    """
    Liest alle V4L2-Controls vom Gerät und gibt sie als Dict zurück.

    Format je Eintrag (Integer-Control):
        {"name": str, "supported": bool, "type": "int",
         "min": int, "max": int, "step": int, "default": int, "value": int}

    Format je Eintrag (Menu-Control):
        {"name": str, "supported": bool, "type": "menu",
         "min": int, "max": int, "default": int, "value": int,
         "menu_entries": {"1": "Manual Mode", "3": "Aperture Priority Mode", ...}}
    """
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--device", device, "--list-ctrls-menus"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError(f"v4l2-ctl Fehler: {result.stderr}")

        controls: dict = {}
        current_name: str | None = None
        for line in result.stdout.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue

            # Menu-Eintrag: Zeilen ohne Control-ID (kein "0x") im Anschluss an ein Menu-Control.
            # Format: "        1: Manual Mode" oder "\t\t3: Aperture Priority Mode"
            if current_name is not None and "0x" not in line:
                colon_pos = stripped.find(":")
                if colon_pos > 0:
                    idx_str = stripped[:colon_pos].strip()
                    label = stripped[colon_pos + 1 :].strip()
                    if idx_str.lstrip("-").isdigit() and label:
                        controls[current_name]["menu_entries"][idx_str] = label
                        continue

            current_name = None

            # Control-Header-Zeile: enthält immer eine Control-ID ("0x…") und ":"
            if "0x" not in line or ":" not in line:
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue

            name = parts[0]
            is_menu = "(menu)" in line
            info: dict = {
                "name": name,
                "supported": name in SUPPORTED_CAMERA_CONTROLS,
                "type": "menu" if is_menu else "int",
            }
            for part in parts:
                if "=" in part:
                    key, val = part.split("=", 1)
                    try:
                        info[key] = int(val)
                    except ValueError:
                        info[key] = val
            if is_menu:
                info["menu_entries"] = {}
                current_name = name
            controls[name] = info
        return controls

    except subprocess.TimeoutExpired:
        raise RuntimeError("v4l2-ctl Timeout")
    except Exception as e:
        raise RuntimeError(f"Fehler beim Abrufen der Controls: {e}")


# Beim Modulimport einmalig laden – Fehler werden abgefangen, da Kamera im Test nicht vorhanden.
try:
    cached_camera_controls.update(read_camera_controls_from_device(CAMERA_DEVICE))
    print(f"✓ Camera Controls geladen: {list(cached_camera_controls.keys())}")
except Exception as e:
    print(f"⚠ Warnung: Camera Controls konnten nicht geladen werden: {e}")
    print("  Kamera-Endpunkte funktionieren erst nach erneutem Laden.")
