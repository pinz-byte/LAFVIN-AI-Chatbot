import struct

import pytest

from symbios_gateway.audio import (
    INPUT_FRAME_SAMPLES,
    OUTPUT_FRAME_BYTES,
    XiaozhiAudioCodec,
    amplify_pcm16,
    unwrap_opus_frame,
    wrap_opus_frame,
)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_xiaozhi_audio_framing_round_trip(version: int) -> None:
    payload = b"an-opus-packet"
    framed = wrap_opus_frame(payload, version)
    assert unwrap_opus_frame(framed, version) == payload


def test_xiaozhi_v2_rejects_mismatched_payload_length() -> None:
    packet = struct.pack("!HHII", 2, 0, 123, 99) + b"short"
    with pytest.raises(ValueError, match="invalid"):
        unwrap_opus_frame(packet, 2)


def test_xiaozhi_v3_rejects_non_audio_packet() -> None:
    packet = struct.pack("!BBH", 1, 0, 3) + b"abc"
    with pytest.raises(ValueError, match="invalid"):
        unwrap_opus_frame(packet, 3)


def test_pcm16_amplification_scales_and_saturates() -> None:
    pcm = struct.pack("<hhhh", 100, -100, 20_000, -20_000)

    assert struct.unpack("<hhhh", amplify_pcm16(pcm, 4.0)) == (
        400,
        -400,
        32_767,
        -32_768,
    )


def test_pcm16_amplification_rejects_invalid_input() -> None:
    with pytest.raises(ValueError, match="odd byte"):
        amplify_pcm16(b"\x00", 4.0)
    with pytest.raises(ValueError, match="at least"):
        amplify_pcm16(b"\x00\x00", 0.5)


def test_opus_decode_and_encode_paths() -> None:
    from ctypes.util import find_library

    if find_library("opus") is None:
        pytest.skip("system libopus is not installed")
    import opuslib_next

    device_encoder = opuslib_next.Encoder(16_000, 1, "audio")
    device_packet = device_encoder.encode(b"\0" * INPUT_FRAME_SAMPLES * 2, INPUT_FRAME_SAMPLES)

    codec = XiaozhiAudioCodec()
    assert len(codec.decode_input_16k(device_packet)) == INPUT_FRAME_SAMPLES * 2
    assert len(codec.decode_input(device_packet)) == OUTPUT_FRAME_BYTES
    assert len(codec.feed_output(b"\0" * OUTPUT_FRAME_BYTES)) == 1
