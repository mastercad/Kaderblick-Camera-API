# Servo absolut auf 120°
curl -X POST "http://<pi-ip>:8000/servo" -H "Content-Type: application/json" -d '{"angle":120}'

# Aktuelle Servo Position abfragen:
curl "http://<pi-ip>:8000/servo"

# Stepper relativ +100 Schritte:
curl -X POST "http://<pi-ip>:8000/stepper" -H "Content-Type: application/json" -d '{"steps":100, "delay":0.002}'

# Stepper absolut auf Position 500:
curl -X POST "http://<pi-ip>:8000/stepper/absolute" -H "Content-Type: application/json" -d '{"position":500, "delay":0.002}'

# Status (beide Werte):
curl "http://<pi-ip>:8000/status"

# Relativ: 10 Grad nach rechts
curl -X POST http://localhost:8000/servo -H "Content-Type: application/json" -d '{"degrees": 10}'

# Relativ: 15 Grad nach links
curl -X POST http://localhost:8000/servo -H "Content-Type: application/json" -d '{"degrees": -15}'

# Absolut: Fahre zu 90°
curl -X POST http://localhost:8000/servo/absolute -H "Content-Type: application/json" -d '{"angle": 90}'

# start service
python camera_service.py

# start api
uvicorn fastapi_app:app --host 0.0.0.0 --port 8000

# umwandlung
ffmpeg -f mjpeg -i aufnahme_* -c:v copy output.avi

## auf 30FPS
ffmpeg -framerate 30 -f mjpeg -i aufnahme_2025-11-26_19-48-28.mjpg -c:v copy output.avi

# /media/Austausch/Projekte/fussballverein/output/48/

##############################################################################################
# AUDIO
##############################################################################################
# audio von mono zu stereo
ffmpeg -i input_mono.wav -ac 2 output_stereo.wav

# audio normalisieren
## per ffmpeg
ffmpeg -i aufnahme.wav -filter:a "loudnorm" aufnahme_laut.wav

# audio 3x lauter machen (5.0 für 5x)
ffmpeg -i input.wav -filter:a "volume=3.0" output_laut.wav

# audio 10db lauter
ffmpeg -i input.wav -filter:a "volume=10dB" output_laut.wav

# rauschen entfernen
ffmpeg -i input.wav -af "afftdn" output_clean.wav

## per sox
sox aufnahme.wav aufnahme_laut.wav gain -n

## per sox (nur pegel anzeigen)
sox aufnahme.wav -n stat

# audio und video kombinieren
ffmpeg -i aufnahme.avi -i aufnahme.wav -c:v copy -c:a aac -strict experimental -shortest video_mit_audio.mp4

## in avi umwandeln
ffmpeg -f mjpeg -i aufnahme.mjpg -c:v copy aufnahme.avi

## aus audio und video eine datei machen

## maximale kompatibilität mit PCM audio 
ffmpeg -i aufnahme.avi -i aufnahme.wav -c:v copy -c:a pcm_s16le -shortest video_mit_audio.avi

## modern komprimiert mit MP4 und AAC für web/youtube
ffmpeg -i aufnahme.avi -i aufnahme.wav -c:v copy -c:a aac -b:a 192k -shortest video_mit_audio.mp4


# konvertierungsreihenfolge für c&p
ffmpeg -framerate 30 -f mjpeg -i aufnahme_2025-11-26_19-48-28.mjpg -c:v copy output.avi
#ffmpeg -i aufnahme.wav -filter:a "loudnorm" aufnahme_laut.wav
ffmpeg -i aufnahme.wav -af "volume=3.0,loudnorm" aufnahme_rauschen_reduziert_3x_lauter_normalisiert.wav
ffmpeg -i aufnahme.avi -i aufnahme.wav -c:v copy -c:a pcm_s16le -shortest video_mit_audio.avi
ffmpeg -i aufnahme.avi -i aufnahme.wav -c:v copy -c:a aac -b:a 192k -shortest video_mit_audio.mp4

# bestehendes DJI 4K Video auf Youtube format konvertieren
## h264 (0,3 Geschwindigkeit, 3.4GB statt 16GB)
ffmpeg -i input.mp4 -c:v libx264 -preset slow -crf 23 -pix_fmt yuv420p -c:a aac -b:a 192k output_4k60_youtube.mp4

## preset veryfast für höhere geschwindigkeit aber geringere komprimierung
ffmpeg -i input.mp4 -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p -c:a aac -b:a 192k output.mp4

