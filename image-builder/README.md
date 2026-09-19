# Kaderblick Camera-API-Laufzeitpaket

GitHub Actions erzeugt hier kein bootfähiges Raspberry-Pi-Image. `build-runtime.sh` bündelt ausschließlich Camera API, Dienste, Regeln und den einmaligen Installationscode. Das kleine Paket wird zusammen mit dem offiziellen Raspberry Pi OS Lite und der Kamerakonfiguration durch das Desktop-Tool auf SD-Karte oder USB-Massenspeicher geschrieben.

Der Raspberry Pi installiert die benötigten Debian- und Python-Pakete beim ersten Start über Ethernet. Anschließend werden Installationswerkzeuge und nicht benötigte Funk- und Hintergrunddienste entfernt. Kamera, API, SSH und SMB benötigen im späteren Betrieb weder Internet noch einen Gateway.
