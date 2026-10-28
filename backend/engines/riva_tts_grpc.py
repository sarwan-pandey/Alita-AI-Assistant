"""
Riva TTS gRPC Client & Protocol Buffer Stubs
=============================================
Pure Python gRPC client for NVIDIA Riva SpeechSynthesisService / NVCF.
Communicates directly with NVIDIA hosted inference at grpc.nvcf.nvidia.com:443
or self-hosted Riva containers.

Zero extra binary dependencies: uses existing grpcio and google.protobuf.
"""

from __future__ import annotations

import io
import logging
import os
import re
import threading
import time
import wave
from typing import Any, Dict, Iterator, List, Optional, Tuple

import grpc
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

log = logging.getLogger("alita.riva_grpc")

# Official NVIDIA NVCF Hosted Inference Defaults
DEFAULT_NVCF_SERVER = "grpc.nvcf.nvidia.com:443"
DEFAULT_CHATTERBOX_FUNCTION_ID = "ddacc747-1269-4fab-bfd9-8f593dead106"
DEFAULT_SAMPLE_RATE_HZ = 24000

# ── Dynamic Protobuf Descriptor Setup ─────────────────────────────────────────

_pool = descriptor_pool.Default()

# 1. riva_common.proto
_common_fd = descriptor_pb2.FileDescriptorProto()
_common_fd.name = "riva/proto/riva_common.proto"
_common_fd.package = "nvidia.riva"
_req_id = _common_fd.message_type.add()
_req_id.name = "RequestId"
_f_val = _req_id.field.add()
_f_val.name = "value"
_f_val.number = 1
_f_val.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING

try:
    _pool.Add(_common_fd)
except TypeError:
    pass  # Already registered

# 2. riva_audio.proto
_audio_fd = descriptor_pb2.FileDescriptorProto()
_audio_fd.name = "riva/proto/riva_audio.proto"
_audio_fd.package = "nvidia.riva"
_enc_enum = _audio_fd.enum_type.add()
_enc_enum.name = "AudioEncoding"
for _vname, _vnum in [
    ("ENCODING_UNSPECIFIED", 0),
    ("LINEAR_PCM", 1),
    ("FLAC", 2),
    ("MULAW", 3),
    ("OGGOPUS", 4),
    ("ALAW", 20),
]:
    _ev = _enc_enum.value.add()
    _ev.name = _vname
    _ev.number = _vnum

try:
    _pool.Add(_audio_fd)
except TypeError:
    pass

# 3. riva_tts.proto
_tts_fd = descriptor_pb2.FileDescriptorProto()
_tts_fd.name = "riva/proto/riva_tts.proto"
_tts_fd.package = "nvidia.riva.tts"
_tts_fd.dependency.extend(["riva/proto/riva_common.proto", "riva/proto/riva_audio.proto"])

# SynthesizeSpeechRequest
_req_msg = _tts_fd.message_type.add()
_req_msg.name = "SynthesizeSpeechRequest"
for _name, _num, _typ, _typ_name in [
    ("text", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, None),
    ("language_code", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, None),
    ("encoding", 3, descriptor_pb2.FieldDescriptorProto.TYPE_ENUM, ".nvidia.riva.AudioEncoding"),
    ("sample_rate_hz", 4, descriptor_pb2.FieldDescriptorProto.TYPE_INT32, None),
    ("voice_name", 5, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, None),
    ("id", 100, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, ".nvidia.riva.RequestId"),
]:
    _f = _req_msg.field.add()
    _f.name = _name
    _f.number = _num
    _f.type = _typ
    if _typ_name:
        _f.type_name = _typ_name

# SynthesizeSpeechResponse
_resp_msg = _tts_fd.message_type.add()
_resp_msg.name = "SynthesizeSpeechResponse"
_f_audio = _resp_msg.field.add()
_f_audio.name = "audio"
_f_audio.number = 1
_f_audio.type = descriptor_pb2.FieldDescriptorProto.TYPE_BYTES

_f_resp_id = _resp_msg.field.add()
_f_resp_id.name = "id"
_f_resp_id.number = 100
_f_resp_id.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
_f_resp_id.type_name = ".nvidia.riva.RequestId"

# RivaSynthesisConfigRequest
_cfg_req = _tts_fd.message_type.add()
_cfg_req.name = "RivaSynthesisConfigRequest"
_f_cm = _cfg_req.field.add()
_f_cm.name = "model_name"
_f_cm.number = 1
_f_cm.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING

# RivaSynthesisConfigResponse
_cfg_resp = _tts_fd.message_type.add()
_cfg_resp.name = "RivaSynthesisConfigResponse"
_inner_cfg = _cfg_resp.nested_type.add()
_inner_cfg.name = "Config"
_f_mod = _inner_cfg.field.add()
_f_mod.name = "model_name"
_f_mod.number = 1
_f_mod.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING

