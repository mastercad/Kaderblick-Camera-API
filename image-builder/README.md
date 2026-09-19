# Kaderblick Camera-API-Laufzeitpaket

GitHub Actions erzeugt hier kein bootfähiges Raspberry-Pi-Image. `build-runtime.sh` bündelt ausschließlich Camera API, Dienste, Regeln und den einmaligen Installationscode. Das kleine Paket wird zusammen mit dem offiziellen Raspberry Pi OS Lite und der Kamerakonfiguration durch das Desktop-Tool auf SD-Karte oder USB-Massenspeicher geschrieben.

Der Raspberry Pi installiert die benötigten Debian- und Python-Pakete genau einmal beim ersten Start über Ethernet. Dabei verwaltet der bereits im Raspberry-Pi-OS enthaltene NetworkManager die statische Kamera-IP und die vorübergehende DHCP-Konfiguration für den Internetzugang. Nach erfolgreichem Abschluss entfernt das Init seinen Boot-Eintrag und schreibt die endgültige statische Netzwerkkonfiguration. Kamera, API, SSH und SMB benötigen im späteren Betrieb kein Internet.