## encoding über nvidia GPU:
ffmpeg -i input.mp4 -c:v h264_nvenc -preset fast -rc:v vbr -cq:v 23 -c:a aac -b:a 192k output.mp4

## angeblich optimalstes conmmand (macht aber keinen sinn, 0.7 geschwindigkeit und dategröße fast unverändert (13GB statt 16GB ...)):
ffmpeg -i input.mp4 -c:v h264_nvenc -preset p4 -rc:v vbr -cq:v 19 -b:v 0 -pix_fmt yuv420p -c:a aac -b:a 192k output_4k60_nvenc.mp4

## h265
ffmpeg -i input.mp4 -c:v libx265 -preset slow -crf 28 -pix_fmt yuv420p -c:a aac -b:a 192k output_4k60_youtube_h265.mp4

ffmpeg -i aufnahme_2025-11-29_19-33-56.avi -i /media/Austausch/Projekte/fussballverein/output/testaufnahme/aufnahme_2025-11-29_19-33-56.wav -c:v copy -c:a pcm_s16le -shortest /media/Austausch/Projekte/fussballverein/output/testaufnahme/aufnahme_2025-11-29_19-33-56.avi

# von mjpeg avi auf youtube format konvertieren
ffmpeg -i aufnahme_2025-11-29_19-33-56.avi -i /media/Austausch/Projekte/fussballverein/output/testaufnahme/aufnahme_2025-11-29_19-33-56.wav -c:v libx264 -preset slow -crf 23 -pix_fmt yuv420p -c:a aac -b:a 192k /media/Austausch/Projekte/fussballverein/output/testaufnahme/aufnahme_2025-11-29_19-33-56.avi

# lösung für kaputte mjpeg mit framedrops:
## mjpeg neu timen
ffmpeg -fflags +genpts -i aufnahme.mjpg -r 25 -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p aufnahme_fixed.mp4

## audio und video kombinieren
ffmpeg -i aufnahme_fixed.mp4 -i aufnahme.wav -c:v copy -c:a aac -b:a 192k -shortest output.mp4

# console commands
v4l2-ctl --device=/dev/video0 --set-fmt-video=width=3840,height=2160,pixelformat=MJPG

# HDR aktivieren
v4l2-ctl -d /dev/video0 --set-fmt-video=width=3840,height=2160,pixelformat=NV12

v4l2-ctl --device=/dev/video0 --list-formats-ext
ioctl: VIDIOC_ENUM_FMT
        Type: Video Capture

        [0]: 'YUYV' (YUYV 4:2:2)
                Size: Discrete 3840x2160
                        Interval: Discrete 0.067s (15.000 fps)
                Size: Discrete 1920x1080
                        Interval: Discrete 0.017s (60.000 fps)
                Size: Discrete 1280x720
                        Interval: Discrete 0.017s (60.000 fps)
                Size: Discrete 640x480
                        Interval: Discrete 0.017s (60.000 fps)
                Size: Discrete 320x320
                        Interval: Discrete 0.017s (60.000 fps)
                Size: Discrete 128x128
                        Interval: Discrete 0.017s (60.000 fps)
                Size: Discrete 96x96
                        Interval: Discrete 0.017s (60.000 fps)
        [1]: 'MJPG' (Motion-JPEG, compressed)
                Size: Discrete 3840x2160
                        Interval: Discrete 0.033s (30.000 fps)
                Size: Discrete 1920x1080
                        Interval: Discrete 0.017s (60.000 fps)
                Size: Discrete 1280x720
                        Interval: Discrete 0.017s (60.000 fps)
                Size: Discrete 640x480
                        Interval: Discrete 0.017s (60.000 fps)


v4l2-ctl --list-ctrls

```
User Controls

                       contrast 0x00980901 (int)    : min=0 max=4 step=1 default=2 value=2
                     saturation 0x00980902 (int)    : min=0 max=4 step=1 default=2 value=2
                           gain 0x00980913 (int)    : min=1 max=16 step=1 default=1 value=1
                      sharpness 0x0098091b (int)    : min=0 max=6 step=1 default=3 value=3

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=0 value=0 (Auto Mode)
         exposure_time_absolute 0x009a0902 (int)    : min=10 max=660 step=1 default=10 value=10 flags=inactive
```


