#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="${1:?Repository root fehlt}"
PI_GEN_ROOT="${2:?pi-gen root fehlt}"
STAGE_SOURCE="${REPOSITORY_ROOT}/image-builder/stage-kaderblick"
STAGE_TARGET="${PI_GEN_ROOT}/stage-kaderblick"
FIRMWARE_PACKAGES="${PI_GEN_ROOT}/stage0/02-firmware/01-packages"
STAGE1_NET_SCRIPT="${PI_GEN_ROOT}/stage1/02-net-tweaks/00-run.sh"
EXPORT_CLEAN_SOURCE="${REPOSITORY_ROOT}/image-builder/export-kaderblick-clean"
EXPORT_CLEAN_TARGET="${PI_GEN_ROOT}/export-image/04-kaderblick-clean"

# Das Appliance-Image ist ausschließlich für Raspberry Pi 5 bestimmt. Der
# generische ARM64-Kernel und Kernel-Header würden nur Buildzeit und Platz
# kosten; für die vorinstallierten UVC-/GPIO-Treiber werden keine Header
# benötigt.
sed -i \
  -e '/^linux-image-rpi-v8$/d' \
  -e '/^linux-headers-rpi-v8$/d' \
  -e '/^linux-headers-rpi-2712$/d' \
  "${FIRMWARE_PACKAGES}"
grep -qx 'linux-image-rpi-2712' "${FIRMWARE_PACKAGES}"

# Stage 1 nutzt raspi-config ausschließlich zum Abschalten vorhersehbarer
# Interface-Namen. Die beiden von raspi-config erzeugten Links reichen aus und
# vermeiden dessen umfangreichen Werkzeug-/EEPROM-Abhängigkeitsbaum.
rm -f "${PI_GEN_ROOT}/stage1/01-sys-tweaks/00-packages"
# ROOTFS_DIR muss erst im pi-gen-Build expandieren.
# shellcheck disable=SC2016
sed -i '/on_chroot << EOF/,/^EOF$/c\
install -d -m 0755 "${ROOTFS_DIR}/etc/systemd/network"\
ln -sf /dev/null "${ROOTFS_DIR}/etc/systemd/network/99-default.link"\
ln -sf /dev/null "${ROOTFS_DIR}/etc/systemd/network/73-usb-net-by-mac.link"' \
  "${STAGE1_NET_SCRIPT}"

# Bei fest vorgegebenem Benutzer darf die Exportstufe userconf-pi nicht wieder
# nachinstallieren. Unsere letzte Exportstufe validiert das Laufzeitsystem und
# entfernt erst danach Paketlisten und andere Buildreste.
rm -f "${PI_GEN_ROOT}/export-image/01-user-rename/00-packages"
cp -a "${EXPORT_CLEAN_SOURCE}" "${EXPORT_CLEAN_TARGET}"

cp -a "${STAGE_SOURCE}" "${STAGE_TARGET}"
mkdir -p "${STAGE_TARGET}/00-runtime/files/camera-api"
cp -a "${REPOSITORY_ROOT}/src" "${STAGE_TARGET}/00-runtime/files/camera-api/src"
