# Diagnosezustand: V4L2-/MJPEG-Frameverluste

Stand: 11. Oktober 2026 (Europe/Berlin)

Dieses Dokument ist der verbindliche Zwischenstand der Ursachenanalyse. Es
trennt Messwerte, daraus zulässige Schlussfolgerungen und noch offene Fragen.
Frühere Prüfungen sollen nicht ohne neue Evidenz wiederholt oder als neue
Ursachenerklärung präsentiert werden.

## Verbindliche Bewertungsmethode

Folgende Beobachtungen sind ausdrücklich **kein** Ursachen-, Referenz- oder
Wirksamkeitsbeleg:

- ein einzelnes Fehlerereignis oder ein einzelner Fehlerburst;
- ein einzelner fehlerfreier oder fehlerhafter Testlauf;
- ein einmaliger Vorher-/Nachher-Vergleich;
- ein einmaliger Wechsel einer Einstellung zwischen Kamera 1 und Kamera 2;
- eine zeitliche Korrelation ohne reproduzierbaren Zusammenhang.

Eine Änderung darf erst bewertet werden, wenn vorher Messgröße, Messdauer und
Vergleichsbedingungen festgelegt wurden, beide Zustände mehrfach über für die
sporadischen Fehler ausreichend lange Zeiträume gemessen wurden und das
Ergebnis in Wiederholungen bestehen bleibt. Einzelbeobachtungen dürfen nur als
Anlass für einen solchen Test dienen, nicht als dessen Ergebnis.

Kreuztests sind ausdrücklich zulässig. Sie müssen wiederholt und alternierend
durchgeführt werden. Unterschiede zwischen nur einem Kamerapaar oder nur einem
Zeitfenster dürfen nicht dem getauschten Parameter zugerechnet werden, solange
die natürliche Schwankung der beiden Systeme nicht durch Wiederholungen
erfasst ist.

## Beobachtetes Fehlerbild

Die Fehler treten auf beiden Kamera-Pis auch ohne laufende Aufnahme und bei
deaktivierter Auslieferung des Preview-Streams auf. Der Prozess erhält über
`VIDIOC_DQBUF` sowohl V4L2-Sequenzsprünge als auch unvollständige oder
offensichtlich nicht am JPEG-Anfang beginnende Puffer.

Beispiele aus `GET /health/events`:

- Kamera 1: Sequenz `43560 -> 43570`, neun fehlende Sequenzen; der anschließend
  gelieferte Puffer hatte 16.255 Byte und weder JPEG-SOI noch JPEG-EOI.
- Kamera 2: Sequenz `45606 -> 45608`, eine fehlende Sequenz; der Puffer bei
  Sequenz 45606 hatte 1.015.064 Byte, begann mit JPEG-SOI, enthielt aber kein
  JPEG-EOI. Darauf folgten mehrere etwa 16-KB-Puffer ohne SOI und EOI.
- Die kleinen ungültigen Puffer enthalten unterschiedliche Nutzdaten und sind
  keine leeren Puffer.

Damit ist belegt, dass diese konkreten Fehler vor Preview-Decodierung,
Netzwerkübertragung und Dateischreiben sichtbar sind. Noch nicht belegt ist,
ob die fehlerhaften Puffer durch Kamera/Firmware, USB-Übertragung, `uvcvideo`
oder eine fehlerhafte Initialisierung beziehungsweise Nutzung von V4L2 durch
unsere Anwendung entstehen.

## Vergleich beider laufender Systeme

Beide Systeme waren zum Messzeitpunkt gleich konfiguriert:

- Arducam B0589 4K HDR, USB-ID `04b4:0822`
- ausgehandeltes Format: `3840x2160`, MJPEG, 30 fps
- Zielrate der gespeicherten Aufnahme: 15 fps; Auswahl jedes zweiten der von
  der Kamera gelieferten 30-fps-Frames
- Kamera jeweils allein an einem eigenen 5-Gbit/s-xHCI-Controller
- zwölf von V4L2 tatsächlich bereitgestellte MMAP-Capture-Puffer
- Linux `6.12.75+rpt-rpi-2712` auf beiden Pis

Die später vollständig ausgelesenen Geräteprofile stimmen ebenfalls überein:

- UVC 1.10, Bulk-Endpunkt `0x81`, `wMaxPacketSize=1024`, `bMaxBurst=7`;
- `bcdDevice=0.00`;
- dieselbe vom Gerät gemeldete Serienkennung `Arducam_20250812_0001` auf beiden
  physischen Kameras;
- identische Wertebereiche und aktuelle Werte für Kontrast, Sättigung, Gain,
  Schärfe und Belichtung.

Die identische Serienkennung eignet sich daher nicht zur eindeutigen
Identifikation der beiden physischen Geräte.

