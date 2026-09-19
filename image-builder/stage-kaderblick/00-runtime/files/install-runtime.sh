#!/bin/bash
set -euo pipefail

BOOT=/boot/firmware
PAYLOAD_ARCHIVE="${BOOT}/kaderblick-runtime-bookworm-arm64.tar.xz"
WORK=/run/kaderblick-install

test -s "${PAYLOAD_ARCHIVE}"
rm -rf "${WORK}"
mkdir -p "${WORK}"

export DEBIAN_FRONTEND=noninteractive

# systemd.run wird vor dem normalen multi-user.target ausgefuehrt. Den im
# Raspberry-Pi-OS vorhandenen NetworkManager deshalb hier explizit starten.
systemctl start NetworkManager.service

ethernet_interface=
for interface_path in /sys/class/net/eth* /sys/class/net/en*; do
  test -d "${interface_path}" || continue
  test -d "${interface_path}/wireless" && continue
  ethernet_interface=${interface_path##*/}
  break
done

if test -z "${ethernet_interface}"; then
  echo "Kein Ethernet-Interface gefunden." >&2
  ip link show >&2 || true
  exit 1
fi

networkmanager_device=false
for _ in $(seq 1 30); do
  if nmcli --terse --fields DEVICE,TYPE device status \
    | grep -q "^${ethernet_interface}:ethernet$"; then
    networkmanager_device=true
    break
  fi
  udevadm settle --timeout=2 || true
  sleep 1
done

if test "${networkmanager_device}" != true; then
  echo "NetworkManager hat das Ethernet-Interface ${ethernet_interface} nicht erkannt." >&2
  nmcli device status >&2 || true
  ip link show >&2 || true
  exit 1
fi

setup_address=$(python3 - "${BOOT}/kaderblick-config.json" <<'PY'
import json
import sys

config = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"{config['ip']}/{config['prefix']}")
PY
)

nmcli connection delete kaderblick-setup >/dev/null 2>&1 || true
nmcli connection add type ethernet ifname "${ethernet_interface}" \
  con-name kaderblick-setup connection.autoconnect yes \
  connection.autoconnect-priority 100 ipv4.method auto \
  ipv4.addresses "${setup_address}" ipv6.method disabled
nmcli connection up kaderblick-setup || true

write_setup_resolver() {
  local server
  local temporary=/run/kaderblick-resolv.conf

  : > "${temporary}"
  while IFS= read -r server; do
    test -n "${server}" || continue
    printf 'nameserver %s\n' "${server}" >> "${temporary}"
  done < <(nmcli --get-values IP4.DNS device show "${ethernet_interface}" 2>/dev/null || true)

  # Manche DHCP-Server liefern keinen DNS-Wert. Die Fallbacks werden nur fuer
  # die einmalige Online-Einrichtung verwendet.
  printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' >> "${temporary}"
  install -m 0644 "${temporary}" /etc/resolv.conf
}

network_ready=false
for _ in $(seq 1 60); do
  write_setup_resolver
  if ip -4 route show default dev "${ethernet_interface}" | grep -q '^default ' \
    && getent ahostsv4 deb.debian.org >/dev/null 2>&1; then
    network_ready=true
    break
  fi
  sleep 2
done

if test "${network_ready}" != true; then
  echo "Die Ethernet-Internetverbindung fuer die Ersteinrichtung ist nicht bereit." >&2
  echo "Ethernet-Interface: ${ethernet_interface}" >&2
  ip -4 address show dev "${ethernet_interface}" >&2 || true
  ip -4 route show >&2 || true
  nmcli device show "${ethernet_interface}" >&2 || true
  cat /etc/resolv.conf >&2 || true
  exit 1
fi