_map_entry = _inner_cfg.nested_type.add()
_map_entry.name = "ParametersEntry"
_map_entry.options.map_entry = True
_kf = _map_entry.field.add()
_kf.name = "key"
_kf.number = 1
_kf.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
_vf = _map_entry.field.add()
_vf.name = "value"
_vf.number = 2
_vf.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING

_f_par = _inner_cfg.field.add()
_f_par.name = "parameters"
_f_par.number = 2
_f_par.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
_f_par.type_name = "ParametersEntry"
_f_par.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED

_f_mc = _cfg_resp.field.add()
_f_mc.name = "model_config"
_f_mc.number = 1
_f_mc.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
_f_mc.type_name = "Config"
_f_mc.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED

try:
    _pool.Add(_tts_fd)
except TypeError:
    pass

# Message Classes
SynthesizeSpeechRequest = message_factory.GetMessageClass(
    _pool.FindMessageTypeByName("nvidia.riva.tts.SynthesizeSpeechRequest")
)
SynthesizeSpeechResponse = message_factory.GetMessageClass(
    _pool.FindMessageTypeByName("nvidia.riva.tts.SynthesizeSpeechResponse")
)
RivaSynthesisConfigRequest = message_factory.GetMessageClass(
    _pool.FindMessageTypeByName("nvidia.riva.tts.RivaSynthesisConfigRequest")
)
RivaSynthesisConfigResponse = message_factory.GetMessageClass(
    _pool.FindMessageTypeByName("nvidia.riva.tts.RivaSynthesisConfigResponse")
)


# ── Credential Sanitization ──────────────────────────────────────────────────

def sanitize_error(exc: Any) -> str:
    """Strip API keys and authorization headers from error messages."""
    text = str(exc)
    text = re.sub(r"nvapi-[A-Za-z0-9_\-]+", "nvapi-[REDACTED]", text)
    text = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]+", "Bearer [REDACTED]", text, flags=re.IGNORECASE)
    return text


