#!/usr/bin/env bash
# setup_camera.sh – Kamera-Pi komplett einrichten
#
# Usage:  ./setup_camera.sh <aktuelle-ip> <kamera-nr> [gateway]
# Beisp.: ./setup_camera.sh 192.168.178.100 1 192.168.178.2
#
# <aktuelle-ip>  Aktuelle (DHCP-)IP des Pi
# <kamera-nr>    1 → 192.168.178.47 | 2 → 192.168.178.48
# [gateway]      Standard: 192.168.178.2 (mobiler Hotspot)

set -euo pipefail

CURRENT_IP="${1:?Fehler: Aktuelle IP fehlt.  Usage: $0 <ip> <kamera-nr> [gateway]}"
CAMERA_NR="${2:?Fehler: Kamera-Nummer (1 oder 2) fehlt.}"
GATEWAY="${3:-192.168.178.2}"

SSH_USER="kaderblick"
SSH_PASS="kaderblick"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=15"
SSH="sshpass -p ${SSH_PASS} ssh ${SSH_OPTS} ${SSH_USER}@${CURRENT_IP}"
SCP="sshpass -p ${SSH_PASS} scp ${SSH_OPTS}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "$CAMERA_NR" in
    1) STATIC_IP="192.168.178.47" ;;
    2) STATIC_IP="192.168.178.48" ;;
    *) echo "Fehler: Kamera-Nummer muss 1 oder 2 sein."; exit 1 ;;
esac

HOSTNAME="kamera${CAMERA_NR}"

echo "========================================================"
echo "  Einrichten: ${HOSTNAME}  (${STATIC_IP})"
echo "  Aktuelle IP: ${CURRENT_IP}  |  Gateway: ${GATEWAY}"
echo "========================================================"
echo ""

# ── 1. System-Pakete ─────────────────────────────────────────
echo "[1/9] System-Pakete installieren..."
$SSH "sudo systemctl stop packagekit 2>/dev/null || true && sudo apt-get update -q && sudo apt-get install -y \
    portaudio19-dev python3-pyaudio ffmpeg \
    python3-rpi-lgpio swig liblgpio-dev \
    samba"