Beide Geräte bieten für MJPEG bei `3840x2160` ausschließlich 30 fps an. Ein
direkter 4K-MJPEG-Modus mit 15 fps wird nicht enumeriert. 4K mit 15 fps wird nur
als unkomprimiertes YUYV angeboten. Der aktuelle Code empfängt deshalb den
MJPEG-Stream mit 30 fps und wählt für eine 15-fps-Aufnahme jedes zweite Bild
aus; er kann die Kamera in diesem MJPEG-Modus nicht regelkonform auf 15 fps
stellen.

Statuswerte nach demselben Lauf:

| Messwert | Kamera 1 | Kamera 2 |
| --- | ---: | ---: |
| empfangene Puffer | 46.492 | 46.505 |
| V4L2-Sequenzsprünge | 111 | 127 |
| laut Sequenz fehlende Frames | 469 | 568 |
| ungültige/unvollständige MJPEG-Puffer | 121 | 132 |
| `V4L2_BUF_FLAG_ERROR` | 0 | 0 |
| maximale Pufferhaltezeit im Capture-Code | 6,123 ms | 4,261 ms |
| maximale Writer-Queue-Tiefe | 1 | 1 |
| Writer-Queue-Drops | 0 | 0 |
| aktuelles Undervoltage-Flag | nein | nein |

Die Zähler werden derzeit beim Start einer Aufnahme zurückgesetzt. Sie sind
daher keine Lebenszeitzähler des Geräts, sondern gelten seit dem letzten Reset
der Aufnahmezähler.

## Bereits ausgeschlossene Erklärungen für dieses Fehlerbild

Die folgenden Punkte erklären die hier gemessenen Sequenzsprünge und kaputten
DQBUF-Nutzdaten nicht:

- **Preview-Netzwerk oder Android-Darstellung:** Die Fehler werden im
  Capture-Prozess vor der Preview-Auslieferung gemessen und treten bei
  `stream_active=false` auf.
- **Schreibgeschwindigkeit der Aufnahme:** Zum Messzeitpunkt lief keine
  Aufnahme. In der vorangegangenen Aufnahme gab es außerdem keine
  Writer-Queue-Drops; die maximale Queue-Tiefe war eins.
- **Blockierendes Dateischreiben im Capture-Thread:** Das Schreiben erfolgt im
  aktuellen Code über einen separaten Writer-Thread. Der V4L2-Puffer wird nach
  einer Bytekopie zurückgegeben.
- **Zu lange gehaltene V4L2-Puffer als Erklärung der gemessenen Bursts:** Die
  maximal gemessenen Haltezeiten von 6,123 ms beziehungsweise 4,261 ms liegen
  deutlich unter dem ausgehandelten Frameintervall von 33,333 ms. Das schließt
  nicht jede Form von Userspace-Fehler aus, aber einen durch die gemessene
  Pufferhaltezeit verursachten Rückstau.
- **Hohe allgemeine Systemlast:** Bei der Prüfung lagen die Load-Averages unter
  0,12, mehrere GiB RAM waren verfügbar und Swap wurde nicht benutzt.
- **Aktuelle Unterspannung oder Drosselung:** Während der Fehlerprüfung waren
  die aktuellen Flags nicht gesetzt. Auf beiden Pis ist jedoch eine kurze
  Unterspannung direkt nach dem Boot am 10. Oktober protokolliert; daraus folgt
  keine Erklärung für Fehlerbursts am 11. Oktober.

Aus diesen Ausschlüssen folgt ausdrücklich **nicht**, dass die Kamerahardware
defekt ist.

## Relevante Kernel-Beobachtungen

Auf beiden Pis protokollierte `uvcvideo` am 11. Oktober mehrfach:

```text
uvcvideo 4-1:1.1: Non-zero status (-71) in video completion handler.
```

`-71` entspricht einem USB-Protokollfehler. Diese Meldungen belegen UVC-/USB-
Übertragungsfehler zu den jeweiligen Zeitpunkten. Für die zuletzt beobachteten
Fehlerbursts um 13:34 bis 13:35 Uhr gab es jedoch keine zeitgleiche neue
Kernelmeldung. Deshalb ist noch nicht belegt, dass sämtliche DQBUF-Fehler
durch denselben USB-Fehler verursacht werden.

Die zahlreichen `reset SuperSpeed USB device`-Meldungen sind überwiegend durch
unsere Service-Starts, Konfigurationswechsel und Diagnosetests verursacht. Sie
dürfen nicht als spontane Hardware-Resets interpretiert werden.

Auf Kamera 2 wurden während früherer Tests zeitweise erzwungene
`uvcvideo quirks` (`0x20000` und `0x10`) geladen und danach wieder entfernt.
Diese Testzeiträume dürfen nicht zur Bewertung des Normalbetriebs verwendet
werden. Aktuell steht der Modulparameter `quirks` auf dem automatischen
Standardwert `4294967295` und es existiert keine persistente Quirk-Konfiguration.

