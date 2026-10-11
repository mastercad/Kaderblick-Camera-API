import ctypes
import queue
import struct
import time
import wave
from array import array
from unittest.mock import MagicMock, patch

import pytest

from timestamped_audio import (
    _METADATA_CHUNK_ID,
    _METADATA_HEADER,
    _METADATA_MAGIC,
    _METADATA_RECORD,
    _WRITER_STOP,
    BUFFER_TIME_US,
    TimestampedAudioRecorder,
    _SND_PCM_STATE_PREPARED,
    _SND_PCM_STATE_RUNNING,
    _SND_PCM_STATE_XRUN,
)


def _recorder_without_alsa(tmp_path):
    recorder = object.__new__(TimestampedAudioRecorder)
    recorder.filename = str(tmp_path / "audio.wav")
    recorder.sample_rate = 48_000
    recorder.channels = 1
    recorder.timestamp_records = 0
    recorder.first_sample_monotonic_ns = None
    recorder._metadata_path = f"{recorder.filename}.kbts.tmp"
    recorder._metadata_file = open(recorder._metadata_path, "w+b", buffering=0)
    recorder._last_anchor = None
    return recorder


def test_first_sample_timestamp_is_derived_from_alsa_anchor(tmp_path):
    recorder = _recorder_without_alsa(tmp_path)
    recorder._first_anchor_event = type("Event", (), {"set": lambda self: None})()

    recorder._store_anchor(4_800, 11_000_000_000, 960, 0)

    assert recorder.first_sample_monotonic_ns == 10_900_000_000
    assert recorder.timestamp_records == 1
    recorder._metadata_file.close()