# ── 2. Code deployen ─────────────────────────────────────────
echo "[2/9] Code deployen..."
$SSH "mkdir -p /home/${SSH_USER}/camera_api/systemd /home/${SSH_USER}/camera_api/recordings"
$SCP "${SCRIPT_DIR}"/*.py              "${SSH_USER}@${CURRENT_IP}:/home/${SSH_USER}/camera_api/"
$SCP "${SCRIPT_DIR}/requirements.txt"  "${SSH_USER}@${CURRENT_IP}:/home/${SSH_USER}/camera_api/"
$SCP "${SCRIPT_DIR}/systemd"/*.service "${SSH_USER}@${CURRENT_IP}:/home/${SSH_USER}/camera_api/systemd/"

# ── 3. Python-Venv ───────────────────────────────────────────
echo "[3/9] Python-Venv einrichten..."
$SSH "cd /home/${SSH_USER}/camera_api && \
    python3 -m venv --system-site-packages venv && \
    venv/bin/pip install --quiet -r requirements.txt"

# ── 4. Systemd-Services ──────────────────────────────────────
echo "[4/9] Systemd-Services einrichten..."
$SSH "sudo cp /home/${SSH_USER}/camera_api/systemd/camera_service.service  /etc/systemd/system/ && \
      sudo cp /home/${SSH_USER}/camera_api/systemd/kaderblick_app.service   /etc/systemd/system/ && \
      sudo systemctl daemon-reload && \
      sudo systemctl enable camera_service kaderblick_app && \
      sudo systemctl restart camera_service kaderblick_app"

# ── 5. Hostname setzen ───────────────────────────────────────
echo "[5/9] Hostname setzen (${HOSTNAME})..."
$SSH "sudo hostnamectl set-hostname ${HOSTNAME}"

# ── 6. Statische IP ──────────────────────────────────────────
echo "[6/9] Statische IP konfigurieren (${STATIC_IP}, Gateway ${GATEWAY})..."
# Netplan-YAML direkt schreiben – nmcli allein reicht nicht, weil netplan apply
# danach die 90-NM-*.yaml liest und nmcli-Änderungen überschreibt.
$SSH "sudo rm -f /etc/netplan/90-NM-*.yaml && \
sudo bash -c 'cat > /etc/netplan/90-kaderblick-static.yaml << EOF
network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      addresses:
        - ${STATIC_IP}/24
      routes:
        - to: default
          via: ${GATEWAY}
      nameservers:
        addresses: [192.168.178.1]
EOF
chmod 600 /etc/netplan/90-kaderblick-static.yaml'"

# ── 7. Persistentes Journal-Logging ──────────────────────────
echo "[7/9] Persistentes Journal-Logging einrichten (max. 500 MB)..."
$SSH "sudo mkdir -p /etc/systemd/journald.conf.d && \
sudo tee /etc/systemd/journald.conf.d/kaderblick.conf > /dev/null << 'JEOF'
[Journal]
Storage=persistent
SystemMaxUse=500M
SystemKeepFree=500M
MaxFileSec=1month
JEOF
sudo mkdir -p /var/log/journal && \
sudo systemd-tmpfiles --create --prefix /var/log/journal && \
sudo systemctl restart systemd-journald"

# ── 8. SMB-Freigabe (recordings) ────────────────────────────
echo "[8/9] SMB-Freigabe einrichten..."
$SSH "grep -q '\[recordings\]' /etc/samba/smb.conf || sudo tee -a /etc/samba/smb.conf > /dev/null << 'SEOF'

[recordings]
   path = /home/${SSH_USER}/camera_api/recordings
   browseable = yes
   read only = no
   valid users = ${SSH_USER}
   create mask = 0664
   directory mask = 0775
   force user = ${SSH_USER}
SEOF
sudo pdbedit -L | grep -q '^${SSH_USER}:' || (echo '${SSH_PASS}'; echo '${SSH_PASS}') | sudo smbpasswd -a ${SSH_USER}
sudo smbpasswd -e ${SSH_USER} && \
sudo systemctl enable smbd nmbd >/dev/null 2>&1 && \
sudo systemctl restart smbd nmbd"

# ── 9. Netzwerk anwenden (IP ändert sich!) ───────────────────
echo "[9/9] Netzwerk anwenden – Verbindung zu ${CURRENT_IP} wird getrennt..."
$SSH "sudo bash -c 'sleep 1 && netplan apply >/dev/null 2>&1 &'" || true   # SSH kehrt sofort zurück, netplan läuft im Hintergrund

echo "    Warte 8 Sekunden auf ${STATIC_IP}..."
sleep 8

# ── Verifikation ─────────────────────────────────────────────
SSH_NEW="sshpass -p ${SSH_PASS} ssh ${SSH_OPTS} -o ConnectTimeout=10 ${SSH_USER}@${STATIC_IP}"
echo ""
echo "=== Verifikation unter ${STATIC_IP} ==="

if $SSH_NEW "echo '-- IP:' && ip addr show eth0 | grep 'inet ' && \
             echo '-- Hostname:' && hostname && \
             echo '-- Services:' && sudo systemctl is-active camera_service kaderblick_app"; then
    echo ""
    echo "================================================================"
    echo "  ${HOSTNAME} erfolgreich eingerichtet unter ${STATIC_IP}"
    echo "================================================================"
else
    echo ""
    echo "FEHLER: ${STATIC_IP} nicht erreichbar nach netplan apply."
    echo "Möglicherweise braucht der Pi etwas länger – manuell prüfen:"
    echo "  ssh ${SSH_USER}@${STATIC_IP}"
    exit 1
fi
