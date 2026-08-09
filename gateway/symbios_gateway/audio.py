from __future__ import annotations

import audioop
import struct
import time

INPUT_SAMPLE_RATE = 16_000
OUTPUT_SAMPLE_RATE = 24_000
CHANNELS = 1
FRAME_DURATION_MS = 60
INPUT_FRAME_SAMPLES = INPUT_SAMPLE_RATE * FRAME_DURATION_MS // 1000
OUTPUT_FRAME_SAMPLES = OUTPUT_SAMPLE_RATE * FRAME_DURATION_MS // 1000
OUTPUT_FRAME_BYTES = OUTPUT_FRAME_SAMPLES * 2


def unwrap_opus_frame(packet: bytes, protocol_version: int) -> bytes:
    if protocol_version == 2:
        if len(packet) < 12:
            raise ValueError("truncated Xiaozhi v2 audio frame")
        version, packet_type, _timestamp, payload_size = struct.unpack("!HHII", packet[:12])
        if version != 2 or packet_type != 0 or payload_size != len(packet) - 12:
            raise ValueError("invalid Xiaozhi v2 audio frame")
        return packet[12:]
    if protocol_version == 3:
        if len(packet) < 4:
            raise ValueError("truncated Xiaozhi v3 audio frame")
        packet_type, _reserved, payload_size = struct.unpack("!BBH", packet[:4])
        if packet_type != 0 or payload_size != len(packet) - 4:
            raise ValueError("invalid Xiaozhi v3 audio frame")
        return packet[4:]
    return packet


def wrap_opus_frame(payload: bytes, protocol_version: int) -> bytes:
    if protocol_version == 2:
        timestamp = int(time.monotonic() * 1000) & 0xFFFFFFFF
        return struct.pack("!HHII", 2, 0, timestamp, len(payload)) + payload
    if protocol_version == 3:
        if len(payload) > 0xFFFF:
            raise ValueError("Xiaozhi v3 Opus payload is too large")
        return struct.pack("!BBH", 0, 0, len(payload)) + payload
    return payload


class XiaozhiAudioCodec:
    """Translate Xiaozhi 16 kHz Opus to/from a 24 kHz PCM16 voice service."""

    def __init__(self) -> None:
        import opuslib_next

        self._decoder = opuslib_next.Decoder(INPUT_SAMPLE_RATE, CHANNELS)
        self._encoder = opuslib_next.Encoder(OUTPUT_SAMPLE_RATE, CHANNELS, "audio")
        self._encoder.bitrate = 24_000
        self._input_resample_state = None
        self._output_pcm = bytearray()

    def decode_input(self, opus_payload: bytes) -> bytes:
        pcm16 = self._decoder.decode(opus_payload, INPUT_FRAME_SAMPLES)
        resampled, self._input_resample_state = audioop.ratecv(
            pcm16,
            2,
            CHANNELS,
            INPUT_SAMPLE_RATE,
            OUTPUT_SAMPLE_RATE,
            self._input_resample_state,
        )
        return resampled

    def decode_input_16k(self, opus_payload: bytes) -> bytes:
        return self._decoder.decode(opus_payload, INPUT_FRAME_SAMPLES)

    def feed_output(self, pcm16: bytes) -> list[bytes]:
        self._output_pcm.extend(pcm16)
        packets: list[bytes] = []
        while len(self._output_pcm) >= OUTPUT_FRAME_BYTES:
            frame = bytes(self._output_pcm[:OUTPUT_FRAME_BYTES])
            del self._output_pcm[:OUTPUT_FRAME_BYTES]
            packets.append(self._encoder.encode(frame, OUTPUT_FRAME_SAMPLES))
        return packets

    def flush_output(self) -> list[bytes]:
        if not self._output_pcm:
            return []
        padded = bytes(self._output_pcm).ljust(OUTPUT_FRAME_BYTES, b"\0")
        self._output_pcm.clear()
        return [self._encoder.encode(padded, OUTPUT_FRAME_SAMPLES)]

    def clear_output(self) -> None:
        self._output_pcm.clear()
        self._encoder.reset_state()