## Bewertung des aktuellen Capture-Codes

Der normale MMAP-Ablauf ist im Code grundsätzlich vorhanden:

1. `VIDIOC_REQBUFS`, `VIDIOC_QUERYBUF`, `mmap` und initiales `VIDIOC_QBUF`
2. `VIDIOC_STREAMON`
3. `select`, `VIDIOC_DQBUF`, Kopieren von `mm[:buf.bytesused]`
4. Validierung auf JPEG-SOI/EOI
5. `VIDIOC_QBUF`

Die kopierten `bytes` werden erst nach dem Kopieren an Writer und Preview
weitergegeben. Ein späteres Überschreiben des MMAP-Puffers erklärt daher die
beobachteten ungültigen Bytes nicht.

Noch nicht unabhängig verifiziert sind insbesondere:

- ob zwölf statt der früher verwendeten vier MMAP-Puffer das Verhalten des
  Treibers oder der Kamera beeinflussen;
- ob Format und Framerate nach `VIDIOC_S_FMT` und `VIDIOC_S_PARM` im Code erneut
  ausgelesen und vollständig validiert werden müssen;
- ob UVC-Payload-Grenzen beziehungsweise FID/EOF-Markierungen dieser
  Kamerafirmware vom aktuellen `uvcvideo`-Treiber zeitweise falsch
  zusammengesetzt werden.

## Kontrollierte A/B-Tests des Capture-Pfads

Die unabhängigen A/B-Tests wurden auf Kamera 1 mit `v4l2-ctl`, zwölf MMAP-Puffern
und `3840x2160 MJPEG @ 30 fps` durchgeführt. Der Python-Capture-Code war dabei
nicht aktiv:

| Startbedingung | Einzeltest über 600 Puffer |
| --- | --- |
| kein vorheriger USB-Reset | 600 fortlaufende Sequenzen, keine Lücke |
| `USBDEVFS_RESET`, danach 1 Sekunde warten | 7 Sequenzlücken, 14 fehlende Frames, Puffer bis hinunter zu 16.139 Byte |
| `USBDEVFS_RESET`, danach 5 Sekunden warten | 600 fortlaufende Sequenzen, keine Lücke; 1.489.896 bis 1.506.268 Byte pro Puffer |

Dieser Einzelvergleich war **nicht reproduzierbar**. Es folgten je fünf weitere
Läufe pro Bedingung mit jeweils 300 Puffern:

| Bedingung | Läufe | Sequenzlücken | Puffer unter 1.000.000 Byte |
| --- | ---: | ---: | ---: |
| Reset, 1 Sekunde warten | 5 | 0 | 0 |
| Reset, 5 Sekunden warten | 5 | 0 | 0 |
| kein neuer Reset | 5 | 0 | 0 |

Bei den fünf direkt an einen vorherigen Stream anschließenden Läufen ohne Reset
lieferte V4L2 jeweils zwölf initiale Puffer mit ERROR-Flag und ohne Nutzdaten.
`v4l2-ctl` zählte diese nicht zu den 300 Videopuffern; danach waren Sequenzen,
Abstände und Puffergrößen unauffällig.

Damit ist derzeit nur belegt:

- Das einmal mit `v4l2-ctl` beobachtete Fehlerbild benötigte den Python-Prozess
  nicht. Dieser Einzelbefund beweist weder, dass alle beobachteten Fehler
  dieselbe Ursache haben, noch schließt er zusätzliche Fehler im Python-Code
  aus.
- Der zeitliche Abstand nach `USBDEVFS_RESET` ist nach diesen Messungen **nicht
  als Ursache belegt**. Die einmalige Korrelation darf nicht als Kausalität
  behandelt werden.

Die Ursache der sporadischen Bursts ist weiterhin offen. Für die nächste
Ursacheneingrenzung sind längere, gleichzeitige Messfenster erforderlich, in
denen V4L2-Pufferdaten, Kernel-UVC-/USB-Status und Systemzustand mit derselben
Zeitbasis erfasst werden. Kurze fehlerfreie Läufe widerlegen sporadische Fehler
nicht.

### Alternierende Wiederholungsreihe: Python-Capture gegen `v4l2-ctl`

Am 11. Oktober folgte eine längere Reihe mit identischen Streamparametern und
ohne laufenden Kameradienst: pro Kamera zehn Blöcke zu jeweils 120 Sekunden,
abwechselnd fünf Blöcke mit der isolierten `V4L2MJPGStreamer`-Klasse und fünf
Blöcke mit `v4l2-ctl`. Beide Leser verwendeten 3840x2160 MJPEG bei 30 fps und
zwölf MMAP-Puffer. Die Reihenfolge war zwischen den beiden Kameras vertauscht.

