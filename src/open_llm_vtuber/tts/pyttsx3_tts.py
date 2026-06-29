import os
import sys
import threading

import pythoncom
import win32com.client
from loguru import logger

from .tts_interface import TTSInterface

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)


# using https://github.com/thevickypedia/py3-tts because pyttsx3 is unmaintained and not working


class TTSEngine(TTSInterface):
    def __init__(self):
        self.temp_audio_file = "temp"
        self.file_extension = "wav"
        self.new_audio_dir = "cache"
        self.lock = threading.Lock()
        self.voice_match = "Kangkang"

        if not os.path.exists(self.new_audio_dir):
            os.makedirs(self.new_audio_dir)

    #! This method (pyttsx3) is not thread safe. It will blow if it's called from multiple threads at the same time.
    def generate_audio(self, text, file_name_no_ext=None):
        logger.debug(f"Start Generating {file_name_no_ext}")
        file_name = self.generate_cache_file_name(file_name_no_ext, self.file_extension)

        with self.lock:
            self._speak_to_wav(text, file_name)
        logger.info(f"Finished Generating {file_name}")
        return file_name

    def _speak_to_wav(self, text: str, file_name: str) -> None:
        pythoncom.CoInitialize()
        try:
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            self._select_voice(voice)

            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            stream.Open(os.path.abspath(file_name), 3, False)
            try:
                voice.AudioOutputStream = stream
                voice.Speak(text, 0)
            finally:
                stream.Close()
        finally:
            pythoncom.CoUninitialize()

    def _select_voice(self, voice) -> None:
        voices = voice.GetVoices()
        for idx in range(voices.Count):
            token = voices.Item(idx)
            description = token.GetDescription()
            if self.voice_match in description or self.voice_match in token.Id:
                voice.Voice = token
                logger.debug(f"pyttsx3_tts selected SAPI voice: {description}")
                return

        logger.warning("pyttsx3_tts preferred Chinese male voice Kangkang not found")


if __name__ == "__main__":
    TTSEngine = TTSEngine()
    TTSEngine.generate_audio(
        "Hello, this is a test. But this is not a test. You are screwed bro. You only live once. YOLO."
    )

    def worker(engine, text, index):
        file_name = f"audio_{index}"
        engine.generate_audio(text, file_name)

    texts = [
        "Hello, this is a test.",
        "This is another test.",
        "Yet another test sentence.",
        "Testing multithreading.",
        "Final test sentence.",
    ]

    threads = []
    for i, text in enumerate(texts):
        t = threading.Thread(target=worker, args=(TTSEngine, text, i))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()
