import struct
import wave
from array import array

from timestamped_audio import (
    _METADATA_CHUNK_ID,
    _METADATA_HEADER,
    _METADATA_MAGIC,
    _METADATA_RECORD,
    TimestampedAudioRecorder,
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