| Kamera | Leser | Läufe | UVC-Frames | Läufe mit UVC-Fehlern | Error-Payloads | ungültige Header |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | Python-Capture | 5 | 17.990 | 0 | 0 | 0 |
| 1 | `v4l2-ctl` | 5 | 17.995 | 0 | 0 | 0 |
| 2 | Python-Capture | 5 | 17.990 | 0 | 0 | 0 |
| 2 | `v4l2-ctl` | 5 | 18.014 | 1 | 18 | 4 |

Unmittelbar vor dieser Reihe hatte ein separater 120-Sekunden-Pilot mit der
isolierten Python-Klasse auf Kamera 2 vier Kernel-Error-Payloads, drei
ungültige UVC-Header, zwei V4L2-Sequenzsprünge, elf fehlende Sequenzen und ein
ungültiges MJPEG ergeben; der gleichzeitige Python-Pilot auf Kamera 1 blieb
sauber. Dieser Pilot gehört wegen der abweichenden Stellung in der
Testreihenfolge nicht in die obige Summierung.

Damit ist über getrennte Läufe belegt, dass sowohl der unabhängige Leser als
auch die Python-Klasse von dem Fehler betroffen sein können. Der eigene
Python-Capturepfad ist für das Auftreten folglich nicht erforderlich. Die
Reihe belegt wegen der geringen Zahl sporadischer Ereignisse ausdrücklich
keinen Unterschied der Fehlerrate zwischen den beiden Lesern und keinen
Unterschied zwischen den physischen Kameras.

### Alternierende Wiederholungsreihe: Wartezeit nach USB-Reset

Weil zwei Dienststarts kurz nach dem obligatorischen `USBDEVFS_RESET`
auffällige Bursts gezeigt hatten, wurde die Wartezeit nach dem Reset getrennt
geprüft. Vor jedem Block wurde dasselbe Gerät mit `usbreset 04b4:0822`
zurückgesetzt; anschließend wartete der Test abwechselnd 1 oder 10 Sekunden
und las mit `v4l2-ctl` 1.800 Frames bei denselben 4K-MJPEG-/30-fps- und
12-Puffer-Parametern. Pro Kamera liefen fünf Blöcke je Wartezeit, auf Kamera 2
in umgekehrter Reihenfolge.

| Wartezeit | Läufe | UVC-Frames | Error-Payloads | ungültige Header |
| --- | ---: | ---: | ---: | ---: |
| 1 Sekunde | 10 | 35.980 | 0 | 0 |
| 10 Sekunden | 10 | 35.980 | 0 | 0 |

Damit ist weder die einsekündige Wartezeit noch ein unmittelbar vorheriger
USB-Reset als hinreichende Ursache der sporadischen Bursts belegt. Die zuvor
zeitlich auffälligen Dienststarts dürfen nach dieser Gegenprobe nicht dem
Reset zugerechnet werden.

In einer weiteren Reihe wurde die bislang fehlende Kombination aus Reset und
isolierter Python-Captureklasse fünfmal pro Kamera geprüft. Jeder Block lief
90 Sekunden und verwendete wieder 4K-MJPEG bei 30 fps und zwölf Puffer:

| Kamera | Läufe | UVC-Frames | Läufe mit UVC-Fehlern | Error-Payloads | ungültige Header |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 5 | 13.490 | 0 | 0 | 0 |
| 2 | 5 | 13.514 | 1 | 30 | 1 |

Im betroffenen Kamera-2-Block zählte die Anwendung fünf Sequenzsprünge, 24
fehlende Sequenzen und vier ungültige MJPEG-Puffer. Die übrigen neun Blöcke
waren unauffällig. Damit kann auch die Kombination `USBDEVFS_RESET` plus
Python-Initialisierung betroffen sein; sie ist nach dieser Verteilung aber
nicht als hinreichende Ursache belegt.

### Vollständiges Dienstprogramm außerhalb von systemd

Beide systemd-Units wurden auf Laufzeitbegrenzungen geprüft. Die Prozesse
liefen mit normalem Scheduler, Nice 0, allen vier CPUs, ohne CPU- oder
Speicherlimit und ohne Realtime-Priorität. Anschließend wurde das vollständige
`camera_service.py` bei gestoppter Unit fünfmal pro Kamera manuell mit exakt
derselben virtuellen Umgebung gestartet. Jeder Block lief 90 Sekunden:

| Kamera | Läufe | UVC-Frames | Läufe mit UVC-Fehlern | Error-Payloads | ungültige Header |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 5 | 13.267 | 0 | 0 | 0 |
| 2 | 5 | 13.318 | 1 | 27 | 1 |

Der betroffene Kamera-2-Block erzeugte 33 Anwendungsdiagnosen. Weil der Fehler
damit außerhalb der systemd-Unit auftrat, ist systemd keine notwendige
Bedingung. Die Serie belegt wegen nur eines betroffenen Blocks keinen
Häufigkeitsunterschied zum isolierten Captureprozess.