v4l2-ctl --device /dev/video0 --all
Driver Info:
        Driver name      : uvcvideo
        Card type        : Arducam B0589 4K HDR
        Bus info         : usb-xhci-hcd.1-1
        Driver version   : 6.12.47
        Capabilities     : 0x84a00001
                Video Capture
                Metadata Capture
                Streaming
                Extended Pix Format
                Device Capabilities
        Device Caps      : 0x04200001
                Video Capture
                Streaming
                Extended Pix Format
Media Driver Info:
        Driver name      : uvcvideo
        Model            : Arducam B0589 4K HDR
        Serial           : Arducam_20250812_0001
        Bus info         : usb-xhci-hcd.1-1
        Media version    : 6.12.47
        Hardware revision: 0x00000000 (0)
        Driver version   : 6.12.47
Interface Info:
        ID               : 0x03000002
        Type             : V4L Video
Entity Info:
        ID               : 0x00000001 (1)
        Name             : Arducam B0589 4K HDR
        Function         : V4L2 I/O
        Flags            : default
        Pad 0x01000007   : 0: Sink
          Link 0x02000010: from remote pad 0x100000a of entity 'Extension 3' (Video Pixel Formatter): Data, Enabled, Immutable
Priority: 2
Video input : 0 (Camera 1: ok)
Format Video Capture:
        Width/Height      : 3840/2160
        Pixel Format      : 'MJPG' (Motion-JPEG)
        Field             : None
        Bytes per Line    : 0
        Size Image        : 8294400
        Colorspace        : sRGB
        Transfer Function : Default (maps to sRGB)
        YCbCr/HSV Encoding: Default (maps to ITU-R 601)
        Quantization      : Default (maps to Full Range)
        Flags             : 
Crop Capability Video Capture:
        Bounds      : Left 0, Top 0, Width 3840, Height 2160
        Default     : Left 0, Top 0, Width 3840, Height 2160
        Pixel Aspect: 1/1
Selection Video Capture: crop_default, Left 0, Top 0, Width 3840, Height 2160, Flags: 
Selection Video Capture: crop_bounds, Left 0, Top 0, Width 3840, Height 2160, Flags: 
Streaming Parameters Video Capture:
        Capabilities     : timeperframe
        Frames per second: 30.000 (30/1)
        Read buffers     : 0

User Controls

                       contrast 0x00980901 (int)    : min=0 max=4 step=1 default=2 value=2
                     saturation 0x00980902 (int)    : min=0 max=4 step=1 default=2 value=2
                           gain 0x00980913 (int)    : min=1 max=16 step=1 default=1 value=1
                      sharpness 0x0098091b (int)    : min=0 max=6 step=1 default=3 value=3

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=0 value=0 (Auto Mode)
                                0: Auto Mode
                                1: Manual Mode
         exposure_time_absolute 0x009a0902 (int)    : min=10 max=660 step=1 default=10 value=10 flags=inactive
kaderblick@kamera1:~ $ v4l2-ctl --device /dev/video1 --all
Driver Info:
        Driver name      : uvcvideo
        Card type        : Arducam B0589 4K HDR
        Bus info         : usb-xhci-hcd.1-1
        Driver version   : 6.12.47
        Capabilities     : 0x84a00001
                Video Capture
                Metadata Capture
                Streaming
                Extended Pix Format
                Device Capabilities
        Device Caps      : 0x04a00000
                Metadata Capture
                Streaming
                Extended Pix Format
Media Driver Info:
        Driver name      : uvcvideo
        Model            : Arducam B0589 4K HDR
        Serial           : Arducam_20250812_0001
        Bus info         : usb-xhci-hcd.1-1
        Media version    : 6.12.47
        Hardware revision: 0x00000000 (0)
        Driver version   : 6.12.47
Interface Info:
        ID               : 0x03000005
        Type             : V4L Video
Entity Info:
        ID               : 0x00000004 (4)
        Name             : Arducam B0589 4K HDR
        Function         : V4L2 I/O
Priority: 2
Format Metadata Capture:
        Sample Format   : 'UVCH' (UVC Payload Header Metadata)
        Buffer Size     : 10240


v4l2-ctl --list-devices
pispbe (platform:1000880000.pisp_be):
        /dev/video20
        /dev/video21
        /dev/video22
        /dev/video23
        /dev/video24
        /dev/video25
        /dev/video26
        /dev/video27
        /dev/video28
        /dev/video29
        /dev/video30
        /dev/video31
        /dev/video32
        /dev/video33
        /dev/video34
        /dev/video35
        /dev/media1
        /dev/media3

