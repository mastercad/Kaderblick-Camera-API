import subprocess
import re

def find_usb_audio_device(name_pattern=None):
    """
    Sucht das ALSA-Device (z.B. hw:1,0) für ein USB-Audio-Gerät anhand des Namensmusters.
    Gibt den Gerätenamen (z.B. 'hw:1,0') zurück oder None, wenn nicht gefunden.
    Loggt den Output von arecord -l.
    """
    import logging
    try:
        output = subprocess.check_output(["arecord", "-l"], encoding="utf-8")
        logging.info("arecord -l Output:\n" + output)
    except Exception as e:
        logging.error(f"arecord -l Fehler: {e}")
        return None
    card = None
    device = None
    # Suche nach 'huawei' oder 'earpods' (case-insensitive)
    for line in output.splitlines():
        if re.search(r'(huawei|earpods)', line, re.IGNORECASE):
            m = re.search(r'card (\d+):.*device (\d+):', line)
            if m:
                card = m.group(1)
                device = m.group(2)
                logging.info(f"USB-Audio-Device gefunden: {line.strip()} => hw:{card},{device}")
                return f"hw:{card},{device}"
    logging.error("Kein passendes USB-Audio-Device gefunden!")
    return None