### API-/Preview-Subscriber an und aus

Der API-Prozess startet beim Import dauerhaft einen ZMQ-Subscriber. Die zur
Kameraausrichtung benötigte Preview sendet unabhängig vom separat schaltbaren
Livestream bis zu drei vollständige 4K-JPEGs pro Sekunde. Um den Subscriber
von der UVC-Ursache zu trennen, liefen pro Kamera fünf neue Streams mit je einer
60-Sekunden-Phase bei gestopptem und gestartetem API-Prozess; die Reihenfolge
war zwischen den Kameras vertauscht.

Über beide Kameras waren jeweils sieben Phasen pro Zustand unauffällig. Zwei
API-an-Phasen enthielten zusammen 69 Error-Payloads und zehn ungültige Header;
eine API-aus-Phase enthielt neun Error-Payloads und vier ungültige Header.
Damit ist der Subscriber keine notwendige Bedingung der Bursts. Drei
Burstphasen reichen nicht aus, um einen Häufigkeitsunterschied zwischen den
Zuständen zu belegen. Preview und Livestream bleiben funktional getrennt; das
Livestream-Flag darf die Preview nicht deaktivieren.

## Kernelinterne UVC-Paketstatistik

Der laufende `uvcvideo`-Treiber stellt unter
`/sys/kernel/debug/usb/uvcvideo/*/stats` eigene Statistiken bereit. Eine
zeitgleiche Stichprobe ergab:

| Kernelzähler | Kamera 1 | Kamera 2 |
| --- | ---: | ---: |
| UVC-Frames | 4.757 | 70.364 |
| UVC-Pakete | 415.140 | 6.095.135 |
| Payloads mit UVC-Error-Bit | 230 | 823 |
| ungültige UVC-Payload-Header | 13 | 66 |

Im Raspberry-Pi-Kernel `rpi-6.12.y` entstehen diese Werte in
`drivers/media/usb/uvc/uvc_video.c`:

- `errors` wird erhöht, wenn das von der Kamera gelieferte UVC-Payload-Header-
  Byte das Bit `UVC_STREAM_ERR` enthält.
- `invalid` wird erhöht, wenn der Payload-Header zu kurz ist, eine ungültige
  Headerlänge enthält oder die Headerlänge größer als das USB-Payload ist.
- Ein Puffer mit gesetztem Error-Bit wird intern als fehlerhaft markiert. Bei
  dem auf beiden Pis aktiven Modulparameter `nodrop=0` verwirft der Treiber
  solche beschädigten Frames.

Damit ist belegt, dass Fehler bereits bei der Verarbeitung der von der Kamera
kommenden UVC-Payloads im Kernel vorliegen. Der Recorder, der Preview-Callback,
ZMQ, HTTP und Android können diese Fehler nicht erzeugen. Die V4L2-
Sequenzsprünge sind mindestens teilweise die erwartbare Folge davon, dass der
Kernel als beschädigt markierte Frames verwirft.

Noch nicht belegt ist die darunterliegende Ursache der fehlerhaften Payloads:
Die Daten können bereits vom Kamera-/USB-Bridge-Firmwarepfad fehlerhaft
markiert oder aufgebaut werden, oder während der USB-Übertragung beschädigt
werden. Einzelne Kernelmeldungen mit USB-Fehler `-71` belegen, dass zumindest
zeitweise auch USB-Protokollfehler auftreten; sie erscheinen aber nicht zu
jedem registrierten Payloadfehler.

### Treiber-Quirk `MJPEG_NO_EOF`: wiederholter Kreuztest

Der vorherige einzelne Lauf und einzelne Tausch mit
`UVC_QUIRK_MJPEG_NO_EOF` (`0x20000`) wird nicht bewertet. Am 11. Oktober wurde
deshalb eine neue, vorab festgelegte Reihe durchgeführt:

- sechs alternierende Blöcke;
- pro Block 30 Sekunden Aufwärmzeit, danach exakt fünf Minuten Messzeit;
- Blöcke 1, 3 und 5: Kamera 1 mit Quirk, Kamera 2 mit Standardtreiber;
- Blöcke 2, 4 und 6: Kamera 1 mit Standardtreiber, Kamera 2 mit Quirk;
- ausgewertet wurden ausschließlich die Differenzen zwischen Start und Ende
  jedes Messfensters;
- parallel wurden die Anwendungszähler und die Kernel-UVC-Statistik erfasst.

