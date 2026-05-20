import wave
from pathlib import Path
from typing import BinaryIO

import requests
from loguru import logger

from .tts_interface import TTSInterface


class TTSEngine(TTSInterface):
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:50001",
        mode: str = "zero_shot",
        spk_id: str = "fay_default",
        prompt_text: str = "You are a helpful assistant.<|endofprompt|>希望你以后能够做的比我还好呦。",
        prompt_wav: str = "/mnt/d/AI/fay/third_party/CosyVoice/asset/zero_shot_prompt.wav",
        instruct_text: str = "",
        sample_rate: int = 24000,
        timeout: int = 180,
    ):
        self.base_url = base_url.rstrip("/")
        self.mode = mode
        self.spk_id = spk_id
        self.prompt_text = prompt_text
        self.prompt_wav = prompt_wav
        self.instruct_text = instruct_text
        self.sample_rate = sample_rate
        self.timeout = timeout

    def generate_audio(self, text: str, file_name_no_ext=None) -> str:
        audio_bytes = self._request_tts(text)
        output_path = self.generate_cache_file_name(file_name_no_ext, "wav")

        with wave.open(output_path, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(audio_bytes)

        return output_path

    def _request_tts(self, text: str) -> bytes:
        url = f"{self.base_url}/inference_{self.mode}"
        data = {"tts_text": text}
        files: dict[str, tuple[str, BinaryIO, str]] | None = None
        prompt_file: BinaryIO | None = None

        try:
            if self.mode == "sft":
                data["spk_id"] = self.spk_id
            elif self.mode == "zero_shot":
                data["prompt_text"] = self.prompt_text
                prompt_file = self._open_prompt_wav()
                files = {"prompt_wav": ("prompt.wav", prompt_file, "audio/wav")}
            elif self.mode == "cross_lingual":
                prompt_file = self._open_prompt_wav()
                files = {"prompt_wav": ("prompt.wav", prompt_file, "audio/wav")}
            elif self.mode == "instruct":
                data["spk_id"] = self.spk_id
                data["instruct_text"] = self.instruct_text
            elif self.mode == "instruct2":
                data["instruct_text"] = self.instruct_text
                prompt_file = self._open_prompt_wav()
                files = {"prompt_wav": ("prompt.wav", prompt_file, "audio/wav")}
            else:
                raise ValueError(f"Unsupported CosyVoice3 mode: {self.mode}")

            response = requests.post(
                url,
                data=data,
                files=files,
                timeout=self.timeout,
            )
        finally:
            if prompt_file is not None:
                prompt_file.close()

        if response.status_code != 200:
            detail = response.text[:500] if response.text else ""
            raise RuntimeError(
                f"CosyVoice3 TTS failed: HTTP {response.status_code} {detail}"
            )

        if not response.content:
            raise RuntimeError("CosyVoice3 TTS returned empty audio content")

        logger.debug(f"CosyVoice3 TTS generated {len(response.content)} bytes")
        return response.content

    def _open_prompt_wav(self) -> BinaryIO:
        if not self.prompt_wav:
            raise ValueError(f"CosyVoice3 mode {self.mode} requires prompt_wav")

        prompt_path = Path(self.prompt_wav)
        if not prompt_path.exists():
            raise FileNotFoundError(f"CosyVoice3 prompt_wav not found: {prompt_path}")

        return prompt_path.open("rb")