def test_metadata_chunk_is_embedded_without_changing_pcm_data(tmp_path):
    recorder = _recorder_without_alsa(tmp_path)
    recorder._first_anchor_event = type("Event", (), {"set": lambda self: None})()
    pcm = b"\x01\x02" * 960
    with wave.open(recorder.filename, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(48_000)
        wav_file.writeframes(pcm)

    recorder._store_anchor(960, 5_020_000_000, 960, 0)
    recorder._store_anchor(1_920, 5_040_000_000, 960, 0)
    recorder._metadata_file.close()
    recorder._append_metadata_chunk()

    with wave.open(recorder.filename, "rb") as wav_file:
        assert wav_file.getparams().nchannels == 1
        assert wav_file.getparams().framerate == 48_000
        assert wav_file.readframes(960) == pcm

    data = (tmp_path / "audio.wav").read_bytes()
    offset = data.index(_METADATA_CHUNK_ID)
    payload_size = struct.unpack_from("<I", data, offset + 4)[0]
    payload = data[offset + 8:offset + 8 + payload_size]
    header = _METADATA_HEADER.unpack_from(payload)
    assert header[0] == _METADATA_MAGIC
    assert header[1] == 1
    assert header[3] == _METADATA_RECORD.size
    assert header[6:9] == (48_000, 1, 16)
    assert header[9] == 5_000_000_000
    assert header[10] == 2
    assert len(payload) == _METADATA_HEADER.size + 2 * _METADATA_RECORD.size


def test_duplicate_hardware_anchor_is_written_only_once(tmp_path):
    recorder = _recorder_without_alsa(tmp_path)
    recorder._first_anchor_event = type("Event", (), {"set": lambda self: None})()

    recorder._store_anchor(960, 5_020_000_000, 960, 0)
    recorder._store_anchor(960, 5_020_000_000, 960, 0)

    assert recorder.timestamp_records == 1
    assert recorder._metadata_file.tell() == _METADATA_RECORD.size
    recorder._metadata_file.close()


def test_mono_is_amplified_threefold_and_duplicated_to_stereo():
    recorder = object.__new__(TimestampedAudioRecorder)
    recorder.digital_gain = 3.0
    recorder.channels = 2
    recorder.clipped_samples = 0
    source = array("h", [1000, -2000, 10_000]).tobytes()

    result = array("h")
    result.frombytes(recorder._process_pcm(source))

    assert result.tolist() == [3000, 3000, -6000, -6000, 30_000, 30_000]
    assert recorder.clipped_samples == 0


def test_gain_clamps_overflow_instead_of_wrapping():
    recorder = object.__new__(TimestampedAudioRecorder)
    recorder.digital_gain = 3.0
    recorder.channels = 2
    recorder.clipped_samples = 0
    source = array("h", [20_000, -20_000]).tobytes()

    result = array("h")
    result.frombytes(recorder._process_pcm(source))

    assert result.tolist() == [32767, 32767, -32768, -32768]
    assert recorder.clipped_samples == 2


def test_writer_queue_decouples_pcm_processing_and_file_writes():
    recorder = object.__new__(TimestampedAudioRecorder)
    recorder._writer_queue = queue.Queue()
    recorder._writer_error = None
    recorder._metadata_file = MagicMock()
    recorder._wave = MagicMock()
    recorder._stop_event = MagicMock()
    recorder.timestamp_records = 0
    recorder.frames_written = 0
    recorder.digital_gain = 1.0
    recorder.channels = 1
    recorder.clipped_samples = 0
    pcm = array("h", [100, -100]).tobytes()
    anchor = _METADATA_RECORD.pack(2, 123, 2, 0)
    recorder._writer_queue.put((anchor, pcm, 2))
    recorder._writer_queue.put(_WRITER_STOP)

    recorder._writer_loop()

    recorder._metadata_file.write.assert_called_once_with(anchor)
    recorder._wave.writeframesraw.assert_called_once_with(pcm)
    assert recorder.frames_written == 2
    assert recorder.timestamp_records == 1
    assert recorder._writer_error is None


def test_pcm_uses_arecord_sized_buffer_and_short_availability_threshold():
    recorder = object.__new__(TimestampedAudioRecorder)
    recorder.device = "hw:0,0"
    recorder.input_channels = 1
    recorder.sample_rate = 48_000
    recorder.period_frames = 960
    recorder._pcm = ctypes.c_void_p()
    recorder._alsa = MagicMock()
    recorder._alsa.lib.snd_pcm_open.return_value = 0
    recorder._alsa.lib.snd_pcm_set_params.return_value = 0
    recorder._alsa.lib.snd_pcm_sw_params_malloc.return_value = 0
    recorder._alsa.lib.snd_pcm_sw_params_current.return_value = 0
    recorder._alsa.lib.snd_pcm_sw_params_set_tstamp_mode.return_value = 0
    recorder._alsa.lib.snd_pcm_sw_params_set_tstamp_type.return_value = 0
    recorder._alsa.lib.snd_pcm_sw_params_set_avail_min.return_value = 0
    recorder._alsa.lib.snd_pcm_sw_params.return_value = 0
    recorder._alsa.lib.snd_pcm_prepare.return_value = 0

    recorder._open_pcm()

    set_params = recorder._alsa.lib.snd_pcm_set_params.call_args.args
    assert set_params[-1] == BUFFER_TIME_US
    avail_min = recorder._alsa.lib.snd_pcm_sw_params_set_avail_min.call_args.args
    assert avail_min[0] is recorder._pcm
    assert avail_min[-1] == 960


def _recorder_for_recovery(state):
    recorder = object.__new__(TimestampedAudioRecorder)
    recorder._pcm = object()
    recorder._alsa = MagicMock()
    recorder._alsa.lib.snd_pcm_state.return_value = state
    recorder.xrun_count = 0
    recorder.recovery_restart_count = 0
    recorder._pending_record_flags = 0
    recorder.last_progress_monotonic = time.monotonic()
    return recorder


def test_xrun_and_recovery_emit_persistent_health_events():
    recorder = _recorder_for_recovery(_SND_PCM_STATE_PREPARED)
    recorder._alsa.lib.snd_pcm_recover.return_value = 0
    recorder._alsa.lib.snd_pcm_start.return_value = 0
    events = []
    recorder.health_event_callback = events.append

    recorder._recover(-32)

    assert [event["type"] for event in events] == [
        "audio_xrun",
        "audio_recovery_restart",
    ]
    assert all(event["recording"] is True for event in events)
    assert all(event["severity"] == "error" for event in events)


def test_xrun_recovery_restarts_prepared_pcm_stream():
    recorder = _recorder_for_recovery(_SND_PCM_STATE_PREPARED)
    recorder._alsa.lib.snd_pcm_recover.return_value = 0
    recorder._alsa.lib.snd_pcm_start.return_value = 0

    recorder._recover(-32)

    assert recorder.xrun_count == 1
    assert recorder.recovery_restart_count == 1
    recorder._alsa.lib.snd_pcm_recover.assert_called_once_with(recorder._pcm, -32, 1)
    recorder._alsa.lib.snd_pcm_start.assert_called_once_with(recorder._pcm)


def test_wait_timeout_restarts_prepared_pcm_stream():
    recorder = _recorder_for_recovery(_SND_PCM_STATE_PREPARED)
    recorder._alsa.lib.snd_pcm_start.return_value = 0

    recorder._handle_wait_timeout()

    assert recorder.recovery_restart_count == 1
    recorder._alsa.lib.snd_pcm_start.assert_called_once_with(recorder._pcm)


def test_wait_timeout_recovers_xrun_state():
    recorder = _recorder_for_recovery(_SND_PCM_STATE_XRUN)
    with patch.object(recorder, "_recover") as recover:
        recorder._handle_wait_timeout()

    recover.assert_called_once_with(-32)


def test_wait_timeout_fails_after_two_seconds_without_audio_progress():
    recorder = _recorder_for_recovery(_SND_PCM_STATE_RUNNING)
    recorder.last_progress_monotonic = time.monotonic() - 3

    with pytest.raises(TimeoutError, match="Keine Audiodaten"):
        recorder._handle_wait_timeout()
