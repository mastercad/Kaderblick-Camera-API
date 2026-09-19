#!/bin/bash
set -euo pipefail

BOOT=/boot/firmware
PAYLOAD_ARCHIVE="${BOOT}/kaderblick-runtime-bookworm-arm64.tar.xz"
WORK=/run/kaderblick-install

test -s "${PAYLOAD_ARCHIVE}"
rm -rf "${WORK}"
mkdir -p "${WORK}"
tar -xJf "${PAYLOAD_ARCHIVE}" -C "${WORK}"

export DEBIAN_FRONTEND=noninteractive
apt-get -o Acquire::Retries=3 update
apt-get -o Acquire::Retries=3 --no-install-recommends install -y \
  alsa-utils ca-certificates fake-hwclock openssh-server python3 \
  python3-pip python3-psutil python3-rpi-lgpio python3-venv python3-zmq \
  samba samba-common-bin sudo usbutils v4l-utils

install -d -m 0755 /opt/kaderblick/camera_api/src /opt/kaderblick/camera_api/config
install -d -m 0775 /srv/kaderblick/recordings
cp -a "${WORK}/camera-api/src/." /opt/kaderblick/camera_api/src/
cp "${WORK}/requirements-image.txt" /opt/kaderblick/camera_api/
ln -sfn /srv/kaderblick/recordings /opt/kaderblick/camera_api/recordings

python3 -m venv --system-site-packages /opt/kaderblick/camera_api/venv
/opt/kaderblick/camera_api/venv/bin/pip install --no-cache-dir \
  -r /opt/kaderblick/camera_api/requirements-image.txt

install -m 0644 "${WORK}/camera_service.service" /etc/systemd/system/
install -m 0644 "${WORK}/kaderblick_app.service" /etc/systemd/system/
install -m 0644 "${WORK}/99-arducam.rules" /etc/udev/rules.d/
install -d -m 0755 /etc/systemd/journald.conf.d /etc/ssh/sshd_config.d
install -m 0644 "${WORK}/journald.conf" /etc/systemd/journald.conf.d/kaderblick.conf
install -m 0644 "${WORK}/sshd.conf" /etc/ssh/sshd_config.d/20-kaderblick.conf
install -m 0755 "${WORK}/kaderblick-firstboot.py" /usr/local/sbin/kaderblick-firstboot

getent group kaderblick >/dev/null || groupadd kaderblick
id kaderblick >/dev/null 2>&1 || useradd --create-home --gid kaderblick --shell /bin/bash kaderblick
for group in video audio gpio spi i2c dialout sudo systemd-journal; do
  getent group "${group}" >/dev/null || groupadd --system "${group}"
done
passwd --lock root

systemctl disable NetworkManager.service NetworkManager-wait-online.service 2>/dev/null || true
systemctl enable systemd-networkd.service ssh.service smbd.service camera_service.service kaderblick_app.service
systemctl enable fstrim.timer 2>/dev/null || true
systemctl disable apt-daily.timer apt-daily-upgrade.timer systemd-networkd-wait-online.service 2>/dev/null || true
systemctl disable systemd-timesyncd.service nmbd.service samba-ad-dc.service triggerhappy.service triggerhappy.socket 2>/dev/null || true
systemctl disable rpi-eeprom-update.service rpi-display-backlight.service sshswitch.service hciuart.service 2>/dev/null || true

/usr/local/sbin/kaderblick-firstboot

# Reine Installations- und Funkverwaltungswerkzeuge bleiben nicht auf der
# Kamera. Die Venv ist zu diesem Zeitpunkt vollständig erstellt.
apt-get purge -y \
  avahi-daemon bluez modemmanager network-manager pi-bluetooth \
  python3-pip python3-venv raspi-config systemd-timesyncd triggerhappy \
  wpasupplicant 2>/dev/null || true
apt-get -o APT::AutoRemove::RecommendsImportant=false autoremove --purge -y

# Erst nach erfolgreicher Einrichtung wird der Einmalstart entfernt. Ein
# vorübergehender Downloadfehler kann dadurch beim nächsten Start erneut
# versucht werden.
python3 - "${BOOT}/cmdline.txt" << 'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
tokens = path.read_text(encoding="utf-8").strip().split()
blocked = ("systemd.run=", "systemd.run_success_action=", "systemd.unit=")
path.write_text(" ".join(t for t in tokens if not t.startswith(blocked)) + "\n", encoding="utf-8")
PY

rm -rf "${WORK}" "${PAYLOAD_ARCHIVE}" "${BOOT}/kaderblick-install.sh"
apt-get clean
sync
