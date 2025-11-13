# als user pi, im Home-Verzeichnis
python3 -m venv /home/pi/venv
source /home/pi/venv/bin/activate
pip install -r /home/pi/myapp/requirements.txt

# copy service file
sudo cp systemd/camera_service.service /etc/systemd/system/
sudo cp systemd/kaderblick_app.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now camera_service
sudo systemctl enable --now kaderblick_app
sudo journalctl -u camera_service -f
sudo journalctl -u kaderblick_app -f