rpi-hevc-dec (platform:rpi-hevc-dec):
        /dev/video19
        /dev/media0

Arducam B0589 4K HDR (usb-xhci-hcd.1-1):
        /dev/video0
        /dev/video1
        /dev/media2

v4l2-ctl --device /dev/video0 --all
Driver Info:
        Driver name      : uvcvideo
        Card type        : Arducam B0589 4K HDR
        Bus info         : usb-xhci-hcd.1-1
        Driver version   : 6.12.47
        Capabilities     : 0x84a00001
                Video Capture
                Metadata Capture
                Streaming
                Extended Pix Format
                Device Capabilities
        Device Caps      : 0x04200001
                Video Capture
                Streaming
                Extended Pix Format
Media Driver Info:
        Driver name      : uvcvideo
        Model            : Arducam B0589 4K HDR
        Serial           : Arducam_20250812_0001
        Bus info         : usb-xhci-hcd.1-1
        Media version    : 6.12.47
        Hardware revision: 0x00000000 (0)
        Driver version   : 6.12.47
Interface Info:
        ID               : 0x03000002
        Type             : V4L Video
Entity Info:
        ID               : 0x00000001 (1)
        Name             : Arducam B0589 4K HDR
        Function         : V4L2 I/O
        Flags            : default
        Pad 0x01000007   : 0: Sink
          Link 0x02000010: from remote pad 0x100000a of entity 'Extension 3' (Video Pixel Formatter): Data, Enabled, Immutable
Priority: 2
Video input : 0 (Camera 1: ok)
Format Video Capture:
        Width/Height      : 3840/2160
        Pixel Format      : 'MJPG' (Motion-JPEG)
        Field             : None
        Bytes per Line    : 0
        Size Image        : 8294400
        Colorspace        : sRGB
        Transfer Function : Default (maps to sRGB)
        YCbCr/HSV Encoding: Default (maps to ITU-R 601)
        Quantization      : Default (maps to Full Range)
        Flags             : 
Crop Capability Video Capture:
        Bounds      : Left 0, Top 0, Width 3840, Height 2160
        Default     : Left 0, Top 0, Width 3840, Height 2160
        Pixel Aspect: 1/1
Selection Video Capture: crop_default, Left 0, Top 0, Width 3840, Height 2160, Flags: 
Selection Video Capture: crop_bounds, Left 0, Top 0, Width 3840, Height 2160, Flags: 
Streaming Parameters Video Capture:
        Capabilities     : timeperframe
        Frames per second: 30.000 (30/1)
        Read buffers     : 0

User Controls

                       contrast 0x00980901 (int)    : min=0 max=4 step=1 default=2 value=2
                     saturation 0x00980902 (int)    : min=0 max=4 step=1 default=2 value=2
                           gain 0x00980913 (int)    : min=1 max=16 step=1 default=1 value=1
                      sharpness 0x0098091b (int)    : min=0 max=6 step=1 default=3 value=3

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=0 value=0 (Auto Mode)
                                0: Auto Mode
                                1: Manual Mode
         exposure_time_absolute 0x009a0902 (int)    : min=10 max=660 step=1 default=10 value=10 flags=inactive


v4l2-ctl --device /dev/video1 --all
Driver Info:
        Driver name      : uvcvideo
        Card type        : Arducam B0589 4K HDR
        Bus info         : usb-xhci-hcd.1-1
        Driver version   : 6.12.47
        Capabilities     : 0x84a00001
                Video Capture
                Metadata Capture
                Streaming
                Extended Pix Format
                Device Capabilities
        Device Caps      : 0x04a00000
                Metadata Capture
                Streaming
                Extended Pix Format
Media Driver Info:
        Driver name      : uvcvideo
        Model            : Arducam B0589 4K HDR
        Serial           : Arducam_20250812_0001
        Bus info         : usb-xhci-hcd.1-1
        Media version    : 6.12.47
        Hardware revision: 0x00000000 (0)
        Driver version   : 6.12.47
Interface Info:
        ID               : 0x03000005
        Type             : V4L Video
Entity Info:
        ID               : 0x00000004 (4)
        Name             : Arducam B0589 4K HDR
        Function         : V4L2 I/O
Priority: 2
Format Metadata Capture:
        Sample Format   : 'UVCH' (UVC Payload Header Metadata)
        Buffer Size     : 10240
