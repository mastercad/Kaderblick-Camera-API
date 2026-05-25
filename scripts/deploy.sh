#!/usr/bin/env bash
# deploy.sh – Aktuellen Python-Code auf beide Kamera-Pis deployen und Services neustarten
set -euo pipefail

SSH_USER="kaderblick"
SSH_PASS="kaderblick"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=15"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

IPS=("192.168.178.47" "192.168.178.48")

for IP in "${IPS[@]}"; do
    echo "==> Deploying zu ${IP}..."

    SSH="sshpass -p ${SSH_PASS} ssh ${SSH_OPTS} ${SSH_USER}@${IP}"
    SCP="sshpass -p ${SSH_PASS} scp ${SSH_OPTS}"

    $SSH "mkdir -p /home/${SSH_USER}/camera_api/src /home/${SSH_USER}/camera_api/config"

    $SCP "${PROJECT_DIR}"/src/*.py "${SSH_USER}@${IP}:/home/${SSH_USER}/camera_api/src/"

    # udev-Regel: gibt der 'video'-Gruppe Schreibzugriff auf den Arducam USB-Device-Node
    # (wird für USBDEVFS_RESET ioctl benötigt – kein root-Prozess nötig)
    $SSH "echo 'SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"04b4\", ATTRS{idProduct}==\"0822\", MODE=\"0664\", GROUP=\"video\"' \
          | sudo tee /etc/udev/rules.d/99-arducam.rules > /dev/null \
          && sudo udevadm control --reload-rules \
          && sudo udevadm trigger --subsystem-match=usb"

    $SCP "${PROJECT_DIR}/systemd/camera_service.service" "${SSH_USER}@${IP}:/tmp/camera_service.service"
    $SCP "${PROJECT_DIR}/systemd/kaderblick_app.service" "${SSH_USER}@${IP}:/tmp/kaderblick_app.service"
    $SSH "sudo cp /tmp/camera_service.service /etc/systemd/system/camera_service.service && \
          sudo cp /tmp/kaderblick_app.service /etc/systemd/system/kaderblick_app.service && \
          sudo systemctl daemon-reload"

    $SSH "sudo systemctl restart camera_service kaderblick_app"

    echo "==> ${IP} fertig."
done

echo "Deployment abgeschlossen."