| Block | Kamera | Zustand | Frames | Sequenzlücken | fehlende Frames | ungültige MJPEGs | UVC-Error-Payloads | ungültige UVC-Header |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1 | Quirk | 9.083 | 22 | 93 | 31 | 138 | 14 |
| 1 | 2 | Standard | 9.085 | 34 | 162 | 39 | 174 | 6 |
| 2 | 1 | Standard | 9.079 | 38 | 133 | 40 | 161 | 10 |
| 2 | 2 | Quirk | 9.058 | 5 | 27 | 5 | 9 | 0 |
| 3 | 1 | Quirk | 9.083 | 32 | 93 | 35 | 96 | 7 |
| 3 | 2 | Standard | 9.061 | 7 | 30 | 8 | 52 | 6 |
| 4 | 1 | Standard | 9.068 | 23 | 82 | 23 | 140 | 9 |
| 4 | 2 | Quirk | 9.061 | 8 | 36 | 7 | 27 | 5 |
| 5 | 1 | Quirk | 9.068 | 11 | 58 | 15 | 42 | 6 |
| 5 | 2 | Standard | 9.067 | 24 | 87 | 23 | 69 | 8 |
| 6 | 1 | Standard | 9.067 | 20 | 76 | 21 | 131 | 6 |
| 6 | 2 | Quirk | 9.065 | 10 | 34 | 12 | 19 | 2 |

Die Summen aus jeweils drei Messfenstern:

| Kamera | Zustand | Frames | Sequenzlücken | fehlende Frames | ungültige MJPEGs | UVC-Error-Payloads | ungültige UVC-Header |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Standard | 27.214 | 81 | 291 | 84 | 432 | 25 |
| 1 | Quirk | 27.234 | 65 | 244 | 81 | 276 | 27 |
| 2 | Standard | 27.213 | 65 | 279 | 70 | 295 | 20 |
| 2 | Quirk | 27.184 | 23 | 97 | 24 | 55 | 7 |

Der Quirk beseitigte die Fehler in keinem der sechs Quirk-Messfenster. Bei
Kamera 2 waren die aggregierten Werte mit Quirk deutlich niedriger. Bei Kamera
1 waren die ungültigen MJPEGs dagegen nahezu gleich (81 gegenüber 84), und die
Abstände zwischen einzelnen Messfenstern schwankten stark. Einzelne benachbarte
Vergleiche kehrten die Richtung außerdem um, etwa Kamera 1 bei den
Sequenzlücken in Block 3 gegenüber Block 4 sowie Kamera 2 in Block 3 gegenüber
Block 4.

Damit besteht in dieser Reihe eine kamerabhängig unterschiedlich starke
Assoziation zwischen Quirk und Zählerständen. Sie belegt weder, dass fehlende
EOF-Markierungen die Ursache sind, noch dass der Quirk eine belastbare Lösung
ist. Insbesondere sind die UVC-Error-Payloads selbst bereits vor der
MJPEG-Frameabgrenzung fehlerhaft; deren stark schwankende Anzahl kann durch den
Quirk nicht als zugrunde liegende Ursache erklärt werden.

Während der sechs eigentlichen Messfenster gab es keine neue spontane
Kernelmeldung `Non-zero status (-71)`. Die im Kernel gezählten
UVC-Error-Payloads und ungültigen Header traten trotzdem auf. Damit ist
zusätzlich belegt, dass eine fehlende `-71`-Logmeldung keinen fehlerfreien
UVC-Payloadstrom bedeutet. Die USB-Resets im Protokoll wurden durch die für den
Zustandswechsel notwendigen Modul- und Service-Neustarts ausgelöst.

Der einmalige Lauf mit `UVC_QUIRK_STREAM_NO_FID` (`0x10`) erfüllt die
Bewertungsmethode weiterhin nicht und wird nicht als Beleg verwendet.

Nach der Messreihe wurden beide Pis auf den automatischen Standardwert
`quirks=4294967295` zurückgesetzt. `camera_service` und `kaderblick_app` waren
danach auf beiden Systemen aktiv; die API meldete fortlaufende Bildlieferung
und keine aktive Aufnahme.

## Wiederholte USB-Transfermessung mit `usbmon`

Um UVC-Payloadfehler von durch den USB-Core gemeldeten Transferfehlern zu
trennen, wurden am 11. Oktober auf beiden Pis gleichzeitig drei Messfenster von
jeweils drei Minuten aufgezeichnet. Beide Systeme liefen dabei mit dem
automatischen Standardwert `quirks=4294967295`. Erfasst wurden ausschließlich
Bulk-Transfers des Kamera-Endpunkts `Bi:4:002:1`; parallel wurden Start- und
Endwerte der App- und Kernel-UVC-Zähler gelesen.

| Fenster | Kamera | erfolgreiche Bulk-Abschlüsse | andere URB-Status | neue Sequenzlücken | neu fehlende Frames | neue ungültige MJPEGs | neue UVC-Error-Payloads | neue ungültige UVC-Header |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1 | 524.416 | 0 | 9 | 33 | 9 | 35 | 3 |
| 1 | 2 | 473.634 | 0 | 5 | 21 | 5 | 17 | 3 |
| 2 | 1 | 535.909 | 0 | 13 | 77 | 17 | 88 | 10 |
| 2 | 2 | 474.741 | 0 | 10 | 50 | 16 | 46 | 2 |
| 3 | 1 | 534.634 | 0 | 18 | 62 | 17 | 47 | 3 |
| 3 | 2 | 473.249 | 0 | 11 | 32 | 14 | 27 | 4 |

