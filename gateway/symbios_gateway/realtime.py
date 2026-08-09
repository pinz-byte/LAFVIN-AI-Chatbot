from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import uuid
from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi import WebSocket
from websockets.asyncio.client import ClientConnection, connect as connect_websocket

from .audio import XiaozhiAudioCodec, unwrap_opus_frame, wrap_opus_frame
from .config import GatewaySettings


class RealtimeBridgeError(RuntimeError):
    pass


@dataclass
class BridgeState:
    listening: bool = False
    listening_mode: str = "auto"
    response_active: bool = False
    tts_active: bool = False
    assistant_transcript: str = ""


def _safety_identifier(device_id: str, client_id: str) -> str:
    digest = hashlib.sha256(f"{device_id}\0{client_id}".encode("utf-8")).hexdigest()
    return f"symbios_{digest[:40]}"


def _realtime_url(settings: GatewaySettings) -> str:
    separator = "&" if "?" in settings.openai_realtime_url else "?"
    return f"{settings.openai_realtime_url}{separator}{urlencode({'model': settings.openai_realtime_model})}"


def _session_update(settings: GatewaySettings) -> str:
    return json.dumps(
        {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "model": settings.openai_realtime_model,
                "output_modalities": ["audio"],
                "instructions": settings.voice_instructions,
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": 24_000},
                        "transcription": {"model": settings.openai_transcription_model},
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 600,
                            "create_response": True,
                            "interrupt_response": True,
                        },
                    },
                    "output": {
                        "format": {"type": "audio/pcm"},
                        "voice": settings.openai_voice,
                    },
                },
            },
        },
        separators=(",", ":"),
    )


async def _send_xiaozhi_json(websocket: WebSocket, session_id: str, **payload: object) -> None:
    await websocket.send_json({"session_id": session_id, **payload})


async def _cancel_response(upstream: ClientConnection, state: BridgeState) -> None:
    if state.response_active:
        await upstream.send('{"type":"response.cancel"}')
    await upstream.send('{"type":"input_audio_buffer.clear"}')
    state.response_active = False


async def run_openai_realtime_bridge(
    websocket: WebSocket,
    settings: GatewaySettings,
    *,
    device_id: str,
    client_id: str,
    protocol_version: int,
) -> None:
    if not settings.openai_api_key:
        raise RealtimeBridgeError("OpenAI Realtime is not configured")

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "OpenAI-Safety-Identifier": _safety_identifier(device_id, client_id),
    }
    session_id = uuid.uuid4().hex
    codec = XiaozhiAudioCodec()
    state = BridgeState()

    async with connect_websocket(
        _realtime_url(settings),
        additional_headers=headers,
        max_size=4 * 1024 * 1024,
        ping_interval=20,
        ping_timeout=20,
        open_timeout=8,
    ) as upstream:
        await upstream.send(_session_update(settings))
        await _send_xiaozhi_json(
            websocket,
            session_id,
            type="hello",
            version=protocol_version,
            transport="websocket",
            audio_params={
                "format": "opus",
                "sample_rate": 24_000,
                "channels": 1,
                "frame_duration": 60,
            },
        )

        async def device_to_openai() -> None:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                if message.get("bytes") is not None:
                    if not state.listening:
                        continue
                    try:
                        opus_payload = unwrap_opus_frame(message["bytes"], protocol_version)
                        pcm16 = codec.decode_input(opus_payload)
                    except (ValueError, RuntimeError) as exc:
                        raise RealtimeBridgeError("invalid device audio frame") from exc
                    await upstream.send(
                        json.dumps(
                            {
                                "type": "input_audio_buffer.append",
                                "audio": base64.b64encode(pcm16).decode("ascii"),
                            },
                            separators=(",", ":"),
                        )
                    )
                    continue

                text = message.get("text")
                if text is None:
                    continue
                try:
                    event = json.loads(text)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if event_type == "listen":
                    listen_state = event.get("state")
                    if listen_state in {"detect", "start"}:
                        await _cancel_response(upstream, state)
                        codec.clear_output()
                    if listen_state == "start":
                        state.listening = True
                        state.listening_mode = str(event.get("mode", "auto"))
                    elif listen_state == "stop":
                        state.listening = False
                        if state.listening_mode == "manual":
                            await upstream.send('{"type":"input_audio_buffer.commit"}')
                            await upstream.send('{"type":"response.create"}')
                            state.response_active = True
                elif event_type == "abort":
                    await _cancel_response(upstream, state)
                    codec.clear_output()
                    state.tts_active = False
                    state.assistant_transcript = ""

        async def openai_to_device() -> None:
            async for raw_message in upstream:
                if not isinstance(raw_message, str):
                    continue
                try:
                    event = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")

                if event_type == "error":
                    error = event.get("error") or {}
                    code = error.get("code", "realtime_error")
                    message = error.get("message", "OpenAI Realtime error")
                    raise RealtimeBridgeError(f"{code}: {message}")
                if event_type == "response.created":
                    state.response_active = True
                    state.assistant_transcript = ""
                    await _send_xiaozhi_json(
                        websocket, session_id, type="llm", emotion="neutral"
                    )
                    continue
                if event_type == "conversation.item.input_audio_transcription.completed":
                    transcript = event.get("transcript")
                    if isinstance(transcript, str) and transcript.strip():
                        await _send_xiaozhi_json(
                            websocket, session_id, type="stt", text=transcript.strip()
                        )
                    continue
                if event_type == "response.output_audio_transcript.delta":
                    delta = event.get("delta")
                    if isinstance(delta, str):
                        state.assistant_transcript += delta
                    continue
                if event_type == "response.output_audio_transcript.done":
                    transcript = event.get("transcript")
                    if isinstance(transcript, str):
                        state.assistant_transcript = transcript
                    continue
                if event_type == "response.output_audio.delta":
                    delta = event.get("delta")
                    if not isinstance(delta, str):
                        continue
                    if not state.tts_active:
                        await _send_xiaozhi_json(
                            websocket, session_id, type="tts", state="start"
                        )
                        state.tts_active = True
                        state.listening = False
                    try:
                        pcm16 = base64.b64decode(delta, validate=True)
                    except ValueError as exc:
                        raise RealtimeBridgeError("invalid Realtime audio payload") from exc
                    for opus_payload in codec.feed_output(pcm16):
                        await websocket.send_bytes(wrap_opus_frame(opus_payload, protocol_version))
                    continue
                if event_type == "input_audio_buffer.speech_started" and state.tts_active:
                    codec.clear_output()
                    await _send_xiaozhi_json(
                        websocket, session_id, type="tts", state="stop"
                    )
                    state.tts_active = False
                    continue
                if event_type == "response.done":
                    for opus_payload in codec.flush_output():
                        await websocket.send_bytes(wrap_opus_frame(opus_payload, protocol_version))
                    transcript = state.assistant_transcript.strip()
                    if transcript:
                        await _send_xiaozhi_json(
                            websocket,
                            session_id,
                            type="tts",
                            state="sentence_start",
                            text=transcript,
                        )
                    if state.tts_active:
                        await _send_xiaozhi_json(
                            websocket, session_id, type="tts", state="stop"
                        )
                    state.response_active = False
                    state.tts_active = False
                    state.assistant_transcript = ""

        tasks = {
            asyncio.create_task(device_to_openai()),
            asyncio.create_task(openai_to_device()),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
