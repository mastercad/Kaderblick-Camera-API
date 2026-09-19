#!/bin/bash -e

on_chroot << 'EOF'
/opt/kaderblick/camera_api/venv/bin/python - << 'PY'
import cv2
import fastapi
import lgpio
import numpy
import psutil
import pyaudio
import uvicorn
import v4l2
import zmq
PY
ffmpeg -version >/dev/null
arecord --version >/dev/null
smbd -V >/dev/null
v4l2-ctl --version >/dev/null
for service in camera_service kaderblick_app kaderblick-firstboot kaderblick-expand-root smbd ssh systemd-networkd; do
  test "$(systemctl is-enabled "${service}.service")" = enabled
done
for package in linux-image-rpi-v8 linux-headers-rpi-v8 linux-headers-rpi-2712 \
  python3-opencv python3-pip python3-venv raspberrypi-sys-mods raspi-config \
  systemd-timesyncd triggerhappy userconf-pi; do
  ! dpkg-query -W -f='${db:Status-Abbrev}' "${package}" 2>/dev/null | grep -q '^ii'
done
dpkg-query -W -f='${db:Status-Abbrev}' linux-image-rpi-2712 | grep -q '^ii'
test ! -e /etc/ssh/ssh_host_ed25519_key
rm -rf /root/.cache /var/cache/apt/archives/*.deb /var/lib/apt/lists/*
EOF
