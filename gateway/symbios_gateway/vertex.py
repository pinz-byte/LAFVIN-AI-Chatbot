from __future__ import annotations

import asyncio
import base64
import json
import uuid
from dataclasses import dataclass

import google.auth
from fastapi import WebSocket
from google.auth.transport.requests import Request as GoogleAuthRequest
from websockets.asyncio.client import connect as connect_websocket

from .audio import XiaozhiAudioCodec, unwrap_opus_frame, wrap_opus_frame
from .config import GatewaySettings


class VertexLiveBridgeError(RuntimeError):
    pass


@dataclass
class VertexBridgeState:
    listening: bool = False
    tts_active: bool = False
    discard_output: bool = False
    user_transcript: str = ""
    assistant_transcript: str = ""


def _vertex_uri(settings: GatewaySettings) -> str:
    host = f"{settings.vertex_location}-aiplatform.googleapis.com"
    return f"wss://{host}/ws/google.cloud.aiplatform.v1.LlmBidiService/BidiGenerateContent"


def _vertex_setup(settings: GatewaySettings) -> str:
    assert settings.gcp_project is not None
    model = (
        f"projects/{settings.gcp_project}/locations/{settings.vertex_location}"
        f"/publishers/google/models/{settings.vertex_live_model}"
    )
    return json.dumps(
        {
            "setup": {
                "model": model,
                "generation_config": {"response_modalities": ["audio"]},
                "system_instruction": {
                    "parts": [{"text": settings.voice_instructions}]
                },
                "input_audio_transcription": {},
                "output_audio_transcription": {},
                "context_window_compression": {"sliding_window": {}},
            }
        },
        separators=(",", ":"),
    )


def _access_token() -> str:
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(GoogleAuthRequest())
    if not credentials.token:
        raise VertexLiveBridgeError("Vertex credentials did not produce an access token")
    return credentials.token


def _field(mapping: dict[str, object], camel: str, snake: str) -> object:
    return mapping.get(camel, mapping.get(snake))


async def _send_xiaozhi_json(websocket: WebSocket, session_id: str, **payload: object) -> None:
    await websocket.send_json({"session_id": session_id, **payload})


async def run_vertex_live_bridge(
    websocket: WebSocket,
    settings: GatewaySettings,
    *,
    protocol_version: int,
) -> None:
    token = await asyncio.to_thread(_access_token)
    session_id = uuid.uuid4().hex
    codec = XiaozhiAudioCodec()
    state = VertexBridgeState()

    async with connect_websocket(
        _vertex_uri(settings),
        additional_headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        max_size=4 * 1024 * 1024,
        ping_interval=20,
        ping_timeout=20,
        open_timeout=8,
    ) as upstream:
        await upstream.send(_vertex_setup(settings))
        try:
            setup_response = json.loads(await asyncio.wait_for(upstream.recv(), timeout=8))
        except (asyncio.TimeoutError, json.JSONDecodeError) as exc:
            raise VertexLiveBridgeError("Vertex Live setup timed out") from exc
        if "setupComplete" not in setup_response and "setup_complete" not in setup_response:
            raise VertexLiveBridgeError("Vertex Live rejected the session setup")

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

        async def device_to_vertex() -> None:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                if message.get("bytes") is not None:
                    if not state.listening:
                        continue
                    try:
                        opus_payload = unwrap_opus_frame(message["bytes"], protocol_version)
                        pcm16 = codec.decode_input_16k(opus_payload)
                    except (ValueError, RuntimeError) as exc:
                        raise VertexLiveBridgeError("invalid device audio frame") from exc
                    await upstream.send(
                        json.dumps(
                            {
                                "realtime_input": {
                                    "media_chunks": [
                                        {
                                            "data": base64.b64encode(pcm16).decode("ascii"),
                                            "mime_type": "audio/pcm;rate=16000",
                                        }
                                    ]
                                }
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
                    if listen_state == "start":
                        state.discard_output = False
                        state.listening = True
                        codec.clear_output()
                    elif listen_state == "stop":
                        state.listening = False
                    elif listen_state == "detect":
                        state.discard_output = False
                        state.user_transcript = ""
                elif event_type == "abort":
                    state.discard_output = True
                    state.tts_active = False
                    state.assistant_transcript = ""
                    codec.clear_output()

        async def finish_turn() -> None:
            if not state.discard_output:
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
            state.tts_active = False
            state.assistant_transcript = ""

        async def vertex_to_device() -> None:
            async for raw_message in upstream:
                if not isinstance(raw_message, str):
                    continue
                try:
                    event = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue
                if "error" in event:
                    error = event.get("error") or {}
                    raise VertexLiveBridgeError(
                        f"Vertex Live error: {error.get('code', 'unknown')}"
                    )

                content = _field(event, "serverContent", "server_content")
                if not isinstance(content, dict):
                    continue
                if content.get("interrupted"):
                    codec.clear_output()
                    if state.tts_active:
                        await _send_xiaozhi_json(
                            websocket, session_id, type="tts", state="stop"
                        )
                    state.tts_active = False
                    state.discard_output = False
                    state.assistant_transcript = ""
                    continue

                input_transcription = _field(
                    content, "inputTranscription", "input_transcription"
                )
                if isinstance(input_transcription, dict):
                    text = input_transcription.get("text")
                    if isinstance(text, str):
                        state.user_transcript += text
                    if input_transcription.get("finished") and state.user_transcript.strip():
                        await _send_xiaozhi_json(
                            websocket,
                            session_id,
                            type="stt",
                            text=state.user_transcript.strip(),
                        )
                        state.user_transcript = ""

                output_transcription = _field(
                    content, "outputTranscription", "output_transcription"
                )
                if isinstance(output_transcription, dict):
                    text = output_transcription.get("text")
                    if isinstance(text, str):
                        state.assistant_transcript += text

                model_turn = _field(content, "modelTurn", "model_turn")
                if isinstance(model_turn, dict) and not state.discard_output:
                    parts = model_turn.get("parts") or []
                    for part in parts:
                        if not isinstance(part, dict):
                            continue
                        inline_data = _field(part, "inlineData", "inline_data")
                        if not isinstance(inline_data, dict):
                            continue
                        data = inline_data.get("data")
                        if not isinstance(data, str):
                            continue
                        if not state.tts_active:
                            await _send_xiaozhi_json(
                                websocket, session_id, type="tts", state="start"
                            )
                            await _send_xiaozhi_json(
                                websocket, session_id, type="llm", emotion="neutral"
                            )
                            state.tts_active = True
                            state.listening = False
                        try:
                            pcm16 = base64.b64decode(data, validate=True)
                        except ValueError as exc:
                            raise VertexLiveBridgeError("invalid Vertex audio payload") from exc
                        for opus_payload in codec.feed_output(pcm16):
                            await websocket.send_bytes(
                                wrap_opus_frame(opus_payload, protocol_version)
                            )

                generation_complete = bool(
                    _field(content, "generationComplete", "generation_complete")
                )
                turn_complete = bool(_field(content, "turnComplete", "turn_complete"))
                if generation_complete or turn_complete:
                    if state.user_transcript.strip():
                        await _send_xiaozhi_json(
                            websocket,
                            session_id,
                            type="stt",
                            text=state.user_transcript.strip(),
                        )
                        state.user_transcript = ""
                    await finish_turn()

        tasks = {
            asyncio.create_task(device_to_vertex()),
            asyncio.create_task(vertex_to_device()),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
