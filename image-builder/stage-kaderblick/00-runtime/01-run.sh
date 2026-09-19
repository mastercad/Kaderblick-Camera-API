#!/bin/bash -e

install -d -m 0755 "${ROOTFS_DIR}/opt/kaderblick/camera_api/src"
install -d -m 0755 "${ROOTFS_DIR}/opt/kaderblick/camera_api/config"
install -d -m 0775 "${ROOTFS_DIR}/srv/kaderblick/recordings"
install -d -m 0755 "${ROOTFS_DIR}/etc/systemd/journald.conf.d"
install -d -m 0755 "${ROOTFS_DIR}/etc/ssh/sshd_config.d"
ln -s /srv/kaderblick/recordings "${ROOTFS_DIR}/opt/kaderblick/camera_api/recordings"
cp -a files/camera-api/src/. "${ROOTFS_DIR}/opt/kaderblick/camera_api/src/"
install -m 0644 files/camera_service.service "${ROOTFS_DIR}/etc/systemd/system/camera_service.service"
install -m 0644 files/kaderblick_app.service "${ROOTFS_DIR}/etc/systemd/system/kaderblick_app.service"
install -m 0644 files/requirements-image.txt "${ROOTFS_DIR}/opt/kaderblick/camera_api/requirements-image.txt"
install -m 0755 files/kaderblick-firstboot.py "${ROOTFS_DIR}/usr/local/sbin/kaderblick-firstboot"
install -m 0644 files/kaderblick-firstboot.service "${ROOTFS_DIR}/etc/systemd/system/kaderblick-firstboot.service"
install -m 0644 files/99-arducam.rules "${ROOTFS_DIR}/etc/udev/rules.d/99-arducam.rules"
install -m 0644 files/journald.conf "${ROOTFS_DIR}/etc/systemd/journald.conf.d/kaderblick.conf"
install -m 0644 files/sshd.conf "${ROOTFS_DIR}/etc/ssh/sshd_config.d/20-kaderblick.conf"

on_chroot << 'EOF'
apt-get -o Acquire::Retries=3 install --no-install-recommends -y fake-hwclock
python3 -m venv --system-site-packages /opt/kaderblick/camera_api/venv
/opt/kaderblick/camera_api/venv/bin/pip install --no-cache-dir -r /opt/kaderblick/camera_api/requirements-image.txt
for group in video audio gpio spi i2c dialout sudo systemd-journal; do
  getent group "${group}" >/dev/null || groupadd --system "${group}"
done
usermod -a -G video,audio,gpio,spi,i2c,dialout,sudo,systemd-journal kaderblick
passwd --lock root
chown -R kaderblick:kaderblick /opt/kaderblick /srv/kaderblick
chmod 0750 /srv/kaderblick/recordings
systemctl enable systemd-networkd.service
systemctl enable ssh.service smbd.service kaderblick-firstboot.service camera_service.service kaderblick_app.service
systemctl enable fstrim.timer 2>/dev/null || true
systemctl disable apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
systemctl disable systemd-networkd-wait-online.service 2>/dev/null || true
systemctl disable systemd-timesyncd.service 2>/dev/null || true
systemctl disable nmbd.service samba-ad-dc.service triggerhappy.service triggerhappy.socket 2>/dev/null || true
systemctl disable rpi-eeprom-update.service rpi-display-backlight.service sshswitch.service hciuart.service 2>/dev/null || true
apt-get purge -y \
  linux-image-rpi-v8 linux-headers-rpi-v8 linux-headers-rpi-2712 \
  python3-pip python3-venv raspi-config systemd-timesyncd triggerhappy || true
apt-get -o APT::AutoRemove::RecommendsImportant=false autoremove --purge -y
rm -f /etc/ssh/ssh_host_*
EOF

CONFIG_TXT="${ROOTFS_DIR}/boot/firmware/config.txt"
if [ ! -f "${CONFIG_TXT}" ]; then
  CONFIG_TXT="${ROOTFS_DIR}/boot/config.txt"
fi
cat >> "${CONFIG_TXT}" << 'EOF'

# Kaderblick: onboard Funkhardware wird nicht verwendet.
dtoverlay=disable-wifi
dtoverlay=disable-bt
usb_max_current_enable=1
EOF
