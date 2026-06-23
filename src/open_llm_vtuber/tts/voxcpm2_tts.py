import wave

import requests
from loguru import logger

from .tts_interface import TTSInterface


class TTSEngine(TTSInterface):
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:50005",
        control: str = "",
        prompt_wav_path: str = "",
        prompt_text: str = "",
        reference_wav_path: str = "",
        cfg_value: float = 2.0,
        temperature: float = 1.0,
        max_generate_length: int = 1500,
        inference_timesteps: int = 5,
        normalize: bool = False,
        denoise: bool = False,
        retry_badcase: bool = False,
        sample_rate: int = 48000,
        timeout: float = 180,
    ):
        self.base_url = base_url.rstrip("/")
        self.control = control
        self.prompt_wav_path = prompt_wav_path
        self.prompt_text = prompt_text
        self.reference_wav_path = reference_wav_path
        self.cfg_value = cfg_value
        self.temperature = temperature
        self.max_generate_length = max_generate_length
        self.inference_timesteps = inference_timesteps
        self.normalize = normalize
        self.denoise = denoise
        self.retry_badcase = retry_badcase
        self.sample_rate = sample_rate
        self.timeout = timeout

    def generate_audio(self, text: str, file_name_no_ext=None) -> str:
        audio = self._request_tts(text)
        output_path = self.generate_cache_file_name(file_name_no_ext, "wav")

        if audio.startswith(b"RIFF"):
            with open(output_path, "wb") as wav_file:
                wav_file.write(audio)
        else:
            with wave.open(output_path, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(audio)

        return output_path

    def _request_tts(self, text: str) -> bytes:
        payload = {
            "text": text,
            "cfg_value": self.cfg_value,
            "temperature": self.temperature,
            "max_generate_length": self.max_generate_length,
            "inference_timesteps": self.inference_timesteps,
            "normalize": self.normalize,
            "denoise": self.denoise,
            "retry_badcase": self.retry_badcase,
        }

        if self.control:
            payload["control"] = self.control
        if self.reference_wav_path:
            payload["reference_wav_path"] = self.reference_wav_path
        if self.prompt_wav_path or self.prompt_text:
            if not self.prompt_wav_path or not self.prompt_text:
                raise ValueError(
                    "VoxCPM2 prompt_wav_path and prompt_text must be configured together"
                )
            payload["prompt_wav_path"] = self.prompt_wav_path
            payload["prompt_text"] = self.prompt_text

        response = requests.post(
            f"{self.base_url}/tts",
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code != 200:
            detail = response.text[:500] if response.text else ""
            raise RuntimeError(f"VoxCPM2 TTS failed: HTTP {response.status_code} {detail}")
        if not response.content:
            raise RuntimeError("VoxCPM2 TTS returned empty audio")

        logger.debug(f"VoxCPM2 TTS generated {len(response.content)} bytes")
        return response.content