In Summe wurden 3.016.583 Bulk-Abschlüsse erfasst. Jeder Abschluss hatte den
USB-URB-Status `0`. Trotzdem stiegen in jedem der sechs Kamera-Messfenster die
Sequenzverlust-, MJPEG- und Kernel-UVC-Fehlerzähler. Im selben Zeitraum gab es
auf beiden Pis keine Kernelmeldung `Non-zero status (-71)`.

Damit ist wiederholt belegt:

- Die in diesen Fenstern erfassten Framefehler waren nicht von einem durch den
  USB-Core gemeldeten fehlgeschlagenen Bulk-Transfer begleitet.
- UVC-Payloads mit Error-Bit beziehungsweise ungültigem Header erreichen den
  UVC-Treiber innerhalb von Transfers, die der USB-Core erfolgreich
  abschließt.
- Das Auslesen in Python, Preview, Netzwerk und Recorder liegen hinter diesem
  Punkt und können diese bereits vorhandenen Payloadfehler nicht erzeugen.
- Das frühere Auftreten von `-71` ist ein reales, aber zusätzliches Fehlerbild;
  es erklärt die hier wiederholt gemessenen Bursts nicht.

Nicht belegt ist weiterhin, welcher interne Zustand der Kamera beziehungsweise
USB-Bridge das UVC-Error-Bit und die ungültigen Header auslöst. Dafür kommen
unter anderem Encoder-/Firmwarezustand und geräteinterne Pufferung als noch
unbestätigte Hypothesen in Betracht. Sie dürfen ohne einen weiteren
kontrollierten Test nicht als Ursache bezeichnet werden.

## UVC-Aushandlung und Framegrenzen im USB-Datenstrom

Am 11. Oktober wurden beim normalen Neuöffnen beider Streams die UVC-Probe-
und Commit-Control-Transfers mit `usbmon` erfasst. Die von beiden Geräten
bestätigten Commit-Daten waren bytegleich:

- Formatindex 2, Frameindex 1;
- Frameintervall 333.333 × 100 ns, also 30 fps;
- `dwMaxVideoFrameSize = 8.294.400` Byte;
- `dwMaxPayloadTransferSize = 16.384` Byte.

Eine direkte, jeweils 0,2 Sekunden aktive `uvcvideo`-Frame-Trace meldete auf
beiden Systemen ausschließlich reguläre Abschlüsse durch `EOF found` (Kamera 1:
7, Kamera 2: 6). Damit ist belegt, dass der Treiber in diesen Zeitfenstern
EOF-Markierungen verarbeitet hat.

Eine zwischenzeitliche Auswertung der ersten Bytes jeder binär über `usbmon`
kopierten URB schien dem zu widersprechen und zeigte auf Kamera 1 zahlreiche
FID-Wechsel. Diese Interpretation ist verworfen: Sie reproduzierte nicht die
gleichzeitig direkt im Treiber gemessenen Frameentscheidungen und darf nicht
als Befund über FID oder EOF verwendet werden. Ebenso ist eine versuchsweise
Gruppierung bis zur nächsten kurzen URB für den ausgehandelten Payloadwert von
16.384 Byte nicht gültig. Maßgeblich bleiben die direkt im Treiber erfassten
UVC-Zähler und Frameentscheidungen.

## Trennung der beobachteten Fehlerklassen

Die gleichzeitigen Messfenster zeigen mindestens zwei getrennt zu behandelnde
Klassen:

1. `uvcvideo` zählt vom Gerät gelieferte Payload-Header mit gesetztem
   `UVC_STREAM_ERR` beziehungsweise formal ungültige Header. Diese Zähler
   stiegen wiederholt trotz ausschließlich erfolgreicher USB-Bulk-Abschlüsse.
2. Anwendungsseitige ungültige MJPEG-Puffer und Sequenzsprünge stimmen nicht in
   jedem Zeitfenster eins zu eins mit diesen beiden Kernelzählern überein. Sie
   dürfen daher nicht pauschal als dasselbe Ereignis gezählt oder erklärt
   werden.

Der Linux-USB-Core prüft SuperSpeed-Übertragungen einschließlich der
Link-/Protokollsicherung, meldete in den wiederholten Messfenstern aber keinen
fehlgeschlagenen URB. Belegt ist daher, dass die von `uvcvideo` gezählten
Error-Bits in erfolgreich abgeschlossenen USB-Daten ankamen. Nicht belegt ist,
welcher interne Kamera-/Bridge-Zustand diese Kennzeichnung auslöst oder ob eine
hostseitige Initialisierungsfolge ihn begünstigt.

