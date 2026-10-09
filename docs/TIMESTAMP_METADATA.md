# Monotone Zeitstempel in MJPEG und WAV

Video- und Audiozeitstempel verwenden `CLOCK_MONOTONIC` in Nanosekunden. Die
Zeitwerte sind deshalb direkt vergleichbar und unabhängig von Änderungen der
Systemzeit.

## MJPEG: APP15 `KBFM`

Jeder gespeicherte JPEG-Frame enthält unmittelbar nach dem SOI einen
APP15-Marker. Der 40 Byte große Payload ist Big Endian kodiert:

```text
>4sBBHQIQQI
magic[4]                 = "KBFM"
version                  = 1
metadata_flags           = 0
header_size              = 40
frame_index              uint64
v4l2_sequence            uint32
v4l2_timestamp_ns        uint64
receive_monotonic_ns     uint64
v4l2_buffer_flags        uint32
```

## WAV: RIFF-Chunk `kbts`

Die WAV-Datei bleibt Standard-PCM mit 48 kHz und 16 Bit. Der Hardwareeingang
ist Mono. Bei der Speicherung wird das Signal mit Faktor 3 verstärkt und als
Dual-Mono auf zwei identische Kanäle geschrieben. Nach dem `data`-Chunk folgt
ein zusätzlicher RIFF-Chunk mit der ID `kbts`. Normale
WAV-Werkzeuge ignorieren diesen unbekannten Chunk; die PCM-Daten bleiben
unverändert lesbar.

Der Chunk-Payload beginnt mit einem 44 Byte großen Little-Endian-Header:

```text
<4sHHIIIIHHQQ
magic[4]                       = "KATS"
version                        = 1
header_size                    = 44
record_size                    = 24
flags                          uint32
clock_id                       = 1 (CLOCK_MONOTONIC)
sample_rate                    = 48000
channels                       = 2
bits_per_sample                = 16
first_sample_monotonic_ns      uint64
record_count                   uint64
```

Flags des Headers:

- Bit 0: Zeitstempel stammt von `snd_pcm_htimestamp`
- Bit 1: Zeitbasis ist `CLOCK_MONOTONIC`
- Bit 2: periodische Zeitanker sind vorhanden

Danach folgen `record_count` Datensätze mit jeweils 24 Byte:

```text
<QQII
sample_index              uint64
monotonic_ns              uint64
available_frames          uint32
flags                     uint32
```

`sample_index` bezeichnet die PCM-Position, die zum zugehörigen ALSA-
Hardwarezeitstempel gehört. Bit 0 der Datensatz-Flags kennzeichnet einen seit
dem vorherigen Anker aufgetretenen XRUN.

## Zuordnung eines Audiosamples

Zwischen zwei benachbarten Ankern wird der Zeitpunkt eines Samples linear
interpoliert:

```text
t(s) = t0 + (s - s0) * (t1 - t0) / (s1 - s0)
```

Damit wird nicht nur der Startversatz berücksichtigt, sondern auch die Drift
des eigenständigen USB-Audiotakts. Ein XRUN bleibt als Flag und als Sprung auf
der monotonen Zeitachse sichtbar und darf nicht durch erfundene Samples
verdeckt werden.
