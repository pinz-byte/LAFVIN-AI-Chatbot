from __future__ import annotations

import asyncio
import base64
import json
import logging
import struct
import uuid
from dataclasses import dataclass

import google.auth
from fastapi import WebSocket
from google.auth.transport.requests import Request as GoogleAuthRequest
from websockets.asyncio.client import connect as connect_websocket

from .audio import XiaozhiAudioCodec, amplify_pcm16, unwrap_opus_frame, wrap_opus_frame
from .config import GatewaySettings


logger = logging.getLogger("uvicorn.error")


class VertexLiveBridgeError(RuntimeError):
    pass


@dataclass
class VertexBridgeState:
    listening: bool = False
    tts_active: bool = False
    discard_output: bool = False
    user_transcript: str = ""
    assistant_transcript: str = ""
    input_frames: int = 0
    input_pcm_bytes: int = 0
    input_abs_sum: int = 0
    input_samples: int = 0
    input_peak: int = 0
    output_pcm_bytes: int = 0


def _reset_vertex_audio_metrics(state: VertexBridgeState) -> None:
    state.input_frames = 0
    state.input_pcm_bytes = 0
    state.input_abs_sum = 0
    state.input_samples = 0
    state.input_peak = 0
    state.output_pcm_bytes = 0


def _record_vertex_input_pcm(state: VertexBridgeState, pcm16: bytes) -> None:
    if len(pcm16) % 2:
        raise VertexLiveBridgeError("decoded device PCM has an odd byte count")
    state.input_frames += 1
    state.input_pcm_bytes += len(pcm16)
    for (sample,) in struct.iter_unpack("<h", pcm16):
        magnitude = abs(sample)
        state.input_abs_sum += magnitude
        state.input_peak = max(state.input_peak, magnitude)
        state.input_samples += 1


def _vertex_input_mean_abs(state: VertexBridgeState) -> int:
    if not state.input_samples:
        return 0
    return state.input_abs_sum // state.input_samples


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
                "realtime_input_config": {
                    "automatic_activity_detection": {"disabled": True}
                },
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


def _decode_vertex_server_event(raw_message: object) -> dict[str, object] | None:
    """Decode JSON carried in either Vertex text or binary WebSocket frames."""
    if isinstance(raw_message, bytes):
        try:
            raw_message = raw_message.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(raw_message, str):
        return None
    try:
        event = json.loads(raw_message)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


async def _send_xiaozhi_json(websocket: WebSocket, session_id: str, **payload: object) -> None:
    await websocket.send_json({"session_id": session_id, **payload})


async def _handle_vertex_listen_event(
    event: dict[str, object], upstream: object, state: VertexBridgeState, codec: XiaozhiAudioCodec
) -> None:
    listen_state = event.get("state")
    if listen_state == "start":
        state.discard_output = False
        was_listening = state.listening
        state.listening = True
        _reset_vertex_audio_metrics(state)
        codec.clear_output()
        logger.info("Vertex listen started")
        if not was_listening:
            await upstream.send(
                json.dumps(
                    {"realtime_input": {"activity_start": {}}},
                    separators=(",", ":"),
                )
            )
    elif listen_state == "stop":
        was_listening = state.listening
        state.listening = False
        logger.info(
            "Vertex listen stopped: frames=%d pcm_bytes=%d mean_abs=%d peak=%d",
            state.input_frames,
            state.input_pcm_bytes,
            _vertex_input_mean_abs(state),
            state.input_peak,
        )
        if was_listening:
            # The LAFVIN DOWN button provides the authoritative push-to-talk
            # boundary. Explicit activity events avoid depending on Vertex VAD
            # to recognize this board's attenuated microphone signal.
            await upstream.send(
                json.dumps(
                    {"realtime_input": {"activity_end": {}}},
                    separators=(",", ":"),
                )
            )
    elif listen_state == "detect":
        state.discard_output = False
        state.user_transcript = ""


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
            raw_setup_response = await asyncio.wait_for(upstream.recv(), timeout=8)
        except asyncio.TimeoutError as exc:
            raise VertexLiveBridgeError("Vertex Live setup timed out") from exc
        setup_response = _decode_vertex_server_event(raw_setup_response)
        if setup_response is None:
            raise VertexLiveBridgeError("Vertex Live returned an invalid setup response")
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
                    _record_vertex_input_pcm(state, pcm16)
                    pcm16 = amplify_pcm16(pcm16, settings.vertex_input_gain)
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
                    await _handle_vertex_listen_event(event, upstream, state, codec)
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
                event = _decode_vertex_server_event(raw_message)
                if event is None:
                    continue
                if "error" in event:
                    error = event.get("error") or {}
                    logger.error(
                        "Vertex Live returned error code %s",
                        error.get("code", "unknown"),
                    )
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
                        logger.info(
                            "Vertex input transcription finished: chars=%d",
                            len(state.user_transcript.strip()),
                        )
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
                        state.output_pcm_bytes += len(pcm16)
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
                    if turn_complete:
                        logger.info(
                            "Vertex turn completed: output_pcm_bytes=%d",
                            state.output_pcm_bytes,
                        )

            logger.info(
                "Vertex stream closed: frames=%d pcm_bytes=%d mean_abs=%d "
                "peak=%d output_pcm_bytes=%d",
                state.input_frames,
                state.input_pcm_bytes,
                _vertex_input_mean_abs(state),
                state.input_peak,
                state.output_pcm_bytes,
            )

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