def pcm_to_wav(
    pcm_bytes: bytes,
    sample_rate: int = DEFAULT_SAMPLE_RATE_HZ,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Wrap raw 16-bit PCM bytes into standard RIFF WAV container."""
    if not pcm_bytes:
        return b""
    if pcm_bytes.startswith(b"RIFF"):
        return pcm_bytes
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


# ── Riva gRPC Client ──────────────────────────────────────────────────────────

class RivaTTSClient:
    """
    gRPC Client for NVIDIA Riva / NVCF Speech Synthesis Service.
    Supports unary synthesis and online bidirectional streaming synthesis.
    """

    METHOD_SYNTHESIZE = "/nvidia.riva.tts.RivaSpeechSynthesis/Synthesize"
    METHOD_SYNTHESIZE_ONLINE = "/nvidia.riva.tts.RivaSpeechSynthesis/SynthesizeOnline"
    METHOD_GET_CONFIG = "/nvidia.riva.tts.RivaSpeechSynthesis/GetRivaSynthesisConfig"

    def __init__(
        self,
        api_key: str = "",
        server: str = "",
        function_id: str = "",
        timeout: float = 4.0,
        use_ssl: Optional[bool] = None,
    ):
        self._api_key = (api_key or os.getenv("NVIDIA_API_KEY", "")).strip()
        self._server = (server or os.getenv("NVIDIA_RIVA_SERVER", "")).strip() or DEFAULT_NVCF_SERVER
        self._function_id = (
            (function_id or os.getenv("NVIDIA_CHATTERBOX_FUNCTION_ID", "")).strip()
            or DEFAULT_CHATTERBOX_FUNCTION_ID
        )
        self._timeout = float(timeout if timeout is not None else os.getenv("NVIDIA_TTS_TIMEOUT", "4.0"))

        if use_ssl is None:
            # NVCF or :443 defaults to SSL
            self._use_ssl = not (self._server.startswith("localhost") or "127.0.0.1" in self._server)
        else:
            self._use_ssl = use_ssl

        self._channel: Optional[grpc.Channel] = None
        self._channel_lock = threading.Lock()

    @property
    def server(self) -> str:
        return self._server

    @property
    def function_id(self) -> str:
        return self._function_id

    @property
    def available(self) -> bool:
        return bool(self._server and self._api_key)

    def _get_channel(self) -> grpc.Channel:
        if self._channel is not None:
            return self._channel
        with self._channel_lock:
            if self._channel is not None:
                return self._channel

            # gRPC keepalive and message limits (max 32MB)
            options = [
                ("grpc.max_receive_message_length", 32 * 1024 * 1024),
                ("grpc.max_send_message_length", 32 * 1024 * 1024),
                ("grpc.keepalive_time_ms", 30000),
                ("grpc.keepalive_timeout_ms", 10000),
            ]
            if self._use_ssl:
                creds = grpc.ssl_channel_credentials()
                self._channel = grpc.secure_channel(self._server, creds, options=options)
            else:
                self._channel = grpc.insecure_channel(self._server, options=options)
            return self._channel

    def _build_metadata(self) -> List[Tuple[str, str]]:
        meta: List[Tuple[str, str]] = []
        if self._api_key:
            meta.append(("authorization", f"Bearer {self._api_key}"))
        if self._function_id:
            meta.append(("function-id", self._function_id))
        return meta

    def close(self):
        with self._channel_lock:
            if self._channel is not None:
                self._channel.close()
                self._channel = None

    def synthesize(
        self,
        text: str,
        language_code: str = "en-US",
        voice_name: str = "Chatterbox-Multilingual.en-US.Male",
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
        request_id: str = "",
        timeout: Optional[float] = None,
    ) -> bytes:
        """
        Unary speech synthesis via Riva gRPC.
        Returns raw PCM bytes.
        """
        if not text or not text.strip():
            return b""

        channel = self._get_channel()
        stub_method = channel.unary_unary(
            self.METHOD_SYNTHESIZE,
            request_serializer=lambda req: req.SerializeToString(),
            response_deserializer=lambda b: SynthesizeSpeechResponse.FromString(b),
        )

        req = SynthesizeSpeechRequest(
            text=text.strip(),
            language_code=language_code,
            encoding=1,  # LINEAR_PCM
            sample_rate_hz=sample_rate_hz,
            voice_name=voice_name,
        )
        if request_id:
            req.id.value = str(request_id)

        timeout_sec = timeout if timeout is not None else self._timeout
        metadata = self._build_metadata()

        try:
            resp: SynthesizeSpeechResponse = stub_method(req, metadata=metadata, timeout=timeout_sec)
            return resp.audio
        except grpc.RpcError as rpc_err:
            sanitized = sanitize_error(rpc_err)
            log.warning("[riva_grpc] Synthesis RPC failed (%s): %s", rpc_err.code(), sanitized)
            raise

    def synthesize_stream(
        self,
        text: str,
        language_code: str = "en-US",
        voice_name: str = "Chatterbox-Multilingual.en-US.Male",
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
        request_id: str = "",
        timeout: Optional[float] = None,
    ) -> Iterator[bytes]:
        """
        Streaming online speech synthesis via SynthesizeOnline.
        Yields raw PCM audio chunks as they arrive from server.
        """
        if not text or not text.strip():
            return

        channel = self._get_channel()
        stream_method = channel.stream_stream(
            self.METHOD_SYNTHESIZE_ONLINE,
            request_serializer=lambda req: req.SerializeToString(),
            response_deserializer=lambda b: SynthesizeSpeechResponse.FromString(b),
        )

        req = SynthesizeSpeechRequest(
            text=text.strip(),
            language_code=language_code,
            encoding=1,  # LINEAR_PCM
            sample_rate_hz=sample_rate_hz,
            voice_name=voice_name,
        )
        if request_id:
            req.id.value = str(request_id)

        def _request_gen():
            yield req

        timeout_sec = timeout if timeout is not None else self._timeout
        metadata = self._build_metadata()

        try:
            response_iterator = stream_method(_request_gen(), metadata=metadata, timeout=timeout_sec)
            for chunk in response_iterator:
                if chunk.audio:
                    yield chunk.audio
        except grpc.RpcError as rpc_err:
            sanitized = sanitize_error(rpc_err)
            log.warning("[riva_grpc] Streaming RPC failed (%s): %s", rpc_err.code(), sanitized)
            raise

    def get_synthesis_config(self, model_name: str = "", timeout: float = 5.0) -> Dict[str, Any]:
        """Query Riva server configuration via GetRivaSynthesisConfig."""
        channel = self._get_channel()
        stub_method = channel.unary_unary(
            self.METHOD_GET_CONFIG,
            request_serializer=lambda req: req.SerializeToString(),
            response_deserializer=lambda b: RivaSynthesisConfigResponse.FromString(b),
        )
        req = RivaSynthesisConfigRequest(model_name=model_name)
        metadata = self._build_metadata()
        resp: RivaSynthesisConfigResponse = stub_method(req, metadata=metadata, timeout=timeout)

        models = {}
        for mc in resp.model_config:
            models[mc.model_name] = dict(mc.parameters)
        return models
