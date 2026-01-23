# System-Pakete
sudo apt-get update
sudo apt-get install -y portaudio19-dev python3-pyaudio ffmpeg python3-rpi-lgpio swig liblgpio-dev

# Python-Pakete
-- python3 -m venv /home/pi/venv
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements.txt

# copy service file
sudo cp systemd/camera_service.service /etc/systemd/system/
sudo cp systemd/kaderblick_app.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now camera_service
sudo systemctl enable --now kaderblick_app
sudo journalctl -u camera_service -f
sudo journalctl -u kaderblick_app -f

# feste netzwerkaddressen
sudo nano /etc/netplan/01-static-ip.yaml

network:
  version: 2
  ethernets:
    eth0:
      dhcp4: no
      addresses:
        - 192.168.178.47/24
      nameservers:
        addresses: [8.8.8.8, 8.8.4.4]
      routes:
        - to: 0.0.0.0/0
          via: 192.168.178.1

network:
  version: 2
  ethernets:
    eth0:
      dhcp4: no
      addresses:
        - 192.168.178.48/24
      nameservers:
        addresses: [8.8.8.8, 8.8.4.4]
      routes:
        - to: 0.0.0.0/0
          via: 192.168.178.1

sudo chmod 600 /etc/netplan/01-static-ip.yaml

# Untervoltage Warnung deaktivieren
sudo nano /boot/firmware/config.txt

usb_max_current_enable=1

# Optimierungen
## Config
sudo nano /boot/firmware/config.txt

arm_freq=1800
gpu_freq=250
over_voltage=-2
force_turbo=0
dtoverlay=disable-bt
dtoverlay=disable-wifi
dtparam=act_led_trigger=none
hdmi_blanking=2

## SSD Warten
sudo systemctl enable fstrim.timer
sudo systemctl start fstrim.timer

## Mount optimieren
UUID=<deine-uuid> / ext4 noatime,commit=600,discard 0 1

- noatime: verhindert ständige Schreibzugriffe bei Dateizugriffen
- commit=600: schreibt Änderungen nur alle 10 min (spart Schreibzyklen)
- discard: aktiviert TRIM direkt (optional – alternativ per fstrim.timer)
