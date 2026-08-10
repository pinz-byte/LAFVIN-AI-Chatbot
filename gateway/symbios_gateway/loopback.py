from __future__ import annotations

import asyncio
import audioop
import json
import logging
import struct
from dataclasses import dataclass, field

from fastapi import WebSocket

from .audio import (
    FRAME_DURATION_MS,
    OUTPUT_FRAME_BYTES,
    XiaozhiAudioCodec,
    amplify_pcm16,
    unwrap_opus_frame,
    wrap_opus_frame,
)
from .config import GatewaySettings


logger = logging.getLogger("uvicorn.error")

LOOPBACK_SAMPLE_RATE = 24_000
MAX_LOOPBACK_SECONDS = 20
MAX_LOOPBACK_PCM_BYTES = LOOPBACK_SAMPLE_RATE * 2 * MAX_LOOPBACK_SECONDS


class RamLoopbackBridgeError(RuntimeError):
    pass


@dataclass
class RamLoopbackState:
    listening: bool = False
    frames: int = 0
    input_pcm_bytes: int = 0
    input_abs_sum: int = 0
    input_samples: int = 0
    input_peak: int = 0
    truncated: bool = False
    resample_state: object | None = None
    pcm24: bytearray = field(default_factory=bytearray, repr=False)


def _zero_and_clear(buffer: bytearray) -> None:
    if buffer:
        buffer[:] = b"\0" * len(buffer)
        buffer.clear()


def _reset_turn(state: RamLoopbackState) -> None:
    _zero_and_clear(state.pcm24)
    state.listening = True
    state.frames = 0
    state.input_pcm_bytes = 0
    state.input_abs_sum = 0
    state.input_samples = 0
    state.input_peak = 0
    state.truncated = False
    state.resample_state = None


def _record_input(state: RamLoopbackState, pcm16: bytes) -> None:
    if len(pcm16) % 2:
        raise RamLoopbackBridgeError("decoded device PCM has an odd byte count")
    state.frames += 1
    state.input_pcm_bytes += len(pcm16)
    for (sample,) in struct.iter_unpack("<h", pcm16):
        magnitude = abs(sample)
        state.input_abs_sum += magnitude
        state.input_samples += 1
        state.input_peak = max(state.input_peak, magnitude)


def _mean_abs(state: RamLoopbackState) -> int:
    if not state.input_samples:
        return 0
    return state.input_abs_sum // state.input_samples


def _append_bounded(state: RamLoopbackState, pcm24: bytes) -> None:
    remaining = MAX_LOOPBACK_PCM_BYTES - len(state.pcm24)
    if remaining <= 0:
        state.truncated = True
        return
    state.pcm24.extend(pcm24[:remaining])
    if len(pcm24) > remaining:
        state.truncated = True


async def _send_xiaozhi_json(
    websocket: WebSocket, session_id: str, **payload: object
) -> None:
    await websocket.send_json({"session_id": session_id, **payload})


async def _play_and_clear(
    websocket: WebSocket,
    codec: XiaozhiAudioCodec,
    state: RamLoopbackState,
    *,
    protocol_version: int,
    session_id: str,
) -> None:
    logger.info(
        "RAM loopback turn ready: frames=%d pcm_bytes=%d mean_abs=%d peak=%d "
        "buffered_bytes=%d truncated=%s",
        state.frames,
        state.input_pcm_bytes,
        _mean_abs(state),
        state.input_peak,
        len(state.pcm24),
        state.truncated,
    )
    if not state.pcm24:
        return

    try:
        await _send_xiaozhi_json(websocket, session_id, type="tts", state="start")
        await _send_xiaozhi_json(websocket, session_id, type="llm", emotion="neutral")
        # Let the ESP32 process the state transition before binary audio arrives.
        await asyncio.sleep(0.1)
        for offset in range(0, len(state.pcm24), OUTPUT_FRAME_BYTES):
            chunk = bytes(state.pcm24[offset : offset + OUTPUT_FRAME_BYTES])
            for opus_payload in codec.feed_output(chunk):
                await websocket.send_bytes(
                    wrap_opus_frame(opus_payload, protocol_version)
                )
                await asyncio.sleep(FRAME_DURATION_MS / 1000)
        for opus_payload in codec.flush_output():
            await websocket.send_bytes(wrap_opus_frame(opus_payload, protocol_version))
            await asyncio.sleep(FRAME_DURATION_MS / 1000)
        await _send_xiaozhi_json(websocket, session_id, type="tts", state="stop")
        logger.info("RAM loopback replay completed and volatile turn buffer cleared")
    finally:
        codec.clear_output()
        _zero_and_clear(state.pcm24)


async def run_ram_loopback_bridge(
    websocket: WebSocket,
    settings: GatewaySettings,
    *,
    protocol_version: int,
) -> None:
    """Replay one device turn from volatile memory without contacting a provider."""
    session_id = "symbios_ram_loopback"
    codec = XiaozhiAudioCodec()
    state = RamLoopbackState()

    await _send_xiaozhi_json(
        websocket,
        session_id,
        type="hello",
        version=protocol_version,
        transport="websocket",
        audio_params={
            "format": "opus",
            "sample_rate": LOOPBACK_SAMPLE_RATE,
            "channels": 1,
            "frame_duration": FRAME_DURATION_MS,
        },
    )

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                if not state.listening:
                    continue
                try:
                    opus_payload = unwrap_opus_frame(
                        message["bytes"], protocol_version
                    )
                    pcm16 = codec.decode_input_16k(opus_payload)
                except (ValueError, RuntimeError) as exc:
                    raise RamLoopbackBridgeError("invalid device audio frame") from exc
                _record_input(state, pcm16)
                pcm16 = amplify_pcm16(pcm16, settings.vertex_input_gain)
                pcm24, state.resample_state = audioop.ratecv(
                    pcm16,
                    2,
                    1,
                    16_000,
                    LOOPBACK_SAMPLE_RATE,
                    state.resample_state,
                )
                _append_bounded(state, pcm24)
                continue

            text = message.get("text")
            if text is None:
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "listen" and event.get("state") == "start":
                codec.clear_output()
                _reset_turn(state)
                logger.info("RAM loopback listening started; provider forwarding disabled")
            elif event.get("type") == "listen" and event.get("state") == "stop":
                if state.listening:
                    state.listening = False
                    await _play_and_clear(
                        websocket,
                        codec,
                        state,
                        protocol_version=protocol_version,
                        session_id=session_id,
                    )
            elif event.get("type") == "abort":
                state.listening = False
                codec.clear_output()
                _zero_and_clear(state.pcm24)
                logger.info("RAM loopback turn aborted and volatile buffer cleared")
    finally:
        _zero_and_clear(state.pcm24)