## Hersteller-Extension-Unit und interner Logpuffer

Beide Kameras melden dieselbe UVC-Extension-Unit mit der GUID
`acb6890c-a3b3-4060-8b9a-df34eef39a2e` und elf herstellerspezifischen
Controls. Sämtliche Prüfungen erfolgten nur lesend über `UVCIOC_CTRL_QUERY`;
es wurden keine unbekannten Herstellerwerte geschrieben.

Control 6 enthält einen 1.024-Byte-Textpuffer mit wiederholten Meldungen wie
`SensorWrite1632 ret: 0`, `SensorWrite1632 ret: 68` und `No Error: 18`.
Während der zeitgleichen Messung stiegen die UVC-Error-Payloads auf Kamera 1
in einem Burst um 30 und auf Kamera 2 in getrennten Bursts um 27 sowie später
25 und 32. Header, Hash und Textzähler des jeweiligen Herstellerpuffers
blieben bei jedem Messpunkt bytegenau unverändert. Die Texte sind daher alter
Pufferinhalt und kein Live-Indikator der beobachteten UVC-Bursts. Ihre
herstellerspezifische Bedeutung ist nicht dokumentiert und darf nicht als
Fehlercode interpretiert werden.

Der 6.144-Byte-Inhalt von Control 4 war bei beiden Kameras identisch und über
wiederholte Lesevorgänge unverändert. Die übrigen lesbaren Controls waren
ebenfalls auf beiden Geräten identisch; Control 11 beantwortete `GET_CUR`
nicht innerhalb des Gerätetimeouts. Es gibt in diesen Controls damit keinen
beobachteten veränderlichen Status, der die Fehlerbursts erklärt.

## Unterschiedliche Systembasis

Die beiden Pis sind nicht vollständig gleich installiert:

- Kamera 1 läuft auf Debian 13 (Trixie).
- Kamera 2 läuft auf Debian 12 (Bookworm).
- Beide melden zwar `6.12.75+rpt-rpi-2712`, Kernel-Image, Kernelkonfiguration
  und `uvcvideo`-Modul sind jedoch binär verschieden. Auf Kamera 2 kennt die
  Paketverwaltung nur ein älteres Kernelpaket; der laufende Kernel wurde damit
  nicht vollständig aus dem dort registrierten Paketbestand installiert.

Das ist eine reale, zu bereinigende Systemabweichung, aber kein belegter
Ursachenbeweis: Die UVC-Error-Payloads treten auf beiden unterschiedlichen
Kernelbuilds auf. Eine Angleichung ist für einen sauberen Kreuztest notwendig,
darf jedoch nicht vorab als Fehlerbehebung bewertet werden.

## Validierung zusammengeklebter MJPEG-Bilder

Die bisherige `_normalize_mjpeg_frame()`-Validierung prüfte nur SOI am Anfang
und das letzte EOI im Puffer. Ein Puffer mit zwei vollständigen, aneinander
gehängten JPEGs konnte dadurch als ein gültiges Bild gelten. Die Validierung
weist nun einen weiteren SOI-Marker nach dem ersten als ungültiges MJPEG zurück,
sodass ein solcher V4L2-Puffer den vorhandenen Qualitätszähler erhöht und nicht
in Preview oder Aufnahme gelangt. Diese Änderung verbessert Erkennung und
Schadensbegrenzung; sie behebt keine bereits vor V4L2 entstandenen
UVC-Payloadfehler.

### Laufzeitkontrolle der erweiterten Validierung

Nach der Änderung wurden beide Capture-Dienste ohne laufende Aufnahme neu
gestartet und zwei Minuten lang in vier 30-Sekunden-Stichproben geprüft:

| Kamera | empfangene V4L2-Puffer | Sequenzlücken | fehlende Frames | ungültige MJPEGs | UVC-Error-Payloads | ungültige UVC-Header |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3.794 | 0 | 0 | 0 | 0 | 0 |
| 2 | 3.804 | 8 | 38 | 12 | 35 | 2 |

Die zwölf ungültigen Puffer auf Kamera 2 waren keine durch die neuen
Mehrfach-SOI-Prüfung entdeckten normalen Bilder: Elf begannen nicht mit SOI,
zehn davon enthielten auch kein EOI; ein 425.542-Byte-Puffer begann mit SOI,
endete aber ohne EOI. Die übrigen fehlerhaften Puffer waren überwiegend nur
etwa 16 KiB groß. Im selben Zeitraum meldete das Kerneljournal weder `-71`
noch einen xHCI-Fehler. Kamera 1 zeigte mit derselben Codeversion keinen
Fehler. Damit hat die strengere Validierung in diesem Kontrollfenster keine
regulären Kamera-1-Frames fälschlich verworfen, während der bereits unterhalb
der Anwendung beginnende Burst auf Kamera 2 unmittelbar reproduziert wurde.

