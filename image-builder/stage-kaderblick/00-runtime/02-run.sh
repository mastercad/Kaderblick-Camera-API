#!/bin/bash -e

rm -f "${ROOTFS_DIR}/etc/init.d/resize2fs_once"
for cmdline in "${ROOTFS_DIR}/boot/firmware/cmdline.txt" "${ROOTFS_DIR}/boot/cmdline.txt"; do
  if [ -f "${cmdline}" ]; then
    sed -i 's| init=/usr/lib/raspberrypi-sys-mods/firstboot||g' "${cmdline}"
  fi
done

install -m 0755 files/kaderblick-expand-root "${ROOTFS_DIR}/usr/local/sbin/kaderblick-expand-root"
install -m 0644 files/kaderblick-expand-root.service "${ROOTFS_DIR}/etc/systemd/system/kaderblick-expand-root.service"

on_chroot << 'EOF'
systemctl disable resize2fs_once 2>/dev/null || true
systemctl enable kaderblick-expand-root.service
EOF
