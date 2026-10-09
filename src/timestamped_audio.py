"""ALSA-WAV-Aufnahme mit eingebetteten monotonen Sample-Zeitankern."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import struct
import threading
import wave
from array import array


SAMPLE_RATE = 48_000
INPUT_CHANNELS = 1
OUTPUT_CHANNELS = 2
SAMPLE_WIDTH_BYTES = 2
PERIOD_FRAMES = 960  # 20 ms bei 48 kHz
DIGITAL_GAIN = 3.0

_SND_PCM_STREAM_CAPTURE = 1
_SND_PCM_ACCESS_RW_INTERLEAVED = 3
_SND_PCM_FORMAT_S16_LE = 2
_SND_PCM_TSTAMP_ENABLE = 1
_SND_PCM_TSTAMP_TYPE_MONOTONIC = 1
_EPIPE = 32

_METADATA_CHUNK_ID = b"kbts"
_METADATA_MAGIC = b"KATS"
_METADATA_VERSION = 1
_METADATA_FLAG_ALSA_HTSTAMP = 0x01
_METADATA_FLAG_CLOCK_MONOTONIC = 0x02
_METADATA_FLAG_PERIODIC_ANCHORS = 0x04
_RECORD_FLAG_XRUN = 0x01

# magic, version, header size, record size, flags, clock id, sample rate,
# channels, bits per sample, timestamp of sample 0, record count
_METADATA_HEADER = struct.Struct("<4sHHIIIIHHQQ")
# sample index at the ALSA hardware position, CLOCK_MONOTONIC timestamp ns,
# frames available when the timestamp was taken, flags
_METADATA_RECORD = struct.Struct("<QQII")


class _Timespec(ctypes.Structure):
    _fields_ = (("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long))


class _Alsa:
    def __init__(self):
        library = ctypes.util.find_library("asound") or "libasound.so.2"
        self.lib = ctypes.CDLL(library, use_errno=True)
        self._declare_functions()

    def _declare_functions(self):
        lib = self.lib
        lib.snd_pcm_open.argtypes = (
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
        )
        lib.snd_pcm_open.restype = ctypes.c_int
        lib.snd_pcm_set_params.argtypes = (
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
            ctypes.c_uint, ctypes.c_int, ctypes.c_uint,
        )
        lib.snd_pcm_set_params.restype = ctypes.c_int
        lib.snd_pcm_sw_params_malloc.argtypes = (ctypes.POINTER(ctypes.c_void_p),)
        lib.snd_pcm_sw_params_malloc.restype = ctypes.c_int
        lib.snd_pcm_sw_params_current.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        lib.snd_pcm_sw_params_current.restype = ctypes.c_int
        lib.snd_pcm_sw_params_set_tstamp_mode.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
        )
        lib.snd_pcm_sw_params_set_tstamp_mode.restype = ctypes.c_int
        lib.snd_pcm_sw_params_set_tstamp_type.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
        )
        lib.snd_pcm_sw_params_set_tstamp_type.restype = ctypes.c_int
        lib.snd_pcm_sw_params.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        lib.snd_pcm_sw_params.restype = ctypes.c_int
        lib.snd_pcm_sw_params_free.argtypes = (ctypes.c_void_p,)
        lib.snd_pcm_prepare.argtypes = (ctypes.c_void_p,)
        lib.snd_pcm_prepare.restype = ctypes.c_int
        lib.snd_pcm_start.argtypes = (ctypes.c_void_p,)
        lib.snd_pcm_start.restype = ctypes.c_int
        lib.snd_pcm_wait.argtypes = (ctypes.c_void_p, ctypes.c_int)
        lib.snd_pcm_wait.restype = ctypes.c_int
        lib.snd_pcm_htimestamp.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(_Timespec),
        )
        lib.snd_pcm_htimestamp.restype = ctypes.c_int
        lib.snd_pcm_readi.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)
        lib.snd_pcm_readi.restype = ctypes.c_long
        lib.snd_pcm_recover.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_int)
        lib.snd_pcm_recover.restype = ctypes.c_int
        lib.snd_pcm_drop.argtypes = (ctypes.c_void_p,)
        lib.snd_pcm_drop.restype = ctypes.c_int
        lib.snd_pcm_close.argtypes = (ctypes.c_void_p,)
        lib.snd_pcm_close.restype = ctypes.c_int
        lib.snd_strerror.argtypes = (ctypes.c_int,)
        lib.snd_strerror.restype = ctypes.c_char_p

    def check(self, result: int, operation: str):
        if result < 0:
            detail = self.lib.snd_strerror(result)
            message = detail.decode("utf-8", errors="replace") if detail else str(result)
            raise OSError(f"{operation}: {message}")


class TimestampedAudioRecorder:
    """Nimmt PCM auf und hängt monotone ALSA-Zeitanker als ``kbts``-Chunk an."""

    def __init__(
        self,
        device: str,
        filename: str,
        sample_rate: int = SAMPLE_RATE,
        input_channels: int = INPUT_CHANNELS,
        output_channels: int = OUTPUT_CHANNELS,
        period_frames: int = PERIOD_FRAMES,
        digital_gain: float = DIGITAL_GAIN,
    ):
        self.device = device
        self.filename = filename
        self.sample_rate = sample_rate
        if input_channels != 1 or output_channels not in (1, 2):
            raise ValueError("Unterstützt wird ausschließlich Mono-Eingang mit Mono-/Stereo-Ausgabe")
        if digital_gain <= 0:
            raise ValueError("digital_gain muss größer als 0 sein")
        self.input_channels = input_channels
        self.channels = output_channels
        self.period_frames = period_frames
        self.digital_gain = digital_gain
        self.returncode: int | None = None
        self.error: str | None = None
        self.stop_requested = False
        self.frames_written = 0
        self.timestamp_records = 0
        self.xrun_count = 0
        self.clipped_samples = 0
        self.first_sample_monotonic_ns: int | None = None

        self._alsa = _Alsa()
        self._pcm = ctypes.c_void_p()
        self._stop_event = threading.Event()
        self._first_anchor_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._wave: wave.Wave_write | None = None
        self._metadata_file = None
        self._metadata_path = f"{filename}.kbts.tmp"
        self._last_anchor: tuple[int, int] | None = None
        self._pending_record_flags = 0

    def start(self):
        """Öffnet ALSA und startet Aufnahme sowie Zeitstempelung synchron."""
        try:
            self._open_pcm()
            self._wave = wave.open(self.filename, "wb")
            self._wave.setnchannels(self.channels)
            self._wave.setsampwidth(SAMPLE_WIDTH_BYTES)
            self._wave.setframerate(self.sample_rate)
            self._metadata_file = open(self._metadata_path, "w+b", buffering=0)
            self._alsa.check(self._alsa.lib.snd_pcm_start(self._pcm), "snd_pcm_start")
            self._thread = threading.Thread(
                target=self._capture_loop,
                name="timestamped-audio-capture",
                daemon=True,
            )
            self._thread.start()
        except Exception:
            self._close_resources(append_metadata=False)
            raise
        return self

    def wait_for_first_timestamp(self, timeout: float = 2.0) -> bool:
        return self._first_anchor_event.wait(timeout)

    def poll(self):
        return self.returncode

    def terminate(self):
        self.stop_requested = True
        self._stop_event.set()

    def wait(self, timeout: float | None = None):
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise TimeoutError("Audioaufnahme konnte nicht rechtzeitig beendet werden")
        return self.returncode

    def _open_pcm(self):
        lib = self._alsa.lib
        self._alsa.check(
            lib.snd_pcm_open(
                ctypes.byref(self._pcm),
                self.device.encode("utf-8"),
                _SND_PCM_STREAM_CAPTURE,
                0,
            ),
            "snd_pcm_open",
        )
        self._alsa.check(
            lib.snd_pcm_set_params(
                self._pcm,
                _SND_PCM_FORMAT_S16_LE,
                _SND_PCM_ACCESS_RW_INTERLEAVED,
                self.input_channels,
                self.sample_rate,
                0,
                100_000,
            ),
            "snd_pcm_set_params",
        )

        sw_params = ctypes.c_void_p()
        self._alsa.check(lib.snd_pcm_sw_params_malloc(ctypes.byref(sw_params)), "sw_params_malloc")
        try:
            self._alsa.check(
                lib.snd_pcm_sw_params_current(self._pcm, sw_params),
                "sw_params_current",
            )
            self._alsa.check(
                lib.snd_pcm_sw_params_set_tstamp_mode(
                    self._pcm, sw_params, _SND_PCM_TSTAMP_ENABLE,
                ),
                "sw_params_set_tstamp_mode",
            )
            self._alsa.check(
                lib.snd_pcm_sw_params_set_tstamp_type(
                    self._pcm, sw_params, _SND_PCM_TSTAMP_TYPE_MONOTONIC,
                ),
                "sw_params_set_tstamp_type",
            )
            self._alsa.check(lib.snd_pcm_sw_params(self._pcm, sw_params), "snd_pcm_sw_params")
        finally:
            lib.snd_pcm_sw_params_free(sw_params)
        self._alsa.check(lib.snd_pcm_prepare(self._pcm), "snd_pcm_prepare")

    def _capture_loop(self):
        input_bytes_per_frame = self.input_channels * SAMPLE_WIDTH_BYTES
        buffer = ctypes.create_string_buffer(self.period_frames * input_bytes_per_frame)
        try:
            while not self._stop_event.is_set():
                wait_result = self._alsa.lib.snd_pcm_wait(self._pcm, 100)
                if wait_result < 0:
                    self._recover(wait_result)
                    continue
                if wait_result == 0:
                    continue

                available = ctypes.c_ulong()
                timestamp = _Timespec()
                result = self._alsa.lib.snd_pcm_htimestamp(
                    self._pcm, ctypes.byref(available), ctypes.byref(timestamp)
                )
                self._alsa.check(result, "snd_pcm_htimestamp")
                if available.value == 0:
                    continue

                timestamp_ns = timestamp.tv_sec * 1_000_000_000 + timestamp.tv_nsec
                hardware_position = self.frames_written + int(available.value)
                self._store_anchor(
                    hardware_position,
                    timestamp_ns,
                    int(available.value),
                    self._pending_record_flags,
                )
                self._pending_record_flags = 0

                frames_to_read = min(self.period_frames, int(available.value))
                frames_read = self._alsa.lib.snd_pcm_readi(
                    self._pcm, buffer, frames_to_read
                )
                if frames_read < 0:
                    self._recover(int(frames_read))
                    continue
                if frames_read == 0:
                    continue
                byte_count = int(frames_read) * input_bytes_per_frame
                self._wave.writeframesraw(self._process_pcm(buffer.raw[:byte_count]))
                self.frames_written += int(frames_read)

            self.returncode = 0
        except Exception as exc:
            self.error = str(exc)
            self.returncode = 1
        finally:
            try:
                self._close_resources(append_metadata=True)
            except Exception as exc:
                self.error = str(exc)
                self.returncode = 1

    def _recover(self, error_code: int):
        if error_code == -_EPIPE:
            self.xrun_count += 1
            self._pending_record_flags |= _RECORD_FLAG_XRUN
        result = self._alsa.lib.snd_pcm_recover(self._pcm, error_code, 1)
        self._alsa.check(result, "snd_pcm_recover")

    def _store_anchor(
        self,
        sample_index: int,
        monotonic_ns: int,
        available_frames: int,
        flags: int,
    ):
        anchor = (sample_index, monotonic_ns)
        if anchor == self._last_anchor:
            return
        self._metadata_file.write(
            _METADATA_RECORD.pack(
                sample_index,
                monotonic_ns,
                available_frames,
                flags,
            )
        )
        self._last_anchor = anchor
        self.timestamp_records += 1
        if self.first_sample_monotonic_ns is None:
            elapsed_ns = (sample_index * 1_000_000_000 + self.sample_rate // 2) // self.sample_rate
            self.first_sample_monotonic_ns = monotonic_ns - elapsed_ns
            self._first_anchor_event.set()

    def _process_pcm(self, mono_pcm: bytes) -> bytes:
        """Verstärkt S16_LE-Mono und erzeugt optional kompatibles Dual-Mono."""
        mono_samples = array("h")
        mono_samples.frombytes(mono_pcm)
        if struct.pack("=H", 1) != struct.pack("<H", 1):
            mono_samples.byteswap()

        output = array("h")
        append = output.append
        clipped = 0
        for sample in mono_samples:
            amplified = round(sample * self.digital_gain)
            if amplified > 32767:
                amplified = 32767
                clipped += 1
            elif amplified < -32768:
                amplified = -32768
                clipped += 1
            append(amplified)
            if self.channels == 2:
                append(amplified)
        self.clipped_samples += clipped

        if struct.pack("=H", 1) != struct.pack("<H", 1):
            output.byteswap()
        return output.tobytes()

    def _close_resources(self, append_metadata: bool):
        pcm = self._pcm
        self._pcm = ctypes.c_void_p()
        if pcm:
            try:
                self._alsa.lib.snd_pcm_drop(pcm)
            finally:
                self._alsa.lib.snd_pcm_close(pcm)

        if self._wave is not None:
            self._wave.close()
            self._wave = None
        if self._metadata_file is not None:
            self._metadata_file.close()
            self._metadata_file = None

        if append_metadata and self.timestamp_records:
            self._append_metadata_chunk()
        try:
            os.unlink(self._metadata_path)
        except FileNotFoundError:
            pass

    def _append_metadata_chunk(self):
        flags = (
            _METADATA_FLAG_ALSA_HTSTAMP
            | _METADATA_FLAG_CLOCK_MONOTONIC
            | _METADATA_FLAG_PERIODIC_ANCHORS
        )
        header = _METADATA_HEADER.pack(
            _METADATA_MAGIC,
            _METADATA_VERSION,
            _METADATA_HEADER.size,
            _METADATA_RECORD.size,
            flags,
            1,  # CLOCK_MONOTONIC
            self.sample_rate,
            self.channels,
            SAMPLE_WIDTH_BYTES * 8,
            self.first_sample_monotonic_ns or 0,
            self.timestamp_records,
        )
        payload_size = len(header) + self.timestamp_records * _METADATA_RECORD.size
        if payload_size > 0xFFFFFFFF:
            raise OverflowError("Audio-Zeitstempelmetadaten überschreiten RIFF-Chunk-Limit")

        with open(self.filename, "r+b", buffering=0) as wav_file:
            wav_file.seek(0, os.SEEK_END)
            wav_file.write(_METADATA_CHUNK_ID)
            wav_file.write(struct.pack("<I", payload_size))
            wav_file.write(header)
            with open(self._metadata_path, "rb", buffering=0) as metadata_file:
                while block := metadata_file.read(1024 * 1024):
                    wav_file.write(block)
            if payload_size & 1:
                wav_file.write(b"\x00")
            file_size = wav_file.tell()
            if file_size - 8 > 0xFFFFFFFF:
                raise OverflowError("WAV-Datei überschreitet RIFF-Größenlimit")
            wav_file.seek(4)
            wav_file.write(struct.pack("<I", file_size - 8))