synchronize_clock() {
  local synchronized

  systemctl restart systemd-timesyncd.service 2>/dev/null || true
  for _ in $(seq 1 15); do
    synchronized=$(timedatectl show --property=NTPSynchronized --value 2>/dev/null || true)
    if test "${synchronized}" = yes || test "${synchronized}" = true; then
      return 0
    fi
    sleep 1
  done

  # NTP ist in manchen Netzen gesperrt. Da die Debian-Repositories hier
  # ohnehin per HTTP erreichbar sein muessen, deren Date-Header als einmaligen
  # Zeit-Fallback verwenden, bevor APT oder HTTPS gestartet werden.
  python3 <<'PY'
import email.utils
import http.client
import subprocess

connection = http.client.HTTPConnection("deb.debian.org", 80, timeout=15)
connection.request("HEAD", "/debian/")
response = connection.getresponse()
date_header = response.getheader("Date")
connection.close()
if not date_header:
    raise RuntimeError("Debian-Server lieferte keinen Date-Header")
timestamp = int(email.utils.parsedate_to_datetime(date_header).timestamp())
subprocess.run(("date", "--utc", "--set", f"@{timestamp}"), check=True)
PY
}

synchronize_clock
tar -xJf "${PAYLOAD_ARCHIVE}" -C "${WORK}"

apt-get -o Acquire::Retries=3 update
apt-get -o Acquire::Retries=3 --no-install-recommends install -y \
  alsa-utils ca-certificates fake-hwclock openssh-server python3 \
  netplan.io python3-pip python3-psutil python3-rpi-lgpio python3-venv python3-zmq \
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
install -m 0644 "${WORK}/kaderblick-boot-preflight.service" /etc/systemd/system/
install -m 0755 "${WORK}/kaderblick-boot-preflight" /usr/local/sbin/
install -m 0644 "${WORK}/99-arducam.rules" /etc/udev/rules.d/
install -m 0644 "${WORK}/99-kaderblick-gpio.rules" /etc/udev/rules.d/
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

systemctl disable systemd-networkd.service systemd-networkd-wait-online.service 2>/dev/null || true
systemctl enable NetworkManager.service ssh.service smbd.service \
  kaderblick-boot-preflight.service camera_service.service kaderblick_app.service
apt-mark manual network-manager netplan.io >/dev/null
systemctl disable cron.service fstrim.timer logrotate.timer man-db.timer \
  dpkg-db-backup.timer e2scrub_all.timer e2scrub_reap.service \
  systemd-tmpfiles-clean.timer 2>/dev/null || true
systemctl mask apt-daily.service apt-daily-upgrade.service \
  apt-daily.timer apt-daily-upgrade.timer cron.service fstrim.timer logrotate.timer \
  man-db.timer dpkg-db-backup.timer e2scrub_all.timer e2scrub_reap.service \
  rpi-eeprom-update.service rpi-eeprom-update.timer \
  systemd-tmpfiles-clean.timer 2>/dev/null || true
systemctl disable systemd-timesyncd.service nmbd.service samba-ad-dc.service triggerhappy.service triggerhappy.socket 2>/dev/null || true
systemctl disable rpi-eeprom-update.service rpi-display-backlight.service sshswitch.service hciuart.service \
  regenerate_ssh_host_keys.service userconfig.service NetworkManager-wait-online.service 2>/dev/null || true

/usr/local/sbin/kaderblick-firstboot

# Reine Installations- und Funkverwaltungswerkzeuge bleiben nicht auf der
# Kamera. Die Venv ist zu diesem Zeitpunkt vollständig erstellt.
apt-get purge -y \
  avahi-daemon bluez modemmanager pi-bluetooth \
  python3-pip python3-venv raspi-config systemd-timesyncd triggerhappy \
  wpasupplicant 2>/dev/null || true
apt-get -o APT::AutoRemove::RecommendsImportant=false autoremove --purge -y || true

# Erst nach erfolgreicher Einrichtung wird der Einmalstart entfernt. Ein
# vorübergehender Downloadfehler kann dadurch beim nächsten Start erneut
# versucht werden.
python3 - "${BOOT}/cmdline.txt" << 'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
tokens = path.read_text(encoding="utf-8").strip().split()
blocked = ("systemd.run=", "systemd.run_success_action=", "systemd.run_failure_action=", "systemd.unit=")
path.write_text(" ".join(t for t in tokens if not t.startswith(blocked)) + "\n", encoding="utf-8")
PY

rm -rf "${WORK}" "${PAYLOAD_ARCHIVE}" "${BOOT}/kaderblick-install.sh"
apt-get clean
sync
